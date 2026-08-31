from __future__ import annotations

import pandas as pd

from ..colunas_relatorio import normalizar_fpd
from ..excel import ler_planilha, resolver_coluna
from ..fpd_format import dataframe_para_base, mes_para_yyyymm
from ..models import LoteImportacao, RelatorioFPD
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje


def _status_aberta(valor) -> bool:
    txt = str(valor or "").strip().lower()
    if not txt:
        return False
    return txt in {"aberta", "open", "aguardando_arrecadacao"} or "abert" in txt or "aguardando" in txt


def _status_paga(valor) -> bool:
    txt = str(valor or "").strip().lower()
    if not txt:
        return False
    return txt.startswith("paga") or txt in {"fechada", "closed"}


def _normalizar_faixa(valor) -> str | None:
    txt = str(valor or "").strip().lower().replace("dias", "").replace("dia", "").replace(" ", "")
    if not txt:
        return None
    if txt in {"0a15", "10a15"}:
        return "10 a 15 Dias"
    if txt == "15a30":
        return "15 a 30 Dias"
    if txt == "30a45":
        return "30 a 45 Dias"
    if txt == "45a55":
        return "45 a 55 Dias"
    if txt == "55a60":
        return "55 a 60 Dias"
    if txt in {">60", ">=61", ">=a61", "maiorque60"}:
        return ">= a 61 Dias"
    return None


def _parse_periodo(valor):
    if pd.isna(valor):
        return None
    if isinstance(valor, pd.Period):
        return valor.asfreq("M")
    if isinstance(valor, pd.Timestamp):
        return valor.to_period("M")
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            n = int(valor)
        except (OverflowError, ValueError):
            n = None
        else:
            if 199001 <= n <= 209912:
                ano, mes = divmod(n, 100)
                if 1 <= mes <= 12:
                    return pd.Period(year=ano, month=mes, freq="M")
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].replace("-", "").isdigit():
        texto = texto[:-2]
    if not texto:
        return None
    if texto.isdigit() and len(texto) == 6:
        try:
            return pd.Period(f"{int(texto[:4])}-{int(texto[4:6]):02d}", freq="M")
        except Exception:
            return None
    if "/" in texto:
        try:
            a, b = texto.split("/", 1)
            if len(a) == 4:
                return pd.Period(f"{int(a)}-{int(b):02d}", freq="M")
            return pd.Period(f"{int(b)}-{int(a):02d}", freq="M")
        except Exception:
            return None
    ts = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return None
    return ts.to_period("M")


def _meses_janela(data_base=None):
    if data_base is None:
        data_base = pd.Timestamp(hoje())
    atual = pd.Period(data_base, freq="M")
    return {atual - 2, atual - 1, atual}


def _fmt_mes(valor) -> str:
    periodo = _parse_periodo(valor)
    if periodo is None:
        return str(valor)
    meses = (
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    )
    return f"{meses[periodo.month - 1]}/{periodo.year}"


def processar_fpd(arquivo, nome_arquivo: str, lote: LoteImportacao) -> dict:
    df = normalizar_fpd(ler_planilha(arquivo, nome_arquivo))
    col_pdv = resolver_coluna(df, ["APELIDO", "nm_pdv_rel", "NM_PDV_REL", "REDE", "DESC_APELIDO"])
    col_ref = resolver_coluna(df, ["REF_VENCTO", "MES_VENC", "MES_VENCIMENTO"])
    col_sit = resolver_coluna(df, ["SITUACAO_FATURA_MENSAL", "DS_SIT_FATURA", "DS_STATUS_FATURA"])
    col_faixa = resolver_coluna(df, ["FAIXA"])
    col_ind = resolver_coluna(df, ["INDICADOR"])
    col_rede = resolver_coluna(df, ["cd_rede", "CD_REDE", "cd_sap_original", "CD_SAP_ORIGINAL"])
    faltantes = []
    if not col_pdv:
        faltantes.append("APELIDO/nm_pdv_rel")
    if not col_ref:
        faltantes.append("REF_VENCTO/MES_VENC")
    if not col_sit:
        faltantes.append("SITUACAO_FATURA")
    if not col_faixa:
        faltantes.append("FAIXA")
    if faltantes:
        raise ValueError("Colunas FPD ausentes: " + ", ".join(faltantes))

    if col_ind:
        df = df[df[col_ind].fillna("").astype(str).str.strip().str.upper() == "FPD"].copy()

    meses_validos = _meses_janela()
    periodos = df[col_ref].apply(_parse_periodo)
    df = df[periodos.isin(meses_validos)].copy()
    if df.empty:
        return {"pdvs": 0, "aviso": "Nenhuma linha na janela de 3 meses."}

    indice = indice_parceiros()
    RelatorioFPD.objects.filter(lote=lote).delete()
    gerados = 0
    sem_parceiro = []

    for apelido in df[col_pdv].dropna().unique():
        parceiro_id = resolver_parceiro_id(str(apelido), indice)
        if not parceiro_id:
            sem_parceiro.append(str(apelido))
            continue
        RelatorioFPD.objects.filter(parceiro_id=parceiro_id).delete()
        df_pdv = df[df[col_pdv] == apelido].copy()
        mensagem = f"📊 *Relatório FPD - {apelido}*\n_(Faturas Por Dia)_\n\n"
        meses_ref = sorted(df_pdv[col_ref].dropna().unique(), key=lambda x: str(x))
        total_fat = total_ab = total_pg = 0
        detalhe_meses = []
        codigo_rede = ""
        if col_rede and not df_pdv[col_rede].dropna().empty:
            codigo_rede = str(df_pdv[col_rede].dropna().iloc[0]).strip()
            if codigo_rede.endswith(".0") and codigo_rede[:-2].isdigit():
                codigo_rede = codigo_rede[:-2]
        for mes_ref in meses_ref:
            bloco = df_pdv[df_pdv[col_ref] == mes_ref]
            status = bloco[col_sit].fillna("").astype(str)
            total = len(bloco)
            pagas = int(status.apply(_status_paga).sum())
            abertas = int(status.apply(_status_aberta).sum())
            perc = (abertas / total * 100) if total else 0
            total_fat += total
            total_ab += abertas
            total_pg += pagas
            faixas = {
                "10 a 15 Dias": 0,
                "15 a 30 Dias": 0,
                "30 a 45 Dias": 0,
                "45 a 55 Dias": 0,
                "55 a 60 Dias": 0,
                ">= a 61 Dias": 0,
            }
            if abertas:
                abertos = bloco[status.apply(_status_aberta)]
                contagem = abertos[col_faixa].apply(_normalizar_faixa).dropna().value_counts().to_dict()
                for chave in faixas:
                    faixas[chave] = int(contagem.get(chave, 0))
            mensagem += f"🗓️ *Mês fatura: {_fmt_mes(mes_ref)}*\n"
            mensagem += f"   - Total: *{total}*\n"
            mensagem += f"   - Pagas: *{pagas}*\n"
            mensagem += f"   - Em aberto: *{abertas}*\n"
            mensagem += f"   - % em aberto: *{perc:.2f}%*\n"
            if abertas:
                mensagem += "   *Abertas por faixa:*\n"
                mensagem += f"     - 10 a 15: {faixas['10 a 15 Dias']}\n"
                mensagem += f"     - 15 a 30: {faixas['15 a 30 Dias']}\n"
                mensagem += f"     - 30 a 45: {faixas['30 a 45 Dias']}\n"
                mensagem += f"     - 45 a 55: {faixas['45 a 55 Dias']}\n"
                mensagem += f"     - 55 a 60: {faixas['55 a 60 Dias']}\n"
                mensagem += f"     - >60: {faixas['>= a 61 Dias']}\n"
            mensagem += "\n"
            detalhe_meses.append(
                {
                    "mes": _fmt_mes(mes_ref),
                    "mes_yyyymm": mes_para_yyyymm(mes_ref),
                    "total": total,
                    "pagas": pagas,
                    "abertas": abertas,
                    "perc_aberto": round(perc, 2),
                    "faixas": faixas,
                }
            )
        perc_pdv = (total_ab / total_fat * 100) if total_fat else 0
        mensagem += (
            f"📌 *FPD consolidado:* {perc_pdv:.2f}% (Abertas: {total_ab} / Total: {total_fat})"
        )
        RelatorioFPD.objects.create(
            lote=lote,
            parceiro_id=parceiro_id,
            pdv_nome=str(apelido),
            percentual=perc_pdv,
            total_faturas=total_fat,
            total_abertas=total_ab,
            mensagem=mensagem.strip(),
            detalhes={
                "meses": detalhe_meses,
                "codigo_rede": codigo_rede,
                "total_pagas": total_pg,
                "base_colunas": list(df_pdv.columns),
                "base": dataframe_para_base(df_pdv),
            },
        )
        gerados += 1

    return {"pdvs": gerados, "sem_parceiro": sem_parceiro}
