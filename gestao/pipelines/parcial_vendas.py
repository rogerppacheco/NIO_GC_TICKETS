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
PLANO_DEFAULT = 2.0

ALIASES_PARCIAL = {
    "pdv": ["PDV", "NM_PARCEIRO", "NM_PARCEIRO_2", "PARCEIRO", "NOME", "LOJA"],
    "vendas": [
        "VENDAS",
        "VENDAS_TOTAL",
        "VENDAS TOTAL",
        "TOTAL_VENDAS",
        "QTD_VENDAS",
        "REALIZADO",
        "VB",
        "TOTAL",
    ],
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


def fracao_turno(turno: int) -> float:
    """Fração linear do dia calendário esperada até o turno (12/24, 15/24, 18/24)."""
    hora = turno if turno in HORARIOS_PARCIAL else turno_parcial()[0]
    return hora / 24.0


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
    if isinstance(valor, str) and not valor.strip():
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def plano_efetivo(valor) -> float:
    """Plano do dia; ausente ou zerado vira PLANO_DEFAULT (2)."""
    bruto = _float_valor(valor)
    if bruto is None or bruto <= 0:
        return PLANO_DEFAULT
    return bruto


def _metricas(vendas: int, plano: float, turno: int) -> dict:
    esperado = plano * fracao_turno(turno)
    ritmo = (vendas / esperado) if esperado > 0 else 0.0
    pct_plano = (vendas / plano) if plano > 0 else 0.0
    return {
        "plano": plano,
        "esperado": round(esperado, 2),
        "ritmo": ritmo,
        "ritmo_pct": int(round(ritmo * 100)),
        "pct_plano": pct_plano,
        "delta": int(round(vendas - esperado)),
    }


def _linha_parceiro(
    parceiro: Parceiro,
    *,
    vendas: int = 0,
    plano: float | None = None,
    turno: int = 12,
) -> dict:
    esp_nome = "—"
    esp_id = None
    if parceiro.especialista_id:
        esp_id = parceiro.especialista_id
        user = parceiro.especialista
        esp_nome = (user.get_full_name() or user.username or "—").strip()
    plano_ok = plano_efetivo(plano)
    met = _metricas(vendas, plano_ok, turno)
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
    plano: float,
    turno: int,
    especialista_id=None,
    especialista: str = "—",
) -> dict:
    met = _metricas(vendas, plano_efetivo(plano), turno)
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
    turno: int,
) -> list[dict]:
    """PDVs do escopo ausentes na planilha entram com zero e plano padrão."""
    vistos = {l["parceiro_id"] for l in linhas}
    out = list(linhas)
    for pid, parceiro in sorted(mapa_parceiros.items(), key=lambda x: (x[1].nome or "").upper()):
        if pid not in vistos:
            out.append(_linha_parceiro(parceiro, turno=turno))
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
    """Importa base Excel: PDV, vendas do dia e Plano Dia (ritmo do turno)."""
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
    for _, row in df.iterrows():
        nome_pdv = texto(row.get("pdv"))
        if not nome_pdv or _eh_total_planilha(nome_pdv):
            continue
        vendas = _int_valor(row.get(col_vendas))
        plano = plano_efetivo(row.get(col_plano))
        pid = resolver_parceiro_id(nome_pdv, indice)
        if pid is None:
            sem_cadastro.append(nome_pdv)
            continue
        if escopo_ids is not None and pid not in escopo_ids:
            if pid not in ids_gerencia:
                continue
        parceiro = mapa_parceiros.get(pid)
        if parceiro is None and (escopo_ids is not None or pid in ids_gerencia):
            parceiro = Parceiro.objects.filter(pk=pid).select_related("especialista").first()
        if parceiro:
            por_id[pid] = _linha_parceiro(
                parceiro, vendas=vendas, plano=plano, turno=hora_turno
            )
        else:
            por_id[pid] = _linha_manual(
                parceiro_id=pid,
                pdv=nome_pdv,
                vendas=vendas,
                plano=plano,
                turno=hora_turno,
            )

    vendas_por_id = dict(por_id)
    linhas = list(por_id.values())
    if mapa_parceiros:
        linhas = _completar_parceiros_escopo(linhas, mapa_parceiros, turno=hora_turno)

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


def _recalcular_linha(linha: dict, turno: int) -> dict:
    """Garante métricas de ritmo mesmo em bases antigas (d7) ou incompletas."""
    vendas = int(linha.get("vendas") or 0)
    if "plano" in linha:
        plano = plano_efetivo(linha.get("plano"))
    elif "d7" in linha:
        # Lotes antigos: D-7 não é plano — usa default.
        plano = PLANO_DEFAULT
    else:
        plano = PLANO_DEFAULT
    met = _metricas(vendas, plano, turno)
    out = dict(linha)
    out.update(met)
    out.pop("d7", None)
    return out


def aplicar_escopo_parcial(dados: dict, parceiros: list) -> dict:
    """Recalcula totais/top/bottom para o escopo atual (ausentes entram com zero)."""
    mapa = {p.pk: p for p in parceiros}
    por_id = _mapa_vendas_parcial(dados)
    turno = int(dados.get("turno") or turno_parcial()[0])
    linhas: list[dict] = []
    for pid in sorted(mapa.keys(), key=lambda x: (mapa[x].nome or "").upper()):
        if pid in por_id:
            linha = _recalcular_linha(por_id[pid], turno)
            if not linha.get("especialista_id") and mapa[pid].especialista_id:
                linha = _linha_parceiro(
                    mapa[pid],
                    vendas=linha.get("vendas", 0),
                    plano=linha.get("plano"),
                    turno=turno,
                )
            linhas.append(linha)
        else:
            linhas.append(_linha_parceiro(mapa[pid], turno=turno))
    return {**dados, **_totais_parcial(linhas), "linhas": linhas}


def _top_e_piores(linhas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Top 5 e piores 5 por ritmo do turno, sem repetir PDV."""
    ordenado = sorted(
        linhas,
        key=lambda l: (-float(l.get("ritmo") or 0), -int(l.get("vendas") or 0), l["pdv"].upper()),
    )
    top5 = ordenado[:5]
    ids_top = {l["parceiro_id"] for l in top5}
    restantes = [l for l in linhas if l.get("parceiro_id") not in ids_top]
    pior5 = sorted(
        restantes,
        key=lambda l: (float(l.get("ritmo") or 0), int(l.get("vendas") or 0), l["pdv"].upper()),
    )[:5]
    return top5, pior5


def _totais_parcial(linhas: list[dict]) -> dict:
    top5, pior5 = _top_e_piores(linhas)
    total_pp = sum(int(l.get("vendas") or 0) for l in linhas)
    total_plano = round(sum(float(l.get("plano") or 0) for l in linhas), 2)
    total_esperado = round(sum(float(l.get("esperado") or 0) for l in linhas), 2)
    ritmo_pp = (total_pp / total_esperado) if total_esperado > 0 else 0.0
    return {
        "top5": top5,
        "pior5": pior5,
        "total_pp": total_pp,
        "total_plano": total_plano,
        "total_esperado": total_esperado,
        "ritmo_pp": ritmo_pp,
        "ritmo_pct": int(round(ritmo_pp * 100)),
        "delta_pp": int(round(total_pp - total_esperado)),
        "qtd_pdvs": len(linhas),
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
        ordenado = sorted(items, key=lambda l: (-l.get("vendas", 0), l.get("pdv", "").upper()))
        total_vendas = sum(l["vendas"] for l in ordenado)
        total_plano = round(sum(float(l.get("plano") or 0) for l in ordenado), 2)
        total_esperado = round(sum(float(l.get("esperado") or 0) for l in ordenado), 2)
        ritmo = (total_vendas / total_esperado) if total_esperado > 0 else 0.0
        grupos.append(
            {
                "especialista_id": None if chave == "sem" else int(chave),
                "especialista": nome_especialista_curto(nome_completo),
                "especialista_completo": nome_completo,
                "linhas": ordenado,
                "total_vendas": total_vendas,
                "total_plano": total_plano,
                "total_esperado": total_esperado,
                "ritmo": ritmo,
                "ritmo_pct": int(round(ritmo * 100)),
                "delta": int(round(total_vendas - total_esperado)),
                "qtd_pdvs": len(ordenado),
            }
        )
    grupos.sort(key=lambda g: (-g["total_vendas"], g["especialista"].upper()))
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


def fmt_ritmo(ritmo: float) -> str:
    return f"{int(round(float(ritmo or 0) * 100))}%"


def fmt_plano(valor: float) -> str:
    v = float(valor or 0)
    if abs(v - round(v)) < 0.05:
        return str(int(round(v)))
    return f"{v:.1f}".replace(".", ",")


def _fmt_linha_ritmo(item: dict) -> str:
    return (
        f"{item['pdv']} — {item['vendas']}/{fmt_plano(item.get('plano', 0))} "
        f"({fmt_ritmo(item.get('ritmo', 0))} ritmo · {_fmt_delta(int(item.get('delta', 0)))} vs esp.)"
    )


def mensagem_parcial_gerencia(dados: dict) -> str:
    ano, mes = dados["ano"], dados["mes"]
    rotulo = dados.get("rotulo_turno") or "—"
    partes = [
        f"📊 *Parcial PP · {mes:02d}/{ano} · {rotulo}*",
        (
            f"Total: *{dados['total_pp']}* VB · plano {fmt_plano(dados.get('total_plano', 0))} · "
            f"ritmo {fmt_ritmo(dados.get('ritmo_pp', 0))} · ∆ {_fmt_delta(dados['delta_pp'])} vs esp."
        ),
        "",
        "*Top 5 (ritmo do turno)*",
    ]
    for i, item in enumerate(dados.get("top5") or [], start=1):
        partes.append(f"{i}. {_fmt_linha_ritmo(item)}")
    partes.append("")
    partes.append("*Bottom 5 (ritmo do turno)*")
    for i, item in enumerate(dados.get("pior5") or [], start=1):
        partes.append(f"{i}. {_fmt_linha_ritmo(item)}")
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
            f"Total carteira: *{dados['total_pp']}* VB · "
            f"ritmo {fmt_ritmo(dados.get('ritmo_pp', 0))} · "
            f"∆ {_fmt_delta(dados['delta_pp'])} vs esp."
        ),
    ]
    for item in dados.get("linhas") or []:
        extra.append(f"• {_fmt_linha_ritmo(item)}")
    return base + "\n".join(extra)


def mensagem_parcial_pdv(linha: dict, dados: dict) -> str:
    return mensagem_parcial(
        pdv=linha["pdv"],
        ano=dados.get("ano"),
        mes=dados.get("mes"),
    ) + (
        f"\n\n📈 *Parcial · {dados.get('rotulo_turno', '—')}*\n"
        f"Total: *{linha['vendas']}* VB · plano {fmt_plano(linha.get('plano', 0))} · "
        f"ritmo {fmt_ritmo(linha.get('ritmo', 0))} · "
        f"∆ {_fmt_delta(int(linha.get('delta', 0)))} vs esp."
    )
