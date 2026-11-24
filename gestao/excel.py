from __future__ import annotations

import io
import re
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd
from django.utils.timezone import get_current_timezone, is_naive, make_aware


def _bytes_planilha(arquivo, nome: str = "") -> tuple[bytes, str]:
    nome = nome or getattr(arquivo, "name", "") or ""
    conteudo = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)
    return conteudo, nome


def _engine_excel(sufixo: str) -> str | None:
    if sufixo == ".xlsb":
        return "pyxlsb"
    if sufixo == ".xls":
        return "xlrd"
    return None


def _parece_html(conteudo: bytes) -> bool:
    """Detecta HTML/Excel-HTML mesmo com BOM ou DOCTYPE em caixa mista."""
    amostra = conteudo[:8192].lstrip()
    if amostra.startswith(b"\xef\xbb\xbf"):
        amostra = amostra[3:].lstrip()
    head = amostra[:64].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return True
    lower = amostra.lower()
    return b"<table" in lower and (
        b"<html" in lower or b"<body" in lower or b"excel.sheet" in lower or b"progid" in lower
    )


def _decodificar_html(conteudo: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def _ler_html_tabela(conteudo: bytes) -> pd.DataFrame:
    """Lê a primeira tabela de um .xls que na verdade é HTML (export Sysmap)."""
    texto = _decodificar_html(conteudo)
    erros: list[str] = []
    for flavor in ("html5lib", "lxml", "bs4"):
        try:
            tabelas = pd.read_html(io.StringIO(texto), flavor=flavor)
        except Exception as exc:  # noqa: BLE001 — tenta próximo parser
            erros.append(f"{flavor}: {exc}")
            continue
        if tabelas:
            return tabelas[0]
        erros.append(f"{flavor}: no tables found")
    detalhe = "; ".join(erros[:3]) if erros else "sem parsers"
    raise ValueError(
        "Nenhuma tabela encontrada no HTML. "
        "Abra no Excel e Salvar como .xlsx (ou esvazie o CPF sem apagar a coluna). "
        f"Detalhe: {detalhe}"
    )


def ler_planilha(arquivo, nome: str = "", sheet_name=0, **kwargs) -> pd.DataFrame:
    """Lê .xlsx, .xlsb, .xls e HTML exportado como .xls."""
    conteudo, nome = _bytes_planilha(arquivo, nome)
    sufixo = Path(nome).suffix.lower()
    if _parece_html(conteudo):
        return _ler_html_tabela(conteudo)

    with tempfile.NamedTemporaryFile(suffix=sufixo or ".xlsx", delete=False) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        read_kwargs = {"sheet_name": sheet_name, **kwargs}
        engine = _engine_excel(sufixo)
        if engine:
            read_kwargs["engine"] = engine
        return pd.read_excel(caminho, **read_kwargs)
    finally:
        Path(caminho).unlink(missing_ok=True)


def listar_abas(arquivo, nome: str = "") -> list[str]:
    conteudo, nome = _bytes_planilha(arquivo, nome)
    sufixo = Path(nome).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=sufixo or ".xlsx", delete=False) as tmp:
        tmp.write(conteudo)
        caminho = tmp.name
    try:
        kwargs = {}
        engine = _engine_excel(sufixo)
        if engine:
            kwargs["engine"] = engine
        with pd.ExcelFile(caminho, **kwargs) as xl:
            return list(xl.sheet_names)
    finally:
        Path(caminho).unlink(missing_ok=True)


def chave_coluna(nome) -> str:
    """Compara colunas ignorando acento, caixa, espaços e pontuação.

    Preserva `%` como `pct` para não colidir "Plano Dia" com "% Plano Dia"
    (export do BI da parcial).
    """
    texto = unicodedata.normalize("NFKD", str(nome or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold().replace("%", " pct ")
    return re.sub(r"[^a-z0-9]+", "", texto)


def _coluna_parece_percentual(nome) -> bool:
    bruto = str(nome or "").strip()
    if bruto.startswith("%"):
        return True
    chave = chave_coluna(bruto)
    return chave.startswith("pct") or "percent" in chave


def resolver_coluna(df: pd.DataFrame, opcoes: list[str]) -> str | None:
    colunas = list(df.columns)
    for nome in opcoes:
        if nome in colunas:
            return nome
    mapa_cf = {str(c).casefold(): c for c in colunas}
    for nome in opcoes:
        achou = mapa_cf.get(str(nome).casefold())
        if achou is not None:
            return achou
    # Em colisão de chave, preferir a coluna alinhada ao alias (% vs absoluto).
    mapa_chave: dict[str, list] = {}
    for c in colunas:
        mapa_chave.setdefault(chave_coluna(c), []).append(c)
    for nome in opcoes:
        candidatos = mapa_chave.get(chave_coluna(nome)) or []
        if not candidatos:
            continue
        if len(candidatos) == 1:
            return candidatos[0]
        quer_pct = _coluna_parece_percentual(nome)
        alinhados = [c for c in candidatos if _coluna_parece_percentual(c) == quer_pct]
        return (alinhados or candidatos)[0]
    return None


def aplicar_aliases(df: pd.DataFrame, campos: dict[str, list[str]]) -> pd.DataFrame:
    """Renomeia a primeira coluna encontrada de cada campo para o nome canônico."""
    out = df.copy()
    rename: dict[str, str] = {}
    usados: set[str] = set()
    for canon, aliases in campos.items():
        existente = resolver_coluna(out, [canon])
        if existente is not None:
            if existente != canon and existente not in usados and existente not in rename:
                rename[existente] = canon
                usados.add(existente)
            continue
        achou = resolver_coluna(out, aliases)
        if not achou or achou in usados or achou in rename:
            continue
        rename[achou] = canon
        usados.add(achou)
    if rename:
        out = out.rename(columns=rename)
    return out


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
