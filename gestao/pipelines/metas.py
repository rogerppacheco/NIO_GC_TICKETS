from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta

import pandas as pd

from tickets.models import Parceiro

from ..excel import listar_abas, ler_planilha, resolver_coluna, texto
from ..models import ConfiguracaoOSAB, MetaCapilaridade
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import anomes as montar_anomes

ABAS_FISICOS = ("BASE_FISICOS", "BASE FÍSICOS", "FISICOS")
ABAS_CALENDARIO = ("CALENDARIO", "CALENDÁRIO")
# Na BASE_FISICOS o orçado mensal vem como INDB=META (é o mesmo número da
# coluna ORÇADO das fichas de GC). FCAST é o plano semanal — não entra aqui.
INDB_ORCADO = "META"
INDS_META = {
    "VL": "meta_vl",
    "GROSS": "meta_gross",
    "CAPILARIDADE": "meta_vendedores",
}


def _achar_aba(abas: list[str], preferidas: tuple[str, ...], trecho: str) -> str | None:
    mapa = {str(a).strip().casefold(): a for a in abas}
    for pref in preferidas:
        if pref.casefold() in mapa:
            return mapa[pref.casefold()]
    for aba in abas:
        if trecho in str(aba).casefold():
            return aba
    return None


def _numero(valor) -> float:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or pd.isna(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace(" ", "").replace(",", ".")
    if not txt:
        return 0.0
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _data_calendario(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    if 20000 < n < 80000:
        return date(1899, 12, 30) + timedelta(days=int(n))
    return None


def extrair_du_calendario(df: pd.DataFrame, ano: int, mes: int) -> dict | None:
    col_anomes = resolver_coluna(df, ["ANOMES", "ANO_MES", "ANOMES_REF"])
    col_data = resolver_coluna(df, ["DATA", "DT", "DIA"])
    col_vl = resolver_coluna(df, ["DU_REG", "DU_VL", "DU_VB", "DU_MTZ"])
    col_gr = resolver_coluna(df, ["DU_GROSS", "DU_GR"])
    if not col_anomes or not col_vl:
        return None
    alvo = montar_anomes(ano, mes)
    pesos_vl: dict[str, float] = {}
    pesos_gr: dict[str, float] = {}
    for _, row in df.iterrows():
        try:
            am = int(float(row.get(col_anomes)))
        except (TypeError, ValueError):
            continue
        if am != alvo:
            continue
        dia = _data_calendario(row.get(col_data)) if col_data else None
        if dia is None or dia.year != ano or dia.month != mes:
            continue
        chave = str(dia.day)
        pesos_vl[chave] = _numero(row.get(col_vl))
        if col_gr:
            pesos_gr[chave] = _numero(row.get(col_gr))
        else:
            pesos_gr[chave] = pesos_vl[chave]
    if not pesos_vl:
        return None
    ultimo = monthrange(ano, mes)[1]
    return {
        "du_vl": round(sum(pesos_vl.values()), 4),
        "du_gross": round(sum(pesos_gr.values()), 4),
        "pesos_diarios_vl": json.dumps({str(d): round(pesos_vl.get(str(d), 0.0), 6) for d in range(1, ultimo + 1)}),
        "pesos_diarios_gross": json.dumps(
            {str(d): round(pesos_gr.get(str(d), 0.0), 6) for d in range(1, ultimo + 1)}
        ),
    }


def extrair_metas_fisicos(df: pd.DataFrame, ano: int, mes: int) -> tuple[dict[str, dict], list[int]]:
    col_indb = resolver_coluna(df, ["INDB", "TIPO", "TIPO_IND"])
    col_ind = resolver_coluna(df, ["INDICADOR"])
    col_qtde = resolver_coluna(df, ["QTDE", "QUANTIDADE", "VALOR", "META"])
    col_am = resolver_coluna(df, ["ANOMES", "ANO_MES"])
    col_pdv = resolver_coluna(df, ["NM_PDV_GRUPO", "NM_PDV", "PDV", "DESCRICAO"])
    if not all([col_indb, col_ind, col_qtde, col_am, col_pdv]):
        raise ValueError(
            "A aba BASE_FISICOS precisa de INDB, INDICADOR, QTDE, ANOMES e NM_PDV_GRUPO. "
            f"Colunas: {list(df.columns)}"
        )
    alvo = montar_anomes(ano, mes)
    meses: set[int] = set()
    por_pdv: dict[str, dict] = {}
    for _, row in df.iterrows():
        try:
            am = int(float(row.get(col_am)))
        except (TypeError, ValueError):
            continue
        meses.add(am)
        if am != alvo:
            continue
        if texto(row.get(col_indb)).upper() != INDB_ORCADO:
            continue
        ind = texto(row.get(col_ind)).upper()
        campo = INDS_META.get(ind)
        if not campo:
            continue
        pdv = texto(row.get(col_pdv), 150)
        if not pdv:
            continue
        item = por_pdv.setdefault(pdv, {"nome": pdv})
        item[campo] = _numero(row.get(col_qtde))
    return por_pdv, sorted(m for m in meses if 202001 <= m <= 210012)


def persistir_metas(linhas: dict[str, dict], ano: int, mes: int, du: dict | None) -> dict:
    indice = indice_parceiros()
    atualizados = 0
    sem_cadastro = []
    for nome, dados in linhas.items():
        pid = resolver_parceiro_id(nome, indice)
        if not pid:
            sem_cadastro.append(nome)
            continue
        parceiro = Parceiro.objects.get(pk=pid)
        if "meta_vendedores" in dados:
            MetaCapilaridade.objects.update_or_create(
                parceiro=parceiro,
                ano=ano,
                mes=mes,
                defaults={"meta_vendedores": int(round(dados["meta_vendedores"]))},
            )
        osab_defaults: dict = {}
        if "meta_vl" in dados:
            osab_defaults["meta_vl"] = int(round(dados["meta_vl"]))
        if "meta_gross" in dados:
            osab_defaults["meta_gross"] = int(round(dados["meta_gross"]))
        if du:
            osab_defaults.update(du)
        if osab_defaults:
            ConfiguracaoOSAB.objects.update_or_create(
                parceiro=parceiro, ano=ano, mes=mes, defaults=osab_defaults
            )
        atualizados += 1
    return {
        "atualizados": atualizados,
        "na_planilha": len(linhas),
        "sem_cadastro": sem_cadastro[:40],
        "sem_cadastro_n": len(sem_cadastro),
        "du_vl": du["du_vl"] if du else None,
        "du_gross": du["du_gross"] if du else None,
    }


def processar_metas(arquivo, nome_arquivo: str, ano: int, mes: int) -> dict:
    abas = listar_abas(arquivo, nome_arquivo)
    aba_base = _achar_aba(abas, ABAS_FISICOS, "fisic")
    if not aba_base:
        raise ValueError(
            "Não achei a aba BASE_FISICOS no acompanhamento semanal. "
            f"Abas: {abas[:12]}"
        )
    df_base = ler_planilha(arquivo, nome_arquivo, sheet_name=aba_base)
    linhas, meses = extrair_metas_fisicos(df_base, ano, mes)
    if not linhas:
        disp = ", ".join(f"{m % 100:02d}/{m // 100}" for m in meses) or "nenhum"
        raise ValueError(
            f"Não há orçado (INDB=META) de VL/Gross/Capilaridade para {mes:02d}/{ano}. "
            f"Meses na base: {disp}."
        )
    du = None
    aba_cal = _achar_aba(abas, ABAS_CALENDARIO, "calend")
    if aba_cal:
        df_cal = ler_planilha(arquivo, nome_arquivo, sheet_name=aba_cal)
        du = extrair_du_calendario(df_cal, ano, mes)
    resumo = persistir_metas(linhas, ano, mes, du)
    resumo.update({"aba": aba_base, "aba_calendario": aba_cal or "", "ano": ano, "mes": mes})
    return resumo
