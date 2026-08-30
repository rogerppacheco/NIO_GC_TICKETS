from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from tickets.models import Parceiro

from ..excel import ler_planilha, resolver_coluna, texto
from ..parceiros import indice_parceiros, resolver_parceiro_id


def _parse_data(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    txt = str(valor).strip()
    if not txt or txt.lower() in ("nat", "nan"):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(txt[:10], fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(valor).date()
    except (TypeError, ValueError):
        return None


def processar_carteira(arquivo, nome_arquivo: str) -> dict:
    """Importa data credenciamento da Carteira PP (aba Planilha1)."""
    df = ler_planilha(arquivo, nome_arquivo, sheet_name="Planilha1")
    col_pdv = resolver_coluna(df, ["NM_PARCEIRO_2", "NM_PARCEIRO", "PDV", "PARCEIRO"])
    col_cred = resolver_coluna(df, ["DT_CREDENC", "DATA_CREDENCIAMENTO", "DT_CREDENCIAMENTO"])
    col_aging = resolver_coluna(df, ["CLASS_AGING", "CLASSIFICACAO", "AGING"])
    if not col_pdv or not col_cred:
        raise ValueError(
            "A carteira precisa das colunas NM_PARCEIRO_2 e DT_CREDENC. "
            f"Colunas: {list(df.columns)}"
        )

    indice = indice_parceiros()
    atualizados = 0
    sem_cadastro: list[str] = []
    divergencias: list[str] = []
    ignorados = 0

    for _, row in df.iterrows():
        nome = texto(row.get(col_pdv))
        if not nome:
            continue
        cred = _parse_data(row.get(col_cred))
        if cred is None:
            ignorados += 1
            continue
        pid = resolver_parceiro_id(nome, indice)
        if pid is None:
            sem_cadastro.append(nome)
            continue
        parceiro = Parceiro.objects.get(pk=pid)
        if parceiro.data_credenciamento != cred:
            parceiro.data_credenciamento = cred
            parceiro.save(update_fields=["data_credenciamento", "atualizado_em"])
            atualizados += 1
        if col_aging:
            aging = texto(row.get(col_aging)).upper()
            if aging and cred.year > 1901:
                esperado = "BASE REGULAR" if _eh_regular(cred) else "INICIANTE"
                if aging not in (esperado, esperado.replace("BASE ", "")):
                    divergencias.append(f"{nome}: planilha {aging}, cadastro {esperado}")

    return {
        "atualizados": atualizados,
        "sem_cadastro": sem_cadastro[:30],
        "sem_cadastro_n": len(sem_cadastro),
        "divergencias": divergencias[:15],
        "divergencias_n": len(divergencias),
        "ignorados": ignorados,
    }


def _eh_regular(cred: date, ref: date | None = None) -> bool:
    from dateutil.relativedelta import relativedelta

    if cred.year <= 1901:
        return True
    ref = ref or date.today()
    return ref > cred + relativedelta(months=6)
