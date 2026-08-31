from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
from django.utils import timezone

from tickets.models import Parceiro

from .models import HistoricoChurn, RelatorioFPD, VendaOSAB
from .periodo import periodo_ativo
from .pipelines.osab import linhas_capilaridade_pdv


def _celula_excel(valor):
    """OpenPyXL recusa datetime com tz; pd.NaT também quebra utcoffset."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, datetime):
        try:
            if timezone.is_aware(valor):
                valor = timezone.localtime(valor)
            return valor.replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            return None
    return valor


def df_para_xlsx(df: pd.DataFrame, nome_arquivo: str) -> tuple[bytes, str]:
    trabalho = df.copy()
    if not trabalho.empty:
        for col in trabalho.columns:
            trabalho[col] = trabalho[col].map(_celula_excel)
    buf = io.BytesIO()
    trabalho.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue(), nome_arquivo


def _tag(parceiro: Parceiro) -> str:
    return (parceiro.nome or "PDV").replace(" ", "_")[:40]


def planilha_capilaridade(parceiro: Parceiro, filtros: dict | None = None) -> tuple[bytes, str]:
    linhas = linhas_capilaridade_pdv(parceiro, filtros)
    df = pd.DataFrame(
        [
            {
                "TT": l.get("matricula_vendedor"),
                "Nome": l.get("nome_vendedor"),
                "Cargo": l.get("cargo_funcao"),
                "Situação": l.get("situacao_funcional"),
                "PDV": l.get("pdv_nome"),
                "Status": l.get("status"),
                "Dias sem vender": l.get("dias_sem_vender"),
                "Última venda": l.get("ultima_venda"),
            }
            for l in linhas
        ]
    )
    if df.empty:
        df = pd.DataFrame(columns=["TT", "Nome", "Cargo", "Situação", "PDV", "Status"])
    return df_para_xlsx(df, f"Capilaridade_{_tag(parceiro)}.xlsx")


def planilha_osab(parceiro: Parceiro) -> tuple[bytes, str]:
    ano, mes = periodo_ativo()
    qs = VendaOSAB.objects.filter(parceiro=parceiro, data_abertura__year=ano, data_abertura__month=mes)
    rows = [
        {
            "Pedido": v.pedido,
            "Matrícula": v.matricula_vendedor,
            "Vendedor": v.nome_vendedor,
            "PDV": v.pdv_nome,
            "Abertura": v.data_abertura,
            "Fechamento": v.data_fechamento,
            "Situação": v.situacao,
            "Velocidade": v.velocidade,
            "Pagamento": v.meio_pagamento,
            "Município": v.municipio,
        }
        for v in qs
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Pedido", "Matrícula", "Vendedor", "PDV", "Abertura", "Fechamento", "Situação"]
    )
    return df_para_xlsx(df, f"OSAB_{_tag(parceiro)}_{mes:02d}-{ano}.xlsx")


from .fpd_format import planilha_fpd


def planilha_churn(parceiro: Parceiro) -> tuple[bytes, str]:
    qs = HistoricoChurn.objects.filter(parceiro=parceiro).order_by("-data_analise", "-anomes_gross")
    ultima = qs.values_list("data_analise", flat=True).first()
    if ultima:
        qs = qs.filter(data_analise=ultima)
    rows = [
        {
            "PDV": h.pdv_nome,
            "Safra": h.anomes_gross,
            "Gross": h.gross,
            "Churn": h.churn,
            "Taxa %": h.taxa_churn,
            "Remanescentes": h.remanescentes,
        }
        for h in qs
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["PDV", "Safra", "Gross", "Churn", "Taxa %"])
    return df_para_xlsx(df, f"Churn_{_tag(parceiro)}.xlsx")


def planilha_acumulado(resumo: dict) -> tuple[bytes, str]:
    d0 = resumo.get("d0")
    d1 = resumo.get("d1")
    rows = [
        {
            "PDV": l["pdv"],
            "Meta VB": l["meta_vb"],
            "Realizado VB": l["realizado_vb"],
            "% meta VB": None if l["pct_vb"] is None else round(l["pct_vb"], 1),
            "VB D-1": l["d1_vb"],
            "VB D0": l["d0_vb"],
            "Meta Gross": l["meta_gross"],
            "Realizado Gross": l["realizado_gross"],
            "% meta Gross": None if l["pct_gross"] is None else round(l["pct_gross"], 1),
            "Gross D-1": l["d1_gross"],
            "Gross D0": l["d0_gross"],
            "D0": d0.isoformat() if d0 else "",
            "D-1": d1.isoformat() if d1 else "",
        }
        for l in resumo.get("linhas") or []
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["PDV", "Meta VB", "Realizado VB", "% meta VB", "VB D-1", "VB D0"]
    )
    mes, ano = resumo.get("mes"), resumo.get("ano")
    nome = f"Acumulado_{mes:02d}-{ano}.xlsx" if mes and ano else "Acumulado.xlsx"
    return df_para_xlsx(df, nome)


def planilha_ranking(ranking: dict) -> tuple[bytes, str]:
    rotulos = {
        "regular": "Base Regular",
        "iniciante": "Iniciante",
        "sem_cadastro": "Sem cadastro",
    }
    rows = []
    for chave, grupo in (ranking.get("grupos") or {}).items():
        for item in grupo:
            rows.append(
                {
                    "Grupo": rotulos.get(chave, chave),
                    "RKG": item.get("posicao"),
                    "PDV": item.get("pdv"),
                    "Especialista": item.get("especialista"),
                    "Esp. curto": item.get("especialista_curto"),
                    "PTS janela": item.get("pontos_dia"),
                    "BTU": item.get("vb_btu"),
                    "Padrão": item.get("vb_padrao"),
                    "PTS acumulado": item.get("pontos"),
                }
            )
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Grupo", "RKG", "PDV", "Especialista", "PTS acumulado"]
    )
    periodo = ranking.get("periodo") or {}
    fim = periodo.get("fim")
    nome = f"Ranking_VB_{fim.isoformat()}.xlsx" if fim else "Ranking_VB.xlsx"
    return df_para_xlsx(df, nome)


def planilha_vb_sem_municipio(parceiros: list[Parceiro], data_ref=None) -> tuple[bytes, str]:
    from .pipelines.resultados import periodo_ranking, vendas_sem_municipio

    vendas = vendas_sem_municipio(parceiros, data_ref)
    periodo = periodo_ranking(data_ref)
    rows = [
        {
            "Pedido": v.pedido,
            "PDV": v.pdv_nome or (v.parceiro.nome if v.parceiro else ""),
            "Matrícula": v.matricula_vendedor,
            "Vendedor": v.nome_vendedor,
            "Município": v.municipio,
            "Situação": v.situacao,
            "Abertura": v.data_abertura,
            "Fechamento": v.data_fechamento,
            "Velocidade": v.velocidade,
        }
        for v in vendas
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Pedido", "PDV", "Matrícula", "Vendedor", "Município", "Situação", "Abertura"]
    )
    fim = periodo.get("fim")
    nome = f"VB_sem_municipio_{fim.isoformat()}.xlsx" if fim else "VB_sem_municipio.xlsx"
    return df_para_xlsx(df, nome)


def bytes_arquivo_field(arquivo_field, nome_fallback: str) -> tuple[bytes, str]:
    if not arquivo_field:
        return b"", nome_fallback
    with arquivo_field.open("rb") as fh:
        nome = Path(arquivo_field.name).name or nome_fallback
        return fh.read(), nome
