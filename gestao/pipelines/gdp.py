from __future__ import annotations

from ..excel import listar_abas, ler_planilha, resolver_coluna, texto
from ..models import PracaBTU
from .resultados import normalizar_praca

ABAS_PREFERIDAS = ("PAP (Local)", "PAP")
PREFIXO_PORTFOLIO = "PORTFOLIO_GDP"


def eh_portfolio_btu(valor: str) -> bool:
    """Oferta especial (BTU / 50%): ESPECIAL ou NOVO ESPECIAL no GDP vigente."""
    return "ESPECIAL" in normalizar_praca(valor)


def _coluna_portfolio_vigente(df) -> str | None:
    cols = [c for c in df.columns if str(c).upper().startswith(PREFIXO_PORTFOLIO)]
    return str(cols[-1]) if cols else None


def _escolher_aba(arquivo, nome: str) -> str:
    abas = listar_abas(arquivo, nome)
    if not abas:
        raise ValueError("O GDP não tem abas.")
    mapa = {str(a).strip().casefold(): a for a in abas}
    for pref in ABAS_PREFERIDAS:
        if pref.casefold() in mapa:
            return mapa[pref.casefold()]
    for aba in abas:
        if "pap" in str(aba).casefold():
            return aba
    return abas[0]


def extrair_pracas_gdp(arquivo, nome_arquivo: str) -> tuple[list[dict], dict]:
    aba = _escolher_aba(arquivo, nome_arquivo)
    df = ler_planilha(arquivo, nome_arquivo, sheet_name=aba)
    col_mun = resolver_coluna(df, ["MUNICIPIO", "MUNICÍPIO", "CIDADE"])
    col_port = _coluna_portfolio_vigente(df)
    if not col_mun or not col_port:
        raise ValueError(
            "O GDP precisa das colunas MUNICIPIO e PORTFOLIO_GDP_… "
            f"(aba {aba!r}, colunas: {list(df.columns)[:12]}…)."
        )
    col_uf = resolver_coluna(df, ["UF"])
    col_ibge = resolver_coluna(df, ["COD_IBGE", "IBGE"])
    linhas: dict[str, dict] = {}
    for _, row in df.iterrows():
        portfolio = texto(row.get(col_port), 40)
        if not eh_portfolio_btu(portfolio):
            continue
        nome = texto(row.get(col_mun), 120)
        norm = normalizar_praca(nome)
        if not norm:
            continue
        uf = texto(row.get(col_uf), 2).upper() if col_uf else ""
        linhas[norm] = {
            "nome": nome,
            "nome_norm": norm,
            "uf": uf,
            "cod_ibge": texto(row.get(col_ibge), 16) if col_ibge else "",
            "portfolio": portfolio,
        }
    meta = {
        "arquivo": nome_arquivo,
        "aba": aba,
        "coluna": col_port,
        "linhas": int(len(df)),
        "especial": len(linhas),
    }
    return list(linhas.values()), meta


def persistir_pracas_gdp(linhas: list[dict]) -> dict:
    vistos: set[str] = set()
    inseridos = atualizados = 0
    for row in linhas:
        norm = row["nome_norm"]
        vistos.add(norm)
        defaults = {
            "nome": row["nome"],
            "uf": row.get("uf") or "",
            "cod_ibge": row.get("cod_ibge") or "",
            "portfolio": row.get("portfolio") or "",
            "fonte": PracaBTU.Fonte.GDP,
            "ativo": True,
        }
        obj, criado = PracaBTU.objects.update_or_create(nome_norm=norm, defaults=defaults)
        if criado:
            inseridos += 1
        else:
            atualizados += 1
    desativados = 0
    if vistos:
        qs = PracaBTU.objects.filter(fonte=PracaBTU.Fonte.GDP, ativo=True).exclude(
            nome_norm__in=vistos
        )
        desativados = qs.update(ativo=False)
    return {
        "inseridos": inseridos,
        "atualizados": atualizados,
        "desativados": desativados,
        "ativas": PracaBTU.objects.filter(ativo=True).count(),
        "mg": PracaBTU.objects.filter(ativo=True, uf="MG").count(),
    }


def processar_gdp(arquivos: list[tuple]) -> dict:
    """Une B2C e/ou B2B: município é BTU se estiver ESPECIAL em qualquer arquivo."""
    if not arquivos:
        raise ValueError("Envie o GDP B2C e/ou B2B (.xlsx).")
    mapa: dict[str, dict] = {}
    origens = []
    for arquivo, nome in arquivos:
        extraidas, meta = extrair_pracas_gdp(arquivo, nome)
        origens.append(meta)
        for row in extraidas:
            mapa[row["nome_norm"]] = row
    persistido = persistir_pracas_gdp(list(mapa.values()))
    return {**persistido, "origens": origens, "especial_uniao": len(mapa)}
