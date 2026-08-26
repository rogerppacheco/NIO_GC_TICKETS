from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
from django.utils.timezone import get_current_timezone, is_naive, make_aware


def ler_planilha(arquivo, nome: str = "") -> pd.DataFrame:
    """Lê .xlsx, .xlsb, .xls e HTML exportado como .xls."""
    nome = nome or getattr(arquivo, "name", "") or ""
    conteudo = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)

    sufixo = Path(nome).suffix.lower()
    inicio = conteudo[:200].lstrip()
    if inicio.startswith(b"<!DOCTYPE") or inicio.startswith(b"<html"):
        tabelas = pd.read_html(io.BytesIO(conteudo), encoding="utf-8")
        if not tabelas:
            raise ValueError("Nenhuma tabela encontrada no arquivo HTML.")
        return tabelas[0]

    with tempfile.NamedTemporaryFile(suffix=sufixo or ".xlsx", delete=False) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        if sufixo == ".xlsb":
            return pd.read_excel(caminho, engine="pyxlsb")
        if sufixo == ".xls":
            return pd.read_excel(caminho, engine="xlrd")
        return pd.read_excel(caminho)
    finally:
        Path(caminho).unlink(missing_ok=True)


def resolver_coluna(df: pd.DataFrame, opcoes: list[str]) -> str | None:
    for nome in opcoes:
        if nome in df.columns:
            return nome
    mapa = {str(c).casefold(): c for c in df.columns}
    for nome in opcoes:
        achou = mapa.get(str(nome).casefold())
        if achou is not None:
            return achou
    return None


def converter_data_robusto(coluna: pd.Series) -> pd.Series:
    datas = pd.Series([pd.NaT] * len(coluna), index=coluna.index, dtype="datetime64[ns]")
    numeros = pd.to_numeric(coluna, errors="coerce")
    validos = numeros.notna()
    if validos.any():
        serie = numeros[validos]
        excel = (serie > 36526) & (serie < 80000)
        if excel.any():
            datas.loc[serie[excel].index] = pd.to_datetime("1899-12-30") + pd.to_timedelta(
                serie[excel].astype("float64"), unit="D"
            )
    restantes = datas.isna()
    if restantes.any():
        datas.loc[restantes] = pd.to_datetime(coluna[restantes], errors="coerce", dayfirst=True)
    return datas


def as_aware(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or pd.isna(valor):
        return None
    if hasattr(valor, "to_pydatetime"):
        valor = valor.to_pydatetime()
    if getattr(valor, "tzinfo", None) is None or is_naive(valor):
        return make_aware(valor, get_current_timezone())
    return valor


def texto(valor, limite: int | None = None) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or pd.isna(valor):
        return ""
    saida = str(valor).strip()
    if saida.endswith(".0") and saida.replace(".0", "").isdigit():
        saida = saida[:-2]
    if limite:
        return saida[:limite]
    return saida
