from __future__ import annotations

from .models import MetaCapilaridade
from .periodo import hoje, periodo_ativo
from .pipelines.osab import (
    classificar_cargo_auditoria,
    contar_ativos_pdv,
    data_ref_capilaridade,
    linhas_capilaridade_pdv,
    mapa_terceiros_por_chave,
    normalizar_cargo_ctps,
    normalizar_chave_tt,
    terceiro_ativo_para_auditoria,
    ultimas_vendas_pdv,
)
from tickets.models import Parceiro


_PARTICULAS_NOME = {"DE", "DA", "DO", "DOS", "DAS", "E", "DEL", "DI"}


def primeiro_ultimo_nome(nome: str) -> str:
    """CAUAN HENRIQUE DE OLIVEIRA DA CRUZ → CAUAN CRUZ."""
    partes = [p for p in (nome or "").split() if p]
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0]
    i = len(partes) - 1
    while i > 0 and partes[i].upper() in _PARTICULAS_NOME:
        i -= 1
    if i == 0:
        return partes[0]
    return f"{partes[0]} {partes[i]}"


def formatar_data_curta(valor) -> str:
    if valor is None:
        return "??"
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m")
    return "??"


def _linha_tt(matricula, dias, ultima, nome: str = "") -> str:
    chave = normalizar_chave_tt(matricula) or str(matricula)
    curto = primeiro_ultimo_nome(nome)
    prefixo = f"{chave} · {curto}" if curto else chave
    if dias is None:
        return f"{prefixo} · sem vendas"
    return f"{prefixo} · {int(dias)}d · {formatar_data_curta(ultima)}"


def resumir_auditoria(parceiro: Parceiro, ano: int, mes: int) -> dict:
    from django.db.models import Count
    from .models import VendaOSAB

    mapa = mapa_terceiros_por_chave()
    data_ref = data_ref_capilaridade()
    ultimas = ultimas_vendas_pdv(parceiro.nome)
    vendas = (
        VendaOSAB.objects.filter(
            pdv_nome=parceiro.nome,
            data_abertura__year=ano,
            data_abertura__month=mes,
        )
        .exclude(matricula_vendedor="")
        .values("matricula_vendedor")
        .annotate(total=Count("id"))
    )
    buckets = {
        "nao_vendedor": [],
        "operador_venda_interna": [],
        "operador_backoffice_indicador": [],
    }
    vistos: dict[str, set[str]] = {k: set() for k in buckets}
    for row in vendas:
        chave = normalizar_chave_tt(row["matricula_vendedor"])
        if not chave:
            continue
        terceiro = mapa.get(chave)
        if not terceiro_ativo_para_auditoria(terceiro):
            continue
        cargo = normalizar_cargo_ctps(terceiro.cargo_funcao if terceiro else "")
        bucket = classificar_cargo_auditoria(cargo)
        if not bucket or chave in vistos[bucket]:
            continue
        ultima = ultimas.get(chave)
        dias = None
        if ultima is not None:
            ultima_dia = ultima.date() if hasattr(ultima, "date") else ultima
            dias = (data_ref.date() - ultima_dia).days
        buckets[bucket].append({"chave": chave, "dias": dias if dias is not None else "?", "ultima": ultima})
        vistos[bucket].add(chave)
    for chave in buckets:
        buckets[chave] = sorted(buckets[chave], key=lambda x: x["chave"])
    return buckets


def montar_mascara_pdv(
    parceiro: Parceiro,
    ano: int | None = None,
    mes: int | None = None,
    filtros: dict | None = None,
) -> str:
    if ano is None or mes is None:
        ano, mes = periodo_ativo()
    meta = (
        MetaCapilaridade.objects.filter(parceiro=parceiro, ano=ano, mes=mes)
        .values_list("meta_vendedores", flat=True)
        .first()
        or 0
    )
    linhas = linhas_capilaridade_pdv(parceiro, filtros)
    ativos = contar_ativos_pdv(parceiro, linhas, filtros)
    pct = (ativos / meta * 100) if meta else 0
    partes = [
        f"*Capilaridade {parceiro.nome}* · {hoje().strftime('%d/%m')}",
        f"🎯 Meta: {meta} | 🟢 Ativos: {ativos} ({pct:.1f}%)",
    ]
    inativos, avencer, recentes = [], [], []
    for linha in linhas:
        if linha.get("sem_venda_osab"):
            inativos.append(
                _linha_tt(linha["matricula_vendedor"], None, None, linha.get("nome_vendedor") or "")
            )
            continue
        dias = int(linha["dias_sem_vender"] or 0)
        txt = _linha_tt(
            linha["matricula_vendedor"],
            dias,
            linha["ultima_venda"],
            linha.get("nome_vendedor") or "",
        )
        if dias >= 7:
            inativos.append(txt)
        elif dias >= 5:
            avencer.append(txt)
        else:
            recentes.append(txt)
    if inativos:
        partes.append(f"🆘 *Inativos a recuperar: {len(inativos)}*\n" + "\n".join(inativos))
    if avencer:
        partes.append(f"⚠️ *A vencer: {len(avencer)}*\n" + "\n".join(avencer))
    if recentes:
        partes.append(
            f"🎉 *Capilaridade com vendas - Recentes: {len(recentes)}*\n" + "\n".join(recentes)
        )

    auditoria = resumir_auditoria(parceiro, ano, mes)
    titulos = (
        ("🏢", "Vendas Operador Back-office indicador", auditoria["operador_backoffice_indicador"]),
        ("📞", "Vendas Operador de Vendas interna", auditoria["operador_venda_interna"]),
        ("⛔", "TTs que não podem ter vendas, e teve input incorreto", auditoria["nao_vendedor"]),
    )
    for icone, titulo, itens in titulos:
        if not itens:
            continue
        linhas_txt = [f"{icone} *{titulo}: {len(itens)}*"]
        for item in itens:
            dias = item["dias"]
            dias_n = dias if isinstance(dias, int) else None
            linhas_txt.append(_linha_tt(item["chave"], dias_n, item["ultima"]))
        partes.append("\n".join(linhas_txt))
    return "\n\n".join(partes)


def resumo_geral(
    parceiros: list[Parceiro],
    ano: int,
    mes: int,
    filtros: dict | None = None,
) -> str:
    meta_total = 0
    ativos = 0
    inativos = 0
    for p in parceiros:
        meta = (
            MetaCapilaridade.objects.filter(parceiro=p, ano=ano, mes=mes)
            .values_list("meta_vendedores", flat=True)
            .first()
            or 0
        )
        meta_total += meta
        linhas = linhas_capilaridade_pdv(p, filtros)
        ativos += contar_ativos_pdv(p, linhas, filtros)
        inativos += sum(1 for l in linhas if l["status"] == "Inativo")
    pct = (ativos / meta_total * 100) if meta_total else 0
    return (
        f"📊 *Resumo Capilaridade* · {hoje().strftime('%d/%m')}\n\n"
        f"🎯 *Meta de vendedores ativos:* {meta_total}\n"
        f"🟢 *Ativos (≤ 7 dias):* {ativos}\n"
        f"🔴 *Inativos:* {inativos}\n"
        f"📈 *Atingimento:* {pct:.1f}%"
    )
