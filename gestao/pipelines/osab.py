from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db.models import Max, Q
from django.utils import timezone

from ..excel import as_aware, converter_data_robusto, resolver_coluna, texto
from ..models import (
    AnaliseCapilaridade,
    ConfiguracaoOSAB,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    MetaCapilaridade,
    PoliticaComissao,
    VendaOSAB,
)
from ..parceiros import indice_parceiros, resolver_parceiro_id, sincronizar_parceiros_osab
from ..periodo import anomes, hoje
from ..terceiros import (
    CARGOS_AUDITORIA_DEDICADOS,
    cargo_elegivel_capilaridade,
    chaves_elegiveis_capilaridade,
    classificar_cargo_auditoria,
    listar_terceiros_do_parceiro,
    mapa_terceiros_por_chave,
    normalizar_cargo_ctps,
    normalizar_chave_tt,
    terceiro_ativo_para_auditoria,
    terceiro_elegivel_capilaridade,
)
from tickets.models import Parceiro

from .comissao import receita_mix

ALIASES_PEDIDO = ["PEDIDO", "NUMERO_PEDIDO", "PEDIDO_ID", "NUMERO_ORDEM"]
ALIASES_DT_REF = ["DT_REF", "DATA_REF", "DT_REFERENCIA", "DATA_REFERENCIA"]
STATUS_IGNORADOS = [
    "Reprovado Analise de Fraude-PAYMENT_NOT_AUTHORIZED_RULE",
    "Aguardando Pagamento-INVALID_SESSION_DATA",
    "Draft-PAYMENT_STATUS_FAILED",
    "Draft-INVALID_SESSION_DATA",
    "Draft-SESSION_DATA_INVALID",
    "Aguardando Pagamento-PAYMENT_STATUS_FAILED",
]
BONUS_M10_VALOR = 150
BONUS_M10_MESES = 10


def data_ref_capilaridade() -> datetime:
    agora = timezone.localtime()
    return (agora - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def persistir_vendas_osab(df: pd.DataFrame, indice=None) -> dict:
    if indice is None:
        indice = indice_parceiros()
    col_pedido = resolver_coluna(df, ALIASES_PEDIDO)
    col_dt_ref = resolver_coluna(df, ALIASES_DT_REF)
    if not col_pedido or not col_dt_ref:
        raise ValueError(
            "A planilha OSAB precisa de PEDIDO e DT_REF. "
            f"Colunas: {list(df.columns)}"
        )
    trabalho = df.rename(columns={col_pedido: "PEDIDO", col_dt_ref: "DT_REF"}).copy()
    if "NOME_VENDEDOR" not in trabalho.columns and "MATRICULA_VENDEDOR" in trabalho.columns:
        trabalho["NOME_VENDEDOR"] = trabalho["MATRICULA_VENDEDOR"].astype(str)
    for col in ("DATA_ABERTURA", "DATA_FECHAMENTO", "DT_REF"):
        if col in trabalho.columns:
            trabalho[col] = converter_data_robusto(trabalho[col])
    trabalho = trabalho.dropna(subset=["DATA_ABERTURA", "DESCRICAO", "PEDIDO", "DT_REF"])
    trabalho["PEDIDO_STR"] = trabalho["PEDIDO"].astype(str).str.strip()
    trabalho = trabalho[trabalho["PEDIDO_STR"] != ""]
    if trabalho.empty:
        return {"inseridos": 0, "atualizados": 0, "ignorados": 0}

    col_gc = resolver_coluna(trabalho, ["nm_gc", "NM_GC", "NOME_GC", "nome_gc"])
    col_sap = resolver_coluna(trabalho, ["PDV_SAP", "pdv_sap"])
    col_mun = resolver_coluna(trabalho, [
        "MUNICIPIO",
        "NM_MUNICIPIO",
        "CIDADE",
        "MUNICÍPIO",
        "NM_MUNICIPIO_INSTALACAO",
        "CIDADE_INSTALACAO",
        "PRACA",
        "PRAÇA",
        "NM_PRACA",
    ])
    col_oferta = resolver_coluna(trabalho, [
        "OFERTA",
        "PRODUTO",
        "PLANO",
        "NOME_OFERTA",
        "NOME_PLANO",
        "PACOTE",
        "DESCRICAO_OFERTA",
    ])
    col_gerencia = resolver_coluna(trabalho, [
        "GERENCIA",
        "GERÊNCIA",
        "NM_GERENCIA",
        "NM_GERÊNCIA",
        "GESTAO",
        "GESTÃO",
    ])
    col_pgto = resolver_coluna(trabalho, [
        "MEIO_PAGAMENTO",
        "meio_pagamento",
        "FORMA_PAGAMENTO",
        "FORMA_PGTO",
        "PAGAMENTO",
    ])
    existentes = {v.pedido: v for v in VendaOSAB.objects.filter(pedido__isnull=False)}
    inseridos = atualizados = ignorados = 0
    for _, row in trabalho.iterrows():
        pedido = texto(row["PEDIDO_STR"], 100)
        dt_ref = as_aware(row["DT_REF"])
        if not pedido or dt_ref is None:
            ignorados += 1
            continue
        pdv_nome = texto(row.get("DESCRICAO"), 150)
        dados = {
            "dt_ref": dt_ref,
            "matricula_vendedor": texto(row.get("MATRICULA_VENDEDOR"), 100),
            "nome_vendedor": texto(row.get("NOME_VENDEDOR"), 200),
            "pdv_nome": pdv_nome,
            "parceiro_id": resolver_parceiro_id(pdv_nome, indice),
            "data_abertura": as_aware(row.get("DATA_ABERTURA")),
            "data_fechamento": as_aware(row.get("DATA_FECHAMENTO")),
            "situacao": texto(row.get("SITUACAO"), 200),
            "velocidade": texto(row.get("VELOCIDADE"), 100),
            "meio_pagamento": texto(row.get(col_pgto), 100) if col_pgto else "",
        }
        if col_gc:
            dados["nm_gc"] = texto(row.get(col_gc), 120)
        if col_sap:
            dados["pdv_sap"] = texto(row.get(col_sap), 32)
        if col_mun:
            dados["municipio"] = texto(row.get(col_mun), 120)
        if col_oferta:
            dados["oferta"] = texto(row.get(col_oferta), 200)
        if col_gerencia:
            dados["gerencia"] = texto(row.get(col_gerencia), 120)
        if pedido in existentes:
            reg = existentes[pedido]
            mudou_meta = False
            if dados.get("pdv_sap") and dados["pdv_sap"] != (reg.pdv_sap or ""):
                reg.pdv_sap = dados["pdv_sap"]
                mudou_meta = True
            if dados.get("nm_gc") and dados["nm_gc"] != (reg.nm_gc or ""):
                reg.nm_gc = dados["nm_gc"]
                mudou_meta = True
            if dados.get("municipio") and dados["municipio"] != (reg.municipio or ""):
                reg.municipio = dados["municipio"]
                mudou_meta = True
            if dados.get("oferta") and dados["oferta"] != (reg.oferta or ""):
                reg.oferta = dados["oferta"]
                mudou_meta = True
            if dados.get("gerencia") and dados["gerencia"] != (reg.gerencia or ""):
                reg.gerencia = dados["gerencia"]
                mudou_meta = True
            if reg.dt_ref is None or dt_ref > reg.dt_ref:
                for k, v in dados.items():
                    setattr(reg, k, v)
                reg.save()
                atualizados += 1
            elif mudou_meta:
                campos = [
                    c
                    for c in ("pdv_sap", "nm_gc", "municipio", "oferta", "gerencia")
                    if dados.get(c)
                ]
                reg.save(update_fields=campos)
                ignorados += 1
            else:
                ignorados += 1
        else:
            novo = VendaOSAB.objects.create(pedido=pedido, **dados)
            existentes[pedido] = novo
            inseridos += 1
    return {"inseridos": inseridos, "atualizados": atualizados, "ignorados": ignorados}


def _dias_desde(ultima, ref: datetime) -> int | None:
    if ultima is None:
        return None
    ultima_dia = ultima.date() if hasattr(ultima, "date") else ultima
    return (ref.date() - ultima_dia).days


def ultimas_vendas_pdv(pdv_nome: str) -> dict[str, datetime]:
    mapa: dict[str, datetime] = {}
    qs = (
        VendaOSAB.objects.filter(pdv_nome=pdv_nome, data_abertura__isnull=False)
        .exclude(matricula_vendedor="")
        .values("matricula_vendedor")
        .annotate(ultima=Max("data_abertura"))
    )
    for row in qs:
        chave = normalizar_chave_tt(row["matricula_vendedor"])
        if chave and row["ultima"]:
            mapa[chave] = row["ultima"]
    return mapa


def _terceiro_passa_filtro(terceiro, filtros: dict | None) -> bool:
    filtros = filtros or {}
    tt = (filtros.get("tt") or "").strip().upper()
    nome = (filtros.get("nome") or "").strip().lower()
    cargo = (filtros.get("cargo") or "").strip()
    situacao = (filtros.get("situacao") or "").strip().lower()
    chave = normalizar_chave_tt(terceiro.chave_acesso) or ""
    if tt and tt not in chave:
        return False
    if nome and nome not in (terceiro.nome_terceiro or "").lower():
        return False
    if cargo and normalizar_cargo_ctps(terceiro.cargo_funcao) != normalizar_cargo_ctps(cargo):
        return False
    if situacao:
        campos = {
            (terceiro.situacao_funcional or "").strip().lower(),
            (terceiro.situacao_empresa or "").strip().lower(),
            (terceiro.situacao_contrato or "").strip().lower(),
        }
        if situacao not in campos:
            return False
    return True


def _filtros_ativos(filtros: dict | None) -> bool:
    filtros = filtros or {}
    return any((filtros.get(k) or "").strip() for k in ("tt", "nome", "cargo", "situacao", "pdv"))


def linhas_capilaridade_pdv(parceiro: Parceiro, filtros: dict | None = None) -> list[dict]:
    data_ref = data_ref_capilaridade()
    ultimas = ultimas_vendas_pdv(parceiro.nome)
    linhas: list[dict] = []
    vistos: set[str] = set()
    cargo_filtro = (filtros or {}).get("cargo") or ""
    situacao_filtro = (filtros or {}).get("situacao") or ""
    for terceiro in listar_terceiros_do_parceiro(parceiro.id):
        if not _terceiro_passa_filtro(terceiro, filtros):
            continue
        if not situacao_filtro and not terceiro_elegivel_capilaridade(
            terceiro.situacao_empresa,
            terceiro.situacao_funcional,
            terceiro.situacao_contrato,
        ):
            continue
        if not cargo_filtro and not cargo_elegivel_capilaridade(terceiro.cargo_funcao):
            continue
        chave = normalizar_chave_tt(terceiro.chave_acesso)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        ultima = ultimas.get(chave)
        if ultima is None:
            linhas.append(
                {
                    "matricula_vendedor": chave,
                    "nome_vendedor": terceiro.nome_terceiro,
                    "cargo_funcao": terceiro.cargo_funcao,
                    "situacao_funcional": terceiro.situacao_funcional,
                    "pdv_nome": parceiro.nome,
                    "parceiro_id": parceiro.id,
                    "ultima_venda": None,
                    "dias_sem_vender": None,
                    "sem_venda_osab": True,
                    "status": "Inativo",
                }
            )
            continue
        dias = _dias_desde(ultima, data_ref)
        linhas.append(
            {
                "matricula_vendedor": chave,
                "nome_vendedor": terceiro.nome_terceiro,
                "cargo_funcao": terceiro.cargo_funcao,
                "situacao_funcional": terceiro.situacao_funcional,
                "pdv_nome": parceiro.nome,
                "parceiro_id": parceiro.id,
                "ultima_venda": ultima,
                "dias_sem_vender": dias if dias is not None else 999,
                "sem_venda_osab": False,
                "status": "Ativo" if dias is not None and dias <= 7 else "Inativo",
            }
        )
    return linhas


def contar_operadores_ativos(parceiro: Parceiro) -> int:
    data_ref = data_ref_capilaridade()
    mapa = mapa_terceiros_por_chave()
    ultimas = ultimas_vendas_pdv(parceiro.nome)
    total = 0
    for chave, ultima in ultimas.items():
        terceiro = mapa.get(chave)
        if not terceiro_ativo_para_auditoria(terceiro):
            continue
        cargo = normalizar_cargo_ctps(terceiro.cargo_funcao if terceiro else "")
        if cargo not in CARGOS_AUDITORIA_DEDICADOS:
            continue
        dias = _dias_desde(ultima, data_ref)
        if dias is not None and dias <= 7:
            total += 1
    return total


def contar_ativos_pdv(
    parceiro: Parceiro,
    linhas: list[dict] | None = None,
    filtros: dict | None = None,
) -> int:
    if linhas is None:
        linhas = linhas_capilaridade_pdv(parceiro, filtros)
    base = sum(1 for l in linhas if l["status"] == "Ativo")
    if _filtros_ativos(filtros) and any(
        (filtros or {}).get(k) for k in ("tt", "nome", "cargo", "situacao")
    ):
        return base
    return base + contar_operadores_ativos(parceiro)


def persistir_capilaridade(ano: int, mes: int) -> dict:
    data_analise = hoje()
    AnaliseCapilaridade.objects.filter(ano_referencia=ano, mes_referencia=mes).delete()
    total = 0
    ativos = 0
    for parceiro in Parceiro.objects.filter(ativo=True):
        for linha in linhas_capilaridade_pdv(parceiro):
            AnaliseCapilaridade.objects.create(
                data_analise=data_analise,
                ano_referencia=ano,
                mes_referencia=mes,
                matricula_vendedor=linha["matricula_vendedor"],
                nome_vendedor=linha["nome_vendedor"] or "",
                pdv_nome=linha["pdv_nome"],
                parceiro_id=linha["parceiro_id"],
                dias_sem_vender=linha["dias_sem_vender"],
                status=linha["status"],
                ultima_venda=linha["ultima_venda"],
                sem_venda_osab=linha["sem_venda_osab"],
            )
            total += 1
            if linha["status"] == "Ativo":
                ativos += 1
    return {"linhas": total, "ativos": ativos, "ano": ano, "mes": mes}


def _bonus_m10(parceiro_id: int, ano: int, mes: int, valor_unitario: int | None = None) -> dict:
    ref = date(int(ano), int(mes), 1) - relativedelta(months=BONUS_M10_MESES)
    anomes_safra = anomes(ref.year, ref.month)
    ultima = HistoricoChurn.objects.filter(parceiro_id=parceiro_id).order_by("-data_analise").first()
    row = None
    if ultima:
        row = HistoricoChurn.objects.filter(
            data_analise=ultima.data_analise,
            parceiro_id=parceiro_id,
            anomes_gross=anomes_safra,
        ).first()
    if row:
        remanescentes = max(0, int(row.remanescentes))
        gross = max(0, int(row.gross))
        churn = max(0, int(row.churn))
    else:
        g = GrossMensal.objects.filter(parceiro_id=parceiro_id, anomes=anomes_safra).first()
        gross = max(0, int(g.gross)) if g else 0
        churn = 0
        remanescentes = gross
    unitario = int(valor_unitario) if valor_unitario is not None else BONUS_M10_VALOR
    return {
        "safra_label": f"{ref.month:02d}/{ref.year}",
        "gross": gross,
        "churn": churn,
        "remanescentes": remanescentes,
        "bonus_total": float(remanescentes * unitario),
    }


def _dias_civis_fechados(hoje_ref: date, ano: int, mes: int) -> int:
    ult = monthrange(ano, mes)[1]
    if hoje_ref.year != ano or hoje_ref.month != mes:
        return ult
    return max(0, min(hoje_ref.day - 1, ult))


def _projecao_linear(realizado: float, hoje_ref: date, ano: int, mes: int) -> float:
    dias_totais = monthrange(ano, mes)[1]
    base = max(1, _dias_civis_fechados(hoje_ref, ano, mes))
    return (realizado / base) * dias_totais


PLANOS_LOW = {"400", "500", "600"}
PLANOS_HIGH = {"800", "1000", "1000_mesh"}


def _brl(valor: float) -> str:
    return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(valor: float, casas: int = 2) -> str:
    return f"{float(valor):.{casas}f}%".replace(".", ",")


def _eh_cartao(meio: str) -> bool:
    txt = (meio or "").upper()
    if "DEBIT" in txt or "DÉBIT" in txt or "DACC" in txt:
        return False
    return "CART" in txt or "CRÉDIT" in txt or "CREDIT" in txt


def _contar_cartao(vendas: list) -> int:
    return sum(1 for v in vendas if _eh_cartao(getattr(v, "meio_pagamento", "") or ""))


def relatorios_osab_atuais(parceiros, limite: int = 80):
    """Um relatório por PDV: o mais recente. Evita misturar o snapshot de ontem com o de hoje."""
    qs = (
        HistoricoOSAB.objects.select_related("parceiro", "parceiro__especialista")
        .filter(Q(parceiro__in=parceiros) | Q(parceiro__isnull=True))
        .order_by("-data_processamento")
    )
    vistos: set = set()
    out = []
    for h in qs:
        chave = h.parceiro_id if h.parceiro_id else f"nome:{h.descricao_pdv}"
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(h)
        if len(out) >= limite:
            break
    return out


def montar_mensagem_osab(
    pdv_nome: str,
    hoje_ref: date,
    ano: int,
    mes: int,
    realizado_vl: int,
    realizado_gross: int,
    config,
    proj_vl: float,
    proj_gross: float,
    atingimento_vl: float,
    atingimento_gross: float,
    mix: dict,
    cartao_vl: int,
    cartao_gross: int,
    comissao_base: float,
    bonus: float,
    comissao_base_proj: float,
    bonus_proj: float,
    comissao_proj: float,
    capilaridade: dict | None,
) -> str:
    mes_label = f"{mes:02d}/{ano}"
    fechados = _dias_civis_fechados(hoje_ref, ano, mes)
    if fechados <= 0:
        ate = hoje_ref
    else:
        ate = date(ano, mes, min(fechados, monthrange(ano, mes)[1]))
    ticket = (comissao_proj / proj_gross) if proj_gross else 0.0
    meta_gross_rs = (config.meta_gross * ticket) if config.meta_gross else 0.0
    gap = comissao_proj - meta_gross_rs
    aproveitamento = (realizado_gross / realizado_vl * 100) if realizado_vl else 0.0
    low = sum(int(mix.get(k, 0) or 0) for k in PLANOS_LOW)
    high = sum(int(mix.get(k, 0) or 0) for k in PLANOS_HIGH)
    outros = int(mix.get("outros", 0) or 0)
    total_mix = max(1, realizado_gross)
    pct_cartao_vl = (cartao_vl / realizado_vl * 100) if realizado_vl else 0.0
    pct_cartao_gr = (cartao_gross / realizado_gross * 100) if realizado_gross else 0.0

    partes = [
        f"🤖 *Relatório financeiro e desempenho - {pdv_nome}*",
        f"📊 *Meta VL (Mês {mes_label}):* {config.meta_vl}",
        f"   - Realizado: *{realizado_vl}* (Vendas Válidas)",
        f"   - Projetado: *{proj_vl:.0f}*",
        f"   - Atingimento: *{_pct(atingimento_vl)}*",
        f"📊 *Meta Gross (Mês {mes_label}):* {config.meta_gross} ({_brl(meta_gross_rs)})",
        f"📈 *Desempenho Gross (Até {ate.strftime('%d/%m')}):*",
        f"   - Realizado: *{realizado_gross}*",
        f"   - Projetado: *{proj_gross:.0f}*",
        f"   - Atingimento: *{_pct(atingimento_gross)}*",
        f"   - Aproveitamento: *{_pct(aproveitamento, 1)}*",
    ]
    if capilaridade:
        partes.extend(
            [
                f"📊 *Resumo de Capilaridade - {hoje_ref.strftime('%d/%m/%Y')}*",
                f"🎯 *Meta de Vendedores Ativos:* {capilaridade['meta']}",
                f"🟢 *Vendedores Ativos (≤ 7 dias):* {capilaridade['ativos']}",
                f"🔴 *Vendedores Inativos (≥ 8 dias):* {capilaridade['inativos']}",
                f"📈 *Atingimento da Meta de vendedores:* {_pct(capilaridade['atingimento'])}",
            ]
        )
    partes.extend(
        [
            "🚀 *Mix de Velocidades (Vendas Concluídas):*",
            f"   - Total: *{realizado_gross}*",
            f"   - Low (400/500/600Mbps): *{low} vendas ({_pct(low / total_mix * 100)})*",
            f"   - High (800/1000Mbps): *{high} vendas ({_pct(high / total_mix * 100)})*",
        ]
    )
    if outros:
        partes.append(f"   - Outros: *{outros} vendas ({_pct(outros / total_mix * 100)})*")
    partes.extend(
        [
            "💸 *Mix de Pagamentos:*",
            f"   - Total de Vendas no Mês: *{realizado_vl}*",
            f"   - % Cartão de Crédito s/ VLs: *{_pct(pct_cartao_vl)} ({cartao_vl} vendas)*",
            f"   - % Cartão de Crédito s/ Gross: *{_pct(pct_cartao_gr)} ({cartao_gross} vendas)*",
            f"💰 *Comissão Realizada (Até {ate.strftime('%d/%m')}):*",
            f"   - Básica: {_brl(comissao_base)}",
            f"   - Bônus: {_brl(bonus)}",
            f"   - *Total Realizado: {_brl(comissao_base + bonus)}*",
            "💰 *Comissão Projetada (Final do Mês):*",
            f"   - Básica: {_brl(comissao_base_proj)}",
            f"   - Bônus: {_brl(bonus_proj)}",
            f"   - *Total Projetado: {_brl(comissao_proj)} (Ticket Médio: {_brl(ticket)})*",
            f"   - *GAP Financeiro: {_brl(gap)}*",
            "_Valores de comissão apenas simulados, não devem ser considerados para validação de ciclo de pagamento._",
        ]
    )
    return "\n".join(partes)


def _resolver_pesos(config, ano: int, mes: int) -> tuple[dict, dict, float, float]:
    pesos_vl = json.loads(config.pesos_diarios_vl) if config.pesos_diarios_vl else {}
    pesos_gr = json.loads(config.pesos_diarios_gross) if config.pesos_diarios_gross else {}
    du_vl = float(config.du_vl or 0)
    du_gr = float(config.du_gross or 0)
    if pesos_vl and du_vl > 0:
        return pesos_vl, pesos_gr, du_vl, du_gr
    from .calendario import pesos_do_mes

    cal = pesos_do_mes(ano, mes)
    if not cal:
        return pesos_vl, pesos_gr, du_vl, du_gr
    return (
        cal["vl"],
        cal["gross"],
        du_vl or cal["du_vl"],
        du_gr or cal["du_gross"],
    )


def calcular_osab(ano: int, mes: int) -> dict:
    hoje_ref = hoje()
    agora = timezone.now()

    vendas = list(
        VendaOSAB.objects.filter(
            data_abertura__year=ano,
            data_abertura__month=mes,
        ).exclude(pdv_nome="")
    )
    por_pdv: dict[str, list[VendaOSAB]] = {}
    for v in vendas:
        por_pdv.setdefault(v.pdv_nome, []).append(v)

    fechamentos = list(
        VendaOSAB.objects.filter(
            data_fechamento__year=ano,
            data_fechamento__month=mes,
        ).exclude(pdv_nome="")
    )
    gross_por_pdv: dict[str, list[VendaOSAB]] = {}
    for v in fechamentos:
        gross_por_pdv.setdefault(v.pdv_nome, []).append(v)

    nomes = sorted(set(por_pdv) | set(gross_por_pdv), key=lambda n: -len(por_pdv.get(n, [])))
    HistoricoOSAB.objects.filter(
        Q(descricao_pdv__in=nomes) | Q(data_processamento__date=hoje_ref)
    ).delete()
    indice = indice_parceiros()
    gerados = 0
    sem_parceiro = []

    is_mes_passado = (ano < agora.year) or (ano == agora.year and mes < agora.month)

    for pdv_nome in nomes:
        parceiro_id = resolver_parceiro_id(pdv_nome, indice)
        if not parceiro_id:
            sem_parceiro.append(pdv_nome)
            continue
        parceiro = Parceiro.objects.get(pk=parceiro_id)
        config = ConfiguracaoOSAB.objects.filter(parceiro=parceiro, ano=ano, mes=mes).first()

        vls = [
            v
            for v in por_pdv.get(pdv_nome, [])
            if v.situacao and v.situacao.strip() and v.situacao not in STATUS_IGNORADOS
        ]
        concluidos = [
            v
            for v in gross_por_pdv.get(pdv_nome, [])
            if (v.situacao or "").strip().lower() == "concluído"
            or (v.situacao or "").strip().lower() == "concluido"
        ]
        realizado_vl = len(vls)
        realizado_gross = len(concluidos)

        GrossMensal.objects.update_or_create(
            parceiro=parceiro,
            anomes=anomes(ano, mes),
            defaults={"gross": realizado_gross},
        )

        detalhes: dict = {
            "total_vl": realizado_vl,
            "total_gross": realizado_gross,
        }
        status = "Ok"
        atingimento_vl = atingimento_gross = comissao_proj = None
        capilaridade = None
        meta_cap = MetaCapilaridade.objects.filter(parceiro=parceiro, ano=ano, mes=mes).first()
        if meta_cap and meta_cap.meta_vendedores:
            linhas = linhas_capilaridade_pdv(parceiro)
            ativos = contar_ativos_pdv(parceiro, linhas)
            inativos = sum(1 for l in linhas if l["status"] == "Inativo")
            pct = (ativos / meta_cap.meta_vendedores * 100) if meta_cap.meta_vendedores else 0
            capilaridade = {
                "meta": meta_cap.meta_vendedores,
                "ativos": ativos,
                "inativos": inativos,
                "atingimento": pct,
            }
            detalhes["capilaridade"] = capilaridade

        if not config:
            status = "Sem metas"
            mensagem = (
                f"🤖 *OSAB {pdv_nome}* · {hoje_ref.strftime('%d/%m/%Y')}\n"
                f"📊 VL: {realizado_vl} | Gross: {realizado_gross}\n"
                "_Cadastre as metas OSAB deste PDV para ver atingimento e comissão._"
            )
        else:
            if is_mes_passado:
                proj_vl, proj_gross = float(realizado_vl), float(realizado_gross)
            else:
                pesos_vl, pesos_gross, du_vl, du_gross = _resolver_pesos(config, ano, mes)
                d_max = _dias_civis_fechados(hoje_ref, ano, mes)
                acc_vl = sum(float(pesos_vl.get(str(d), 0)) for d in range(1, d_max + 1))
                acc_g = sum(float(pesos_gross.get(str(d), 0)) for d in range(1, d_max + 1))
                eps = 1e-9
                rest_vl = du_vl - acc_vl
                if abs(acc_vl) > eps and rest_vl > eps:
                    proj_vl = realizado_vl + rest_vl * (realizado_vl / acc_vl)
                else:
                    proj_vl = _projecao_linear(float(realizado_vl), hoje_ref, ano, mes)
                rest_g = du_gross - acc_g
                if abs(acc_g) > eps and rest_g > eps:
                    proj_gross = realizado_gross + rest_g * (realizado_gross / acc_g)
                else:
                    proj_gross = _projecao_linear(float(realizado_gross), hoje_ref, ano, mes)

            atingimento_vl = (proj_vl / config.meta_vl * 100) if config.meta_vl > 0 else 0
            atingimento_gross = (proj_gross / config.meta_gross * 100) if config.meta_gross > 0 else 0

            politica = PoliticaComissao.vigente()
            receita = receita_mix(concluidos, politica, proj_gross)
            comissao_base = receita["comissao_realizada"]
            bonus_m10 = None
            if config.tem_bonus_m10:
                bonus_m10 = _bonus_m10(parceiro.id, ano, mes, politica.bonus_m10)
                bonus = bonus_m10["bonus_total"]
            elif config.tem_bonus:
                bonus = realizado_gross * config.comissao_bonus
            else:
                bonus = 0
            comissao_base_proj = receita["comissao_projetada"]
            if config.tem_bonus_m10 and bonus_m10:
                bonus_proj = bonus_m10["bonus_total"]
            elif config.tem_bonus:
                bonus_proj = proj_gross * config.comissao_bonus
            else:
                bonus_proj = 0
            comissao_proj = comissao_base_proj + bonus_proj
            mix = receita["mix"]
            cartao_vl = _contar_cartao(vls)
            cartao_gross = _contar_cartao(concluidos)
            detalhes.update(
                {
                    "meta_vl": config.meta_vl,
                    "meta_gross": config.meta_gross,
                    "atingimento_vl": atingimento_vl,
                    "atingimento_gross": atingimento_gross,
                    "proj_vl": proj_vl,
                    "proj_gross": proj_gross,
                    "mix_400": mix["400"],
                    "mix_500": mix["500"],
                    "mix_600": mix["600"],
                    "mix_700": mix["800"],
                    "mix_800": mix["800"],
                    "mix_1000": mix["1000"],
                    "mix_1000_mesh": mix["1000_mesh"],
                    "mix_outros": mix["outros"],
                    "mix_btu": receita["mix_btu"],
                    "cartao_vl": cartao_vl,
                    "cartao_gross": cartao_gross,
                    "comissao_basica": comissao_base,
                    "comissao_bonus": bonus,
                    "comissao_realizada": comissao_base + bonus,
                    "comissao_projetada": comissao_proj,
                }
            )
            if bonus_m10:
                detalhes["bonus_m10"] = bonus_m10
            mensagem = montar_mensagem_osab(
                pdv_nome,
                hoje_ref,
                ano,
                mes,
                realizado_vl,
                realizado_gross,
                config,
                proj_vl,
                proj_gross,
                atingimento_vl,
                atingimento_gross,
                mix,
                cartao_vl,
                cartao_gross,
                comissao_base,
                bonus,
                comissao_base_proj,
                bonus_proj,
                comissao_proj,
                capilaridade,
            )

        HistoricoOSAB.objects.create(
            parceiro=parceiro,
            descricao_pdv=pdv_nome,
            status=status,
            detalhes=detalhes,
            realizado_vl=realizado_vl,
            atingimento_vl=atingimento_vl,
            realizado_gross=realizado_gross,
            atingimento_gross=atingimento_gross,
            comissao_total_projetada=comissao_proj,
            mensagem=mensagem,
        )
        gerados += 1

    return {"pdvs": gerados, "sem_parceiro": sem_parceiro}


def processar_osab(arquivo, nome_arquivo: str, ano: int, mes: int) -> dict:
    from ..excel import ler_planilha

    df = ler_planilha(arquivo, nome_arquivo)
    for col in ("DATA_ABERTURA", "DATA_FECHAMENTO"):
        if col in df.columns:
            df[col] = converter_data_robusto(df[col])
    vendas = persistir_vendas_osab(df)
    parceiros = sincronizar_parceiros_osab()
    cap = persistir_capilaridade(ano, mes)
    osab = calcular_osab(ano, mes)
    return {"vendas": vendas, "capilaridade": cap, "osab": osab, "parceiros": parceiros}
