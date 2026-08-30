from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

import pandas as pd

from ..excel import listar_abas, ler_planilha
from .calendario import aplicar_nos_pdvs, garantir_mes
from .metas import _numero

ABAS_VB = ("Tabela detalhada DU - (VB)",)
ABAS_GROSS = ("Tabela detalhada DU - (Gross)",)


def _linha_pond(df: pd.DataFrame, rotulo: str) -> int:
    alvo = rotulo.casefold()
    for i in range(min(len(df), 20)):
        cel = str(df.iloc[i, 1] if df.shape[1] > 1 else "").strip().casefold()
        if cel == alvo:
            return i
    return 8


def _pesos_mes(df: pd.DataFrame, ano: int, mes: int, linha_pond: int) -> dict[str, float]:
    prefixo = f"{ano}{mes:02d}"
    pesos: dict[str, float] = {}
    for j in range(df.shape[1]):
        chave = df.iloc[2, j]
        if pd.isna(chave) or not str(chave).startswith(prefixo):
            continue
        raw_data = df.iloc[3, j]
        if isinstance(raw_data, datetime):
            dia = raw_data.date()
        elif isinstance(raw_data, date):
            dia = raw_data
        else:
            continue
        if dia.year != ano or dia.month != mes:
            continue
        pesos[str(dia.day)] = round(_numero(df.iloc[linha_pond, j]), 6)
    return pesos


def extrair_du_consolidado(arquivo, nome_arquivo: str, ano: int, mes: int) -> dict:
    abas = listar_abas(arquivo, nome_arquivo)
    aba_vb = next((a for a in abas if a in ABAS_VB or "detalhada du - (vb)" in a.casefold()), None)
    aba_gr = next(
        (a for a in abas if a in ABAS_GROSS or "detalhada du - (gross)" in a.casefold()),
        None,
    )
    if not aba_vb:
        raise ValueError("Consolidado DU sem aba «Tabela detalhada DU - (VB)».")
    df_vb = ler_planilha(arquivo, nome_arquivo, sheet_name=aba_vb, header=None)
    linha_vb = _linha_pond(df_vb, "Pond VB")
    pesos_vl = _pesos_mes(df_vb, ano, mes, linha_vb)
    if not pesos_vl:
        raise ValueError(f"Nenhum peso VB encontrado para {mes:02d}/{ano} no consolidado.")

    pesos_gr = pesos_vl
    if aba_gr:
        df_gr = ler_planilha(arquivo, nome_arquivo, sheet_name=aba_gr, header=None)
        linha_gr = _linha_pond(df_gr, "Pond Gross")
        pesos_gr = _pesos_mes(df_gr, ano, mes, linha_gr) or pesos_vl

    ultimo = monthrange(ano, mes)[1]
    for d in range(1, ultimo + 1):
        ch = str(d)
        pesos_vl.setdefault(ch, 0.0)
        pesos_gr.setdefault(ch, 0.0)

    du_vl = round(sum(pesos_vl.values()), 4)
    du_gross = round(sum(pesos_gr.values()), 4)
    return {
        "du_vl": du_vl,
        "du_gross": du_gross,
        "pesos_vl": pesos_vl,
        "pesos_gr": pesos_gr,
        "dias": ultimo,
    }


def aplicar_du_consolidado(arquivo, nome_arquivo: str, ano: int, mes: int) -> dict:
    dados = extrair_du_consolidado(arquivo, nome_arquivo, ano, mes)
    garantir_mes(ano, mes)
    for dia in garantir_mes(ano, mes):
        ch = str(dia.data.day)
        dia.peso_vl = float(dados["pesos_vl"].get(ch, 0.0))
        dia.peso_gross = float(dados["pesos_gr"].get(ch, 0.0))
        dia.save(update_fields=["peso_vl", "peso_gross"])
    n_pdvs = aplicar_nos_pdvs(ano, mes)
    return {**dados, "pdvs_atualizados": n_pdvs}
