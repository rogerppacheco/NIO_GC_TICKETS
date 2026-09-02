from __future__ import annotations

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

ALIASES_PARCIAL = {
    "pdv": ["PDV", "NM_PARCEIRO", "NM_PARCEIRO_2", "PARCEIRO", "NOME", "LOJA"],
    "vendas": [
        "VENDAS",
        "TOTAL",
        "REALIZADO",
        "VB",
        "VENDAS_TOTAL",
        "TOTAL_VENDAS",
        "QTD_VENDAS",
    ],
    "d7": [
        "D7",
        "D-7",
        "VENDAS_D7",
        "TOTAL_D7",
        "REALIZADO_D7",
        "VB_D7",
        "D_7",
    ],
}


def turno_parcial(hora: int | None = None) -> tuple[int, str]:
    """Próximo turno do dia: 12h, 15h ou 18h."""
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


def _linha_parceiro(parceiro: Parceiro, *, vendas: int = 0, d7: int = 0) -> dict:
    esp_nome = "—"
    esp_id = None
    if parceiro.especialista_id:
        esp_id = parceiro.especialista_id
        user = parceiro.especialista
        esp_nome = (user.get_full_name() or user.username or "—").strip()
    return {
        "parceiro_id": parceiro.pk,
        "pdv": (parceiro.nome or "").strip(),
        "vendas": vendas,
        "d7": d7,
        "delta": vendas - d7,
        "especialista_id": esp_id,
        "especialista": esp_nome,
    }


def _completar_parceiros_escopo(
    linhas: list[dict],
    mapa_parceiros: dict[int, Parceiro],
) -> list[dict]:
    """PDVs do escopo ausentes na planilha entram com zero."""
    vistos = {l["parceiro_id"] for l in linhas}
    out = list(linhas)
    for pid, parceiro in sorted(mapa_parceiros.items(), key=lambda x: (x[1].nome or "").upper()):
        if pid not in vistos:
            out.append(_linha_parceiro(parceiro))
    return out


def processar_parcial_excel(
    arquivo,
    nome_arquivo: str,
    parceiros: Iterable[Parceiro] | None = None,
    *,
    turno: int | None = None,
    ano: int | None = None,
    mes: int | None = None,
) -> dict:
    """Importa base Excel da dashboard: PDV, vendas acumuladas e referência D-7."""
    df = ler_planilha(arquivo, nome_arquivo)
    df = aplicar_aliases(df, ALIASES_PARCIAL)
    if "pdv" not in df.columns:
        raise ValueError(
            "Coluna PDV não encontrada. Use PDV, NM_PARCEIRO ou PARCEIRO."
        )
    col_vendas = resolver_coluna(df, ALIASES_PARCIAL["vendas"])
    col_d7 = resolver_coluna(df, ALIASES_PARCIAL["d7"])
    if not col_vendas or not col_d7:
        raise ValueError(
            "Informe colunas de vendas totais e D-7 "
            f"(ex.: TOTAL e D-7). Colunas: {list(df.columns)}"
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

    indice = indice_parceiros()
    por_id: dict[int, dict] = {}
    sem_cadastro: list[str] = []
    for _, row in df.iterrows():
        nome_pdv = texto(row.get("pdv"))
        if not nome_pdv:
            continue
        vendas = _int_valor(row.get(col_vendas))
        d7 = _int_valor(row.get(col_d7))
        pid = resolver_parceiro_id(nome_pdv, indice)
        if pid is None:
            sem_cadastro.append(nome_pdv)
            continue
        if escopo_ids is not None and pid not in escopo_ids:
            continue
        parceiro = mapa_parceiros.get(pid)
        if parceiro is None and escopo_ids is not None:
            parceiro = Parceiro.objects.filter(pk=pid).select_related("especialista").first()
        if parceiro:
            por_id[pid] = _linha_parceiro(parceiro, vendas=vendas, d7=d7)
        else:
            por_id[pid] = {
                "parceiro_id": pid,
                "pdv": nome_pdv.strip(),
                "vendas": vendas,
                "d7": d7,
                "delta": vendas - d7,
                "especialista_id": None,
                "especialista": "—",
            }

    linhas = list(por_id.values())
    if mapa_parceiros:
        linhas = _completar_parceiros_escopo(linhas, mapa_parceiros)

    if not linhas:
        raise ValueError(
            "Nenhum PDV no escopo. "
            f"{len(sem_cadastro)} linha(s) da planilha sem cadastro."
        )

    return montar_parcial(
        linhas,
        ano=ano,
        mes=mes,
        turno=hora_turno,
        rotulo_turno=rotulo_turno,
        sem_cadastro=sem_cadastro,
        arquivo=nome_arquivo,
    )


def _top_e_piores(linhas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Top 5 e piores 5 sem repetir PDV (piores vêm do restante após o top)."""
    ordenado = sorted(linhas, key=lambda l: (-l["delta"], l["pdv"].upper()))
    top5 = ordenado[:5]
    ids_top = {l["parceiro_id"] for l in top5}
    restantes = [l for l in linhas if l.get("parceiro_id") not in ids_top]
    pior5 = sorted(restantes, key=lambda l: (l["delta"], l["pdv"].upper()))[:5]
    return top5, pior5


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
    top5, pior5 = _top_e_piores(linhas)
    total_pp = sum(l["vendas"] for l in linhas)
    total_d7 = sum(l["d7"] for l in linhas)
    return {
        "ano": ano,
        "mes": mes,
        "turno": turno,
        "rotulo_turno": rotulo_turno,
        "data_ref": data_ref.isoformat(),
        "arquivo": arquivo,
        "linhas": linhas,
        "total_pp": total_pp,
        "total_d7": total_d7,
        "delta_pp": total_pp - total_d7,
        "top5": top5,
        "pior5": pior5,
        "sem_cadastro": sem_cadastro or [],
        "qtd_pdvs": len(linhas),
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
    total = sum(l["vendas"] for l in linhas)
    total_d7 = sum(l["d7"] for l in linhas)
    top5, pior5 = _top_e_piores(linhas)
    return {
        **{k: base[k] for k in ("ano", "mes", "turno", "rotulo_turno", "data_ref", "arquivo")},
        "titulo": titulo,
        "linhas": linhas,
        "total_pp": total,
        "total_d7": total_d7,
        "delta_pp": total - total_d7,
        "top5": top5,
        "pior5": pior5,
        "qtd_pdvs": len(linhas),
        "sem_cadastro": [],
    }


def agrupar_por_especialista(linhas: list[dict]) -> list[dict]:
    """Agrupa PDVs por especialista (ordem alfabética do nome)."""
    buckets: dict[str, list[dict]] = {}
    rotulos: dict[str, str] = {}
    for linha in linhas:
        chave = str(linha.get("especialista_id") or "sem")
        rotulos[chave] = (linha.get("especialista") or "Sem especialista").strip() or "Sem especialista"
        buckets.setdefault(chave, []).append(linha)
    grupos = []
    for chave in sorted(rotulos, key=lambda k: rotulos[k].upper()):
        items = sorted(buckets[chave], key=lambda l: (-l.get("vendas", 0), l.get("pdv", "").upper()))
        grupos.append(
            {
                "especialista_id": None if chave == "sem" else int(chave),
                "especialista": rotulos[chave],
                "linhas": items,
                "total_vendas": sum(l["vendas"] for l in items),
                "total_d7": sum(l["d7"] for l in items),
                "delta": sum(l["delta"] for l in items),
                "qtd_pdvs": len(items),
            }
        )
    return grupos


def caption_imagem_parcial(dados: dict, *, sufixo: str = "") -> str:
    mes, ano = dados.get("mes"), dados.get("ano")
    rotulo = dados.get("rotulo_turno") or "—"
    base = f"📊 Parcial · {mes:02d}/{ano} · {rotulo}" if mes and ano else f"📊 Parcial · {rotulo}"
    return f"{base} · {sufixo}" if sufixo else base


def linha_pdv(dados: dict, parceiro_id: int) -> dict | None:
    for linha in dados.get("linhas") or []:
        if linha.get("parceiro_id") == parceiro_id:
            return linha
    return None


def _fmt_delta(valor: int) -> str:
    if valor > 0:
        return f"+{valor}"
    return str(valor)


def mensagem_parcial_gerencia(dados: dict) -> str:
    ano, mes = dados["ano"], dados["mes"]
    rotulo = dados.get("rotulo_turno") or "—"
    partes = [
        f"📊 *Parcial PP · {mes:02d}/{ano} · {rotulo}*",
        f"Total: *{dados['total_pp']}* VB · D-7: {dados['total_d7']} · ∆ {_fmt_delta(dados['delta_pp'])}",
        "",
        "*Top 5 (∆ absoluto D-7)*",
    ]
    for i, item in enumerate(dados.get("top5") or [], start=1):
        partes.append(
            f"{i}. {item['pdv']} — {item['vendas']} ({_fmt_delta(item['delta'])} vs D-7)"
        )
    partes.append("")
    partes.append("*Piores 5 (∆ absoluto D-7)*")
    for i, item in enumerate(dados.get("pior5") or [], start=1):
        partes.append(
            f"{i}. {item['pdv']} — {item['vendas']} ({_fmt_delta(item['delta'])} vs D-7)"
        )
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
        f"Total carteira: *{dados['total_pp']}* VB · ∆ D-7: {_fmt_delta(dados['delta_pp'])}",
    ]
    for item in dados.get("linhas") or []:
        extra.append(
            f"• {item['pdv']}: {item['vendas']} ({_fmt_delta(item['delta'])} vs D-7)"
        )
    return base + "\n".join(extra)


def mensagem_parcial_pdv(linha: dict, dados: dict) -> str:
    return mensagem_parcial(
        pdv=linha["pdv"],
        ano=dados.get("ano"),
        mes=dados.get("mes"),
    ) + (
        f"\n\n📈 *Parcial · {dados.get('rotulo_turno', '—')}*\n"
        f"Total: *{linha['vendas']}* VB · D-7: {linha['d7']} · "
        f"∆ {_fmt_delta(linha['delta'])}"
    )
