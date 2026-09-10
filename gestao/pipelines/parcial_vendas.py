from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

import pandas as pd
from django.utils import timezone

from tickets.models import Parceiro

from ..excel import aplicar_aliases, ler_planilha, resolver_coluna, texto
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje, periodo_ativo
from .resultados import mensagem_parcial

HORARIOS_PARCIAL = (12, 15, 18)
ROTULOS_TURNO = {12: "12h", 15: "15h", 18: "18h"}
# Só entra no Top/Bottom quem tem plano preenchido e ≥ este piso.
MIN_PLANO = 2.0

ALIASES_PARCIAL = {
    "pdv": ["PDV", "NM_PARCEIRO", "NM_PARCEIRO_2", "PARCEIRO", "NOME", "LOJA"],
    "vendas": [
        "VENDAS_TOTAL",
        "VENDAS TOTAL",
        "VENDAS TOTAL",
        "TOTAL_VENDAS",
        "QTD_VENDAS",
        "VENDAS",
        "REALIZADO",
        "VB",
        "TOTAL",
    ],
    # Nunca usar "PLANO" solto: colide com "% Plano" na chave normalizada.
    "plano_dia": [
        "PLANO_DIA",
        "PLANO DIA",
        "META_DIA",
        "META DIA",
        "ORCADO_DIA",
        "ORÇADO DIA",
    ],
}


def turno_parcial(hora: int | None = None) -> tuple[int, str]:
    """Próximo turno do dia: 12h, 15h ou 18h (só rótulo de corte; não altera a métrica)."""
    hora = hora if hora is not None else timezone.localtime().hour
    if hora < 12:
        escolhido = 12
    elif hora < 15:
        escolhido = 15
    elif hora < 18:
        escolhido = 18
    else:
        escolhido = 18
    return escolhido, ROTULOS_TURNO[escolhido]


def _int_valor(valor) -> int:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


def _float_valor(valor) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, str) and not str(valor).strip():
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def plano_lido(valor) -> float | None:
    """Plano do dia da planilha; ausente/vazio/≤0 → None (fora do ranking)."""
    bruto = _float_valor(valor)
    if bruto is None or bruto <= 0:
        return None
    return bruto


def planos_cadastrados(
    ano: int,
    mes: int,
    parceiro_ids: Iterable[int] | None = None,
) -> dict[int, float]:
    """Plano dia cadastrado em Metas (ConfiguracaoOSAB) para o período."""
    from ..models import ConfiguracaoOSAB

    qs = ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes, plano_dia__gt=0)
    if parceiro_ids is not None:
        qs = qs.filter(parceiro_id__in=list(parceiro_ids))
    return {int(c.parceiro_id): float(c.plano_dia) for c in qs.only("parceiro_id", "plano_dia")}


def planos_dia_fixos(
    ano: int,
    mes: int,
    parceiro_ids: Iterable[int] | None = None,
) -> set[int]:
    """PDVs cujo Plano dia não deve ser sobrescrito pelo Excel do parcial."""
    from ..models import ConfiguracaoOSAB

    qs = ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes, plano_dia_fixo=True)
    if parceiro_ids is not None:
        qs = qs.filter(parceiro_id__in=list(parceiro_ids))
    return {int(pid) for pid in qs.values_list("parceiro_id", flat=True)}


def sincronizar_planos_dia_metas(dados: dict) -> int:
    """Grava em Metas o Plano Dia vindo do Excel (só PDVs presentes na planilha).

    PDVs com plano_dia_fixo=True são ignorados (plano definido pelo especialista).
    """
    from ..models import ConfiguracaoOSAB

    ano = dados.get("ano")
    mes = dados.get("mes")
    if not ano or not mes:
        return 0
    bruto = dados.get("vendas_por_id") or {}
    fixos = planos_dia_fixos(int(ano), int(mes))
    atualizados = 0
    for chave, linha in bruto.items():
        try:
            pid = int(chave) if not isinstance(chave, int) else chave
        except (TypeError, ValueError):
            continue
        if pid in fixos:
            continue
        plano = plano_lido((linha or {}).get("plano"))
        if plano is None:
            continue
        obj, criado = ConfiguracaoOSAB.objects.get_or_create(
            parceiro_id=pid,
            ano=int(ano),
            mes=int(mes),
            defaults={"plano_dia": plano},
        )
        if criado:
            atualizados += 1
            continue
        if float(obj.plano_dia or 0) != float(plano):
            obj.plano_dia = plano
            obj.save(update_fields=["plano_dia"])
            atualizados += 1
    return atualizados


def plano_com_fallback(
    plano_excel: float | None,
    parceiro_id: int | None,
    planos_meta: dict[int, float],
    planos_fixos: set[int] | None = None,
) -> float | None:
    """Excel prevalece; se vazio, usa Metas. Com plano fixo, Metas prevalece."""
    fixos = planos_fixos or set()
    if parceiro_id is not None and int(parceiro_id) in fixos:
        meta = planos_meta.get(int(parceiro_id))
        if meta is not None:
            return meta
    if plano_excel is not None:
        return plano_excel
    if parceiro_id is None:
        return None
    return planos_meta.get(int(parceiro_id))


def plano_arredondado(plano: float | None) -> float | None:
    """No parcial o plano é exibido/usado arredondado para cima (inteiro)."""
    if plano is None:
        return None
    return float(math.ceil(float(plano)))


def elegivel_ranking(plano: float | None, *, min_plano: float = MIN_PLANO) -> bool:
    return plano is not None and plano >= min_plano


def _metricas(vendas: int, plano: float | None) -> dict:
    plano = plano_arredondado(plano)
    pct = (vendas / plano) if plano and plano > 0 else None
    gap = int(round(vendas - plano)) if plano is not None else None
    return {
        "plano": plano,
        "pct_plano": pct,
        "pct_pct": int(round(pct * 100)) if pct is not None else None,
        "delta": gap if gap is not None else 0,
        "elegivel": elegivel_ranking(plano),
    }


def _linha_parceiro(
    parceiro: Parceiro,
    *,
    vendas: int = 0,
    plano: float | None = None,
) -> dict:
    esp_nome = "—"
    esp_id = None
    if parceiro.especialista_id:
        esp_id = parceiro.especialista_id
        user = parceiro.especialista
        esp_nome = (user.get_full_name() or user.username or "—").strip()
    met = _metricas(vendas, plano)
    return {
        "parceiro_id": parceiro.pk,
        "pdv": (parceiro.nome or "").strip(),
        "vendas": vendas,
        "especialista_id": esp_id,
        "especialista": esp_nome,
        **met,
    }


def _linha_manual(
    *,
    parceiro_id: int,
    pdv: str,
    vendas: int,
    plano: float | None,
    especialista_id=None,
    especialista: str = "—",
) -> dict:
    met = _metricas(vendas, plano)
    return {
        "parceiro_id": parceiro_id,
        "pdv": (pdv or "").strip(),
        "vendas": vendas,
        "especialista_id": especialista_id,
        "especialista": especialista,
        **met,
    }


def _eh_total_planilha(nome: str) -> bool:
    return (nome or "").strip().casefold() in {"total", "totais", "geral"}


def _completar_parceiros_escopo(
    linhas: list[dict],
    mapa_parceiros: dict[int, Parceiro],
    *,
    planos_meta: dict[int, float] | None = None,
) -> list[dict]:
    """PDVs do escopo ausentes na planilha entram com zero e plano de Metas, se houver."""
    planos_meta = planos_meta or {}
    vistos = {l["parceiro_id"] for l in linhas}
    out = list(linhas)
    for pid, parceiro in sorted(mapa_parceiros.items(), key=lambda x: (x[1].nome or "").upper()):
        if pid not in vistos:
            out.append(_linha_parceiro(parceiro, plano=planos_meta.get(pid)))
    return out


def processar_parcial_excel(
    arquivo,
    nome_arquivo: str,
    parceiros: Iterable[Parceiro] | None = None,
    *,
    turno: int | None = None,
    ano: int | None = None,
    mes: int | None = None,
    ids_gerencia: set[int] | None = None,
) -> dict:
    """Importa base Excel: PDV, vendas do dia e Plano Dia (% do plano)."""
    df = ler_planilha(arquivo, nome_arquivo)
    df = aplicar_aliases(df, ALIASES_PARCIAL)
    if "pdv" not in df.columns:
        raise ValueError(
            "Coluna PDV não encontrada. Use PDV, NM_PARCEIRO ou PARCEIRO."
        )
    col_vendas = resolver_coluna(df, ALIASES_PARCIAL["vendas"])
    col_plano = resolver_coluna(df, ALIASES_PARCIAL["plano_dia"])
    if not col_vendas or not col_plano:
        raise ValueError(
            "Informe colunas de vendas totais e Plano Dia "
            f"(ex.: Vendas Total e Plano Dia). Colunas: {list(df.columns)}"
        )

    if ano is None or mes is None:
        ano, mes = periodo_ativo()
    hora_turno, rotulo_turno = turno_parcial()
    if turno in HORARIOS_PARCIAL:
        hora_turno, rotulo_turno = turno, ROTULOS_TURNO[turno]

    escopo_ids: set[int] | None = None
    mapa_parceiros: dict[int, Parceiro] = {}
    if parceiros is not None:
        lista = list(parceiros)
        escopo_ids = {p.pk for p in lista}
        mapa_parceiros = {p.pk: p for p in lista}
    ids_gerencia = ids_gerencia or set()

    indice = indice_parceiros()
    por_id: dict[int, dict] = {}
    sem_cadastro: list[str] = []
    ids_para_meta = set(escopo_ids or ()) | set(ids_gerencia)
    planos_meta = planos_cadastrados(ano, mes, ids_para_meta or None)
    planos_fixos = planos_dia_fixos(ano, mes, ids_para_meta or None)
    for _, row in df.iterrows():
        nome_pdv = texto(row.get("pdv"))
        if not nome_pdv or _eh_total_planilha(nome_pdv):
            continue
        vendas = _int_valor(row.get(col_vendas))
        pid = resolver_parceiro_id(nome_pdv, indice)
        if pid is None:
            sem_cadastro.append(nome_pdv)
            continue
        if escopo_ids is not None and pid not in escopo_ids:
            if pid not in ids_gerencia:
                continue
        plano = plano_com_fallback(
            plano_lido(row.get(col_plano)), pid, planos_meta, planos_fixos
        )
        parceiro = mapa_parceiros.get(pid)
        if parceiro is None and (escopo_ids is not None or pid in ids_gerencia):
            parceiro = Parceiro.objects.filter(pk=pid).select_related("especialista").first()
        if parceiro:
            por_id[pid] = _linha_parceiro(parceiro, vendas=vendas, plano=plano)
        else:
            por_id[pid] = _linha_manual(
                parceiro_id=pid,
                pdv=nome_pdv,
                vendas=vendas,
                plano=plano,
            )

    vendas_por_id = dict(por_id)
    linhas = list(por_id.values())
    if mapa_parceiros:
        linhas = _completar_parceiros_escopo(linhas, mapa_parceiros, planos_meta=planos_meta)

    if not linhas:
        raise ValueError(
            "Nenhum PDV no escopo. "
            f"{len(sem_cadastro)} linha(s) da planilha sem cadastro."
        )

    out = montar_parcial(
        linhas,
        ano=ano,
        mes=mes,
        turno=hora_turno,
        rotulo_turno=rotulo_turno,
        sem_cadastro=sem_cadastro,
        arquivo=nome_arquivo,
    )
    out["vendas_por_id"] = {str(k): v for k, v in vendas_por_id.items()}
    return out


def _mapa_vendas_parcial(dados: dict) -> dict[int, dict]:
    bruto = dados.get("vendas_por_id")
    if bruto:
        out: dict[int, dict] = {}
        for k, v in bruto.items():
            pid = int(k) if not isinstance(k, int) else k
            out[pid] = v
        return out
    return {l["parceiro_id"]: l for l in dados.get("linhas") or []}


def _recalcular_linha(
    linha: dict,
    planos_meta: dict[int, float] | None = None,
    planos_fixos: set[int] | None = None,
) -> dict:
    """Garante métricas de % do plano; usa Metas se plano do Excel estiver vazio."""
    vendas = int(linha.get("vendas") or 0)
    pid = linha.get("parceiro_id")
    if "plano" in linha:
        plano_excel = plano_lido(linha.get("plano"))
    else:
        # Bases antigas (D-7): tenta só o cadastro em Metas.
        plano_excel = None
    plano = plano_com_fallback(
        plano_excel, pid, planos_meta or {}, planos_fixos
    )
    met = _metricas(vendas, plano)
    out = dict(linha)
    out.update(met)
    out.pop("d7", None)
    return out


def aplicar_escopo_parcial(dados: dict, parceiros: list) -> dict:
    """Recalcula totais/top/bottom para o escopo atual (ausentes entram com zero)."""
    mapa = {p.pk: p for p in parceiros}
    por_id = _mapa_vendas_parcial(dados)
    ano = int(dados.get("ano") or periodo_ativo()[0])
    mes = int(dados.get("mes") or periodo_ativo()[1])
    planos_meta = planos_cadastrados(ano, mes, mapa.keys())
    planos_fixos = planos_dia_fixos(ano, mes, mapa.keys())
    linhas: list[dict] = []
    for pid in sorted(mapa.keys(), key=lambda x: (mapa[x].nome or "").upper()):
        if pid in por_id:
            linha = _recalcular_linha(por_id[pid], planos_meta, planos_fixos)
            if not linha.get("especialista_id") and mapa[pid].especialista_id:
                linha = _linha_parceiro(
                    mapa[pid],
                    vendas=linha.get("vendas", 0),
                    plano=linha.get("plano"),
                )
            linhas.append(linha)
        else:
            linhas.append(_linha_parceiro(mapa[pid], plano=planos_meta.get(pid)))
    return {**dados, **_totais_parcial(linhas), "linhas": linhas}


def _chave_pct(linha: dict) -> float:
    pct = linha.get("pct_plano")
    return float(pct) if pct is not None else float("-inf")


def _chave_vendas(linha: dict) -> int:
    return int(linha.get("vendas") or 0)


def _top_e_piores(linhas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Top 5 / Bottom 5 por total absoluto; empate → % do plano."""
    elegiveis = [l for l in linhas if l.get("elegivel")]
    ordenado = sorted(
        elegiveis,
        key=lambda l: (-_chave_vendas(l), -_chave_pct(l), l["pdv"].upper()),
    )
    top5 = ordenado[:5]
    ids_top = {l["parceiro_id"] for l in top5}
    restantes = [l for l in elegiveis if l.get("parceiro_id") not in ids_top]
    # Piores: menor total; no empate, menor % do plano
    pior5 = sorted(
        restantes,
        key=lambda l: (_chave_vendas(l), _chave_pct(l), l["pdv"].upper()),
    )[:5]
    return top5, pior5


def _totais_parcial(linhas: list[dict]) -> dict:
    top5, pior5 = _top_e_piores(linhas)
    sem_plano = [l for l in linhas if not l.get("elegivel")]
    total_pp = sum(int(l.get("vendas") or 0) for l in linhas)
    planos = [float(l["plano"]) for l in linhas if l.get("plano") is not None]
    total_plano = round(sum(planos), 2) if planos else 0.0
    pct_pp = (total_pp / total_plano) if total_plano > 0 else None
    return {
        "top5": top5,
        "pior5": pior5,
        "sem_plano": sem_plano,
        "total_pp": total_pp,
        "total_plano": total_plano,
        "pct_pp": pct_pp,
        "pct_pct": int(round(pct_pp * 100)) if pct_pp is not None else None,
        "delta_pp": int(round(total_pp - total_plano)) if planos else 0,
        "qtd_pdvs": len(linhas),
        "qtd_elegiveis": len(linhas) - len(sem_plano),
        "qtd_sem_plano": len(sem_plano),
    }


def montar_parcial(
    linhas: list[dict],
    *,
    ano: int,
    mes: int,
    turno: int,
    rotulo_turno: str,
    sem_cadastro: list[str] | None = None,
    arquivo: str = "",
    agora: datetime | None = None,
) -> dict:
    agora = agora or timezone.localtime()
    data_ref = agora.date() if isinstance(agora, datetime) else hoje()
    return {
        "ano": ano,
        "mes": mes,
        "turno": turno,
        "rotulo_turno": rotulo_turno,
        "data_ref": data_ref.isoformat(),
        "arquivo": arquivo,
        "linhas": linhas,
        "sem_cadastro": sem_cadastro or [],
        **_totais_parcial(linhas),
    }


def linhas_carteira(dados: dict, parceiro_ids: Iterable[int]) -> list[dict]:
    ids = set(parceiro_ids)
    return [l for l in dados.get("linhas") or [] if l.get("parceiro_id") in ids]


def linhas_especialista(dados: dict, user_id: int | None) -> list[dict]:
    if user_id is None:
        return list(dados.get("linhas") or [])
    return [
        l
        for l in dados.get("linhas") or []
        if l.get("especialista_id") == user_id
    ]


def sub_parcial(
    linhas: list[dict],
    base: dict,
    *,
    titulo: str = "",
) -> dict:
    return {
        **{k: base[k] for k in ("ano", "mes", "turno", "rotulo_turno", "data_ref", "arquivo")},
        "titulo": titulo,
        "linhas": linhas,
        "sem_cadastro": [],
        **_totais_parcial(linhas),
    }


def nome_especialista_curto(nome: str) -> str:
    partes = (nome or "").strip().split()
    if not partes:
        return "Sem especialista"
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]} {partes[-1]}"


def ordenar_linhas_parcial(linhas: list[dict]) -> list[dict]:
    """Com vendas: total ↓ (empate % ↓); zerados ao final em ordem alfabética do parceiro."""
    com_venda: list[dict] = []
    zerados: list[dict] = []
    for linha in linhas:
        if int(linha.get("vendas") or 0) > 0:
            com_venda.append(linha)
        else:
            zerados.append(linha)

    def _pct(l: dict) -> float:
        pct = l.get("pct_plano")
        return float(pct) if pct is not None else float("-inf")

    com_venda.sort(
        key=lambda l: (-int(l.get("vendas") or 0), -_pct(l), (l.get("pdv") or "").upper())
    )
    zerados.sort(key=lambda l: (l.get("pdv") or "").upper())
    return com_venda + zerados


def agrupar_por_especialista(linhas: list[dict]) -> list[dict]:
    """Agrupa PDVs por especialista (ordenado por volume total da carteira)."""
    buckets: dict[str, list[dict]] = {}
    rotulos: dict[str, str] = {}
    for linha in linhas:
        chave = str(linha.get("especialista_id") or "sem")
        rotulos[chave] = (linha.get("especialista") or "Sem especialista").strip() or "Sem especialista"
        buckets.setdefault(chave, []).append(linha)
    grupos = []
    for chave, items in buckets.items():
        nome_completo = rotulos[chave]
        ordenado = ordenar_linhas_parcial(items)
        total_vendas = sum(int(l.get("vendas") or 0) for l in ordenado)
        planos = [float(l["plano"]) for l in ordenado if l.get("plano") is not None]
        total_plano = round(sum(planos), 2) if planos else 0.0
        pct = (total_vendas / total_plano) if total_plano > 0 else None
        grupos.append(
            {
                "especialista_id": None if chave == "sem" else int(chave),
                "especialista": nome_especialista_curto(nome_completo),
                "especialista_completo": nome_completo,
                "linhas": ordenado,
                "total_vendas": total_vendas,
                "total_plano": total_plano,
                "pct_plano": pct,
                "pct_pct": int(round(pct * 100)) if pct is not None else None,
                "delta": int(round(total_vendas - total_plano)) if planos else 0,
                "qtd_pdvs": len(ordenado),
            }
        )
    grupos.sort(key=lambda g: (-g["total_vendas"], g["especialista"].upper()))
    return grupos


def caption_imagem_parcial(
    dados: dict,
    *,
    sufixo: str = "",
    nota: str = "",
) -> str:
    mes, ano = dados.get("mes"), dados.get("ano")
    rotulo = dados.get("rotulo_turno") or "—"
    base = f"📊 Parcial · {mes:02d}/{ano} · {rotulo}" if mes and ano else f"📊 Parcial · {rotulo}"
    linha = f"{base} · {sufixo}" if sufixo else base
    extra = (nota or "").strip()
    if extra:
        return f"{linha}\n\n{extra}"
    return linha


def linha_pdv(dados: dict, parceiro_id: int) -> dict | None:
    for linha in dados.get("linhas") or []:
        if linha.get("parceiro_id") == parceiro_id:
            return linha
    return None


def _fmt_delta(valor: int) -> str:
    if valor > 0:
        return f"+{valor}"
    return str(valor)


def fmt_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{int(round(float(pct) * 100))}%"


def fmt_plano(valor: float | None) -> str:
    if valor is None:
        return "—"
    return str(int(math.ceil(float(valor))))


def _fmt_linha_pct(item: dict) -> str:
    return (
        f"{item['pdv']} — {item['vendas']}/{fmt_plano(item.get('plano'))} "
        f"({fmt_pct(item.get('pct_plano'))} do plano)"
    )


def mensagem_parcial_gerencia(dados: dict) -> str:
    ano, mes = dados["ano"], dados["mes"]
    rotulo = dados.get("rotulo_turno") or "—"
    partes = [
        f"📊 *Parcial PP · {mes:02d}/{ano} · {rotulo}*",
        (
            f"Total: *{dados['total_pp']}* VB · plano {fmt_plano(dados.get('total_plano'))} · "
            f"{fmt_pct(dados.get('pct_pp'))} do plano"
        ),
        "",
        "*Top 5 (total)*",
    ]
    for i, item in enumerate(dados.get("top5") or [], start=1):
        partes.append(f"{i}. {_fmt_linha_pct(item)}")
    partes.append("")
    partes.append("*Bottom 5 (total)*")
    for i, item in enumerate(dados.get("pior5") or [], start=1):
        partes.append(f"{i}. {_fmt_linha_pct(item)}")
    qtd_fora = int(dados.get("qtd_sem_plano") or 0)
    if qtd_fora:
        partes.append("")
        partes.append(f"_Fora do ranking (sem plano ou plano < {int(MIN_PLANO)}): {qtd_fora}_")
    return "\n".join(partes)


def mensagem_parcial_especialista(dados: dict, *, pdv: str = "time") -> str:
    """Legenda para visão de carteira ou PDV único."""
    base = mensagem_parcial(
        pdv=pdv,
        ano=dados.get("ano"),
        mes=dados.get("mes"),
    )
    rotulo = dados.get("rotulo_turno") or "—"
    extra = [
        "",
        f"📈 *Parcial · {rotulo}*",
        (
            f"Total carteira: *{dados['total_pp']}* VB · plano {fmt_plano(dados.get('total_plano'))} · "
            f"{fmt_pct(dados.get('pct_pp'))} do plano"
        ),
    ]
    for item in dados.get("linhas") or []:
        extra.append(f"• {_fmt_linha_pct(item)}")
    return base + "\n".join(extra)


def mensagem_parcial_pdv(linha: dict, dados: dict) -> str:
    return mensagem_parcial(
        pdv=linha["pdv"],
        ano=dados.get("ano"),
        mes=dados.get("mes"),
    ) + (
        f"\n\n📈 *Parcial · {dados.get('rotulo_turno', '—')}*\n"
        f"Total: *{linha['vendas']}* VB · plano {fmt_plano(linha.get('plano'))} · "
        f"{fmt_pct(linha.get('pct_plano'))} do plano"
    )
