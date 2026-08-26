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
    """OpenPyXL recusa datetime com tz; o 500 do Enviar todos vinha daqui."""
    if isinstance(valor, datetime):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.replace(tzinfo=None)
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
        }
        for v in qs
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Pedido", "Matrícula", "Vendedor", "PDV", "Abertura", "Fechamento", "Situação"]
    )
    return df_para_xlsx(df, f"OSAB_{_tag(parceiro)}_{mes:02d}-{ano}.xlsx")


def planilha_fpd(rel: RelatorioFPD) -> tuple[bytes, str]:
    rows = []
    for mes in (rel.detalhes or {}).get("meses") or []:
        faixas = mes.get("faixas") or {}
        rows.append(
            {
                "PDV": rel.pdv_nome,
                "Mês": mes.get("mes"),
                "Total": mes.get("total"),
                "Pagas": mes.get("pagas"),
                "Abertas": mes.get("abertas"),
                "10 a 15": faixas.get("10 a 15 Dias", 0),
                "15 a 30": faixas.get("15 a 30 Dias", 0),
                "30 a 45": faixas.get("30 a 45 Dias", 0),
                "45 a 55": faixas.get("45 a 55 Dias", 0),
                "55 a 60": faixas.get("55 a 60 Dias", 0),
                ">60": faixas.get(">= a 61 Dias", 0),
            }
        )
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        [{"PDV": rel.pdv_nome, "FPD %": rel.percentual, "Abertas": rel.total_abertas, "Total": rel.total_faturas}]
    )
    return df_para_xlsx(df, f"FPD_{_tag(rel.parceiro)}.xlsx")


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


def bytes_arquivo_field(arquivo_field, nome_fallback: str) -> tuple[bytes, str]:
    if not arquivo_field:
        return b"", nome_fallback
    with arquivo_field.open("rb") as fh:
        nome = Path(arquivo_field.name).name or nome_fallback
        return fh.read(), nome
