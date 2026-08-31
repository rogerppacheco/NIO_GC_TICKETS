"""Aliases e-mail × Power BI para OSAB e FPD.

Os dois canais trazem o mesmo conteúdo; o BI só muda o nome de algumas colunas
(ex.: APELIDO → nm_pdv_rel, REF_VENCTO → MES_VENC). Depois do normalize, o
resto do pipeline usa sempre os nomes canônicos.
"""
from __future__ import annotations

import pandas as pd

from .excel import aplicar_aliases

# Nome interno → nomes vistos no e-mail e no export do BI
OSAB_CAMPOS: dict[str, list[str]] = {
    "PEDIDO": ["PEDIDO", "NUMERO_PEDIDO", "PEDIDO_ID", "NUMERO_ORDEM", "nr_ordem_original"],
    "DT_REF": ["DT_REF", "DATA_REF", "DT_REFERENCIA", "DATA_REFERENCIA"],
    "DESCRICAO": ["DESCRICAO", "nm_pdv_rel", "NM_PDV_REL", "APELIDO", "REDE"],
    "DATA_ABERTURA": ["DATA_ABERTURA", "DT_ABERTURA"],
    "DATA_FECHAMENTO": ["DATA_FECHAMENTO", "DT_FECHAMENTO"],
    "MATRICULA_VENDEDOR": ["MATRICULA_VENDEDOR", "MATRICULA", "cd_tr_vdd_original"],
    "NOME_VENDEDOR": ["NOME_VENDEDOR", "NM_VENDEDOR"],
    "SITUACAO": ["SITUACAO", "STATUS"],
    "VELOCIDADE": ["VELOCIDADE"],
    "NM_GC": ["NM_GC", "nm_gc", "NOME_GC", "nome_gc"],
    "PDV_SAP": ["PDV_SAP", "pdv_sap", "cd_sap_original"],
    "LOCALIDADE": [
        "LOCALIDADE",
        "NM_LOCALIDADE",
        "MUNICIPIO",
        "NM_MUNICIPIO",
        "CIDADE",
        "MUNICÍPIO",
        "NM_MUNICIPIO_INSTALACAO",
        "CIDADE_INSTALACAO",
        "PRACA",
        "PRAÇA",
        "NM_PRACA",
    ],
    "OFERTA": [
        "OFERTA",
        "NOME_OFERTA",
        "NOME_PLANO",
        "CAMPANHA",
        "PACOTE",
        "DESCRICAO_OFERTA",
        "PLANO",
        "PRODUTO",
    ],
    "GERENCIA": ["GERENCIA", "GERÊNCIA", "NM_GERENCIA", "NM_GERÊNCIA", "GESTAO", "GESTÃO"],
    "MEIO_PAGAMENTO": [
        "MEIO_PAGAMENTO",
        "meio_pagamento",
        "FORMA_PAGAMENTO",
        "FORMA_PGTO",
        "PAGAMENTO",
    ],
}

FPD_CAMPOS: dict[str, list[str]] = {
    "APELIDO": ["APELIDO", "nm_pdv_rel", "NM_PDV_REL", "REDE", "DESC_APELIDO"],
    "REF_VENCTO": ["REF_VENCTO", "MES_VENC", "MES_VENCIMENTO"],
    "SITUACAO_FATURA_MENSAL": [
        "SITUACAO_FATURA_MENSAL",
        "DS_SIT_FATURA",
        "DS_STATUS_FATURA",
    ],
    "FAIXA": ["FAIXA"],
    "INDICADOR": ["INDICADOR"],
}


def _linha_lixo_powerbi(valores) -> bool:
    for valor in valores:
        if isinstance(valor, str) and "filtros aplicados" in valor.casefold():
            return True
    return False


def normalizar_osab(df: pd.DataFrame) -> pd.DataFrame:
    trabalho = aplicar_aliases(df, OSAB_CAMPOS)
    if trabalho.empty:
        return trabalho
    mascara = ~trabalho.apply(_linha_lixo_powerbi, axis=1)
    return trabalho.loc[mascara].copy()


def normalizar_fpd(df: pd.DataFrame) -> pd.DataFrame:
    trabalho = aplicar_aliases(df, FPD_CAMPOS)
    if trabalho.empty:
        return trabalho
    mascara = ~trabalho.apply(_linha_lixo_powerbi, axis=1)
    return trabalho.loc[mascara].copy()
