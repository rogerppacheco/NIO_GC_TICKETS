from __future__ import annotations

import pandas as pd

from ..colunas_relatorio import normalizar_fpd
from ..excel import ler_planilha, resolver_coluna
from ..fpd_format import dataframe_para_base, mes_para_yyyymm
from ..models import LoteImportacao, RelatorioFPD, RelatorioFPDCidade
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje

INDICADORES = ("FPD", "SPD", "TPD")
SEGMENTOS = ("todos", "varejo", "empresarial")

ROTULO_INDICADOR = {
    "FPD": "Primeira fatura",
    "SPD": "Segunda fatura",
    "TPD": "Terceira fatura",
}
ROTULO_SEGMENTO = {
    "todos": "Todos",
    "varejo": "Varejo",
    "empresarial": "Empresarial",
}

_COL_IND = "_ind"
_COL_SEG = "_seg"


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


def _normalizar_indicador(valor) -> str | None:
    txt = str(valor or "").strip().upper()
    if txt in INDICADORES:
        return txt
    return None


def _segmento_linha(valor) -> str | None:
    txt = str(valor or "").strip().casefold()
    if not txt or txt in {"nan", "none", "-", "nat"}:
        return None
    if "empres" in txt or txt in {"b2b", "pj", "pessoa jurídica", "pessoa juridica"}:
        return "empresarial"
    return "varejo"


def _subtitulo(indicador: str, segmento: str) -> str:
    base = ROTULO_INDICADOR.get(indicador, indicador)
    if segmento != "todos":
        return f"{base} · {ROTULO_SEGMENTO.get(segmento, segmento)}"
    return base


def _filtrar_segmento(df: pd.DataFrame, segmento: str) -> pd.DataFrame:
    if segmento == "todos":
        return df
    if _COL_SEG not in df.columns:
        return df.iloc[0:0]
    return df[df[_COL_SEG] == segmento]


def _codigo_rede(df_pdv: pd.DataFrame, col_rede: str | None) -> str:
    if not col_rede or df_pdv[col_rede].dropna().empty:
        return ""
    codigo = str(df_pdv[col_rede].dropna().iloc[0]).strip()
    if codigo.endswith(".0") and codigo[:-2].isdigit():
        return codigo[:-2]
    return codigo


def _base_sem_aux(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[_COL_IND, _COL_SEG], errors="ignore")


def _criar_relatorio(
    *,
    lote: LoteImportacao,
    parceiro_id: int,
    apelido: str,
    indicador: str,
    segmento: str,
    df_pdv: pd.DataFrame,
    col_ref: str,
    col_sit: str,
    col_faixa: str,
    col_rede: str | None,
) -> None:
    subtitulo = _subtitulo(indicador, segmento)
    mensagem = f"📊 *Relatório {indicador} - {apelido}*\n_({subtitulo})_\n\n"
    meses_ref = sorted(df_pdv[col_ref].dropna().unique(), key=lambda x: str(x))
    total_fat = total_ab = total_pg = 0
    detalhe_meses = []
    codigo_rede = _codigo_rede(df_pdv, col_rede)
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
    consolidado = f"{indicador} consolidado"
    if segmento != "todos":
        consolidado += f" · {ROTULO_SEGMENTO[segmento]}"
    mensagem += (
        f"📌 *{consolidado}:* {perc_pdv:.2f}% (Abertas: {total_ab} / Total: {total_fat})"
    )
    base = _base_sem_aux(df_pdv)
    RelatorioFPD.objects.create(
        lote=lote,
        parceiro_id=parceiro_id,
        pdv_nome=str(apelido),
        indicador=indicador,
        segmento=segmento,
        percentual=perc_pdv,
        total_faturas=total_fat,
        total_abertas=total_ab,
        mensagem=mensagem.strip(),
        detalhes={
            "meses": detalhe_meses,
            "codigo_rede": codigo_rede,
            "total_pagas": total_pg,
            "indicador": indicador,
            "segmento": segmento,
            "base_colunas": list(base.columns),
            "base": dataframe_para_base(base),
        },
    )


def processar_fpd(arquivo, nome_arquivo: str, lote: LoteImportacao) -> dict:
    df = normalizar_fpd(ler_planilha(arquivo, nome_arquivo))
    col_pdv = resolver_coluna(df, ["APELIDO", "nm_pdv_rel", "NM_PDV_REL", "REDE", "DESC_APELIDO"])
    col_ref = resolver_coluna(df, ["REF_VENCTO", "MES_VENC", "MES_VENCIMENTO"])
    col_sit = resolver_coluna(df, ["SITUACAO_FATURA_MENSAL", "DS_SIT_FATURA", "DS_STATUS_FATURA"])
    col_faixa = resolver_coluna(df, ["FAIXA"])
    col_ind = resolver_coluna(df, ["INDICADOR"])
    col_seg = resolver_coluna(df, ["NM_SEG", "nm_seg", "NM_SEGMENTO", "SEGMENTO"])
    col_rede = resolver_coluna(df, ["cd_rede", "CD_REDE", "cd_sap_original", "CD_SAP_ORIGINAL"])
    col_cidade = resolver_coluna(df, [
        "LOCALIDADE", "NM_LOCALIDADE", "MUNICIPIO", "NM_MUNICIPIO", 
        "CIDADE", "MUNICÍPIO", "NM_MUNICIPIO_INSTALACAO", 
        "CIDADE_INSTALACAO", "PRACA", "PRAÇA", "NM_PRACA"
    ])
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
        df = df.copy()
        df[_COL_IND] = df[col_ind].map(_normalizar_indicador)
        df = df[df[_COL_IND].notna()].copy()
    else:
        df = df.copy()
        df[_COL_IND] = "FPD"

    if col_seg:
        df[_COL_SEG] = df[col_seg].map(_segmento_linha)
    else:
        df[_COL_SEG] = None

    meses_validos = _meses_janela()
    periodos = df[col_ref].apply(_parse_periodo)
    df = df[periodos.isin(meses_validos)].copy()
    if df.empty:
        return {"pdvs": 0, "relatorios": 0, "aviso": "Nenhuma linha na janela de 3 meses."}

    indice = indice_parceiros()
    RelatorioFPD.objects.filter(lote=lote).delete()
    gerados_pdvs = 0
    gerados = 0
    sem_parceiro = []

    for apelido in df[col_pdv].dropna().unique():
        parceiro_id = resolver_parceiro_id(str(apelido), indice)
        if not parceiro_id:
            sem_parceiro.append(str(apelido))
            continue
        RelatorioFPD.objects.filter(parceiro_id=parceiro_id).delete()
        df_pdv = df[df[col_pdv] == apelido]
        criou = False
        for indicador in INDICADORES:
            df_ind = df_pdv[df_pdv[_COL_IND] == indicador]
            if df_ind.empty:
                continue
            segmentos = SEGMENTOS if col_seg else ("todos",)
            for segmento in segmentos:
                bloco = _filtrar_segmento(df_ind, segmento)
                if bloco.empty:
                    continue
                _criar_relatorio(
                    lote=lote,
                    parceiro_id=parceiro_id,
                    apelido=str(apelido),
                    indicador=indicador,
                    segmento=segmento,
                    df_pdv=bloco,
                    col_ref=col_ref,
                    col_sit=col_sit,
                    col_faixa=col_faixa,
                    col_rede=col_rede,
                )
                gerados += 1
                criou = True
        if criou:
            gerados_pdvs += 1

    gerados_cidades = 0
    if col_cidade and col_rede:
        RelatorioFPDCidade.objects.filter(lote=lote).delete()
        df_cid_group = df.dropna(subset=[col_cidade, col_rede]).groupby([col_cidade, col_rede])
        for (cidade_nome, rede_nome), df_cid in df_cid_group:
            nome_limpo = str(cidade_nome).strip()
            if not nome_limpo:
                continue
            
            parceiro_id = resolver_parceiro_id(rede_nome, indice)
            
            criou = False
            for indicador in INDICADORES:
                df_ind = df_cid[df_cid[_COL_IND] == indicador]
                if df_ind.empty:
                    continue
                segmentos = SEGMENTOS if col_seg else ("todos",)
                for segmento in segmentos:
                    bloco = _filtrar_segmento(df_ind, segmento)
                    if bloco.empty:
                        continue
                        
                    total = len(bloco)
                    status = bloco[col_sit].fillna("").astype(str)
                    abertas = int(status.apply(_status_aberta).sum())
                    perc = (abertas / total * 100) if total else 0
                    
                    RelatorioFPDCidade.objects.create(
                        lote=lote,
                        parceiro_id=parceiro_id,
                        cidade=nome_limpo,
                        indicador=indicador,
                        segmento=segmento,
                        percentual=perc,
                        total_faturas=total,
                        total_abertas=abertas,
                    )
                    criou = True
            if criou:
                gerados_cidades += 1

    return {"pdvs": gerados_pdvs, "relatorios": gerados, "cidades": gerados_cidades, "sem_parceiro": sem_parceiro}


def reprocessar_cidades_lote(lote: LoteImportacao) -> int:
    from ..fpd_format import base_para_dataframe
    
    relatorios = lote.relatorios_fpd.all()
    if not relatorios.exists():
        return 0
        
    dfs = []
    for r in relatorios:
        if r.segmento == "todos" and "base" in r.detalhes:
            df_part = base_para_dataframe(r.detalhes)
            df_part["_parceiro_id"] = r.parceiro_id
            dfs.append(df_part)
            
    if not dfs:
        return 0
        
    df = pd.concat(dfs, ignore_index=True)
    
    col_sit = resolver_coluna(df, ["SITUACAO_FATURA_MENSAL", "DS_SIT_FATURA", "DS_STATUS_FATURA"])
    col_cidade = resolver_coluna(df, [
        "LOCALIDADE", "NM_LOCALIDADE", "MUNICIPIO", "NM_MUNICIPIO", 
        "CIDADE", "MUNICÍPIO", "NM_MUNICIPIO_INSTALACAO", 
        "CIDADE_INSTALACAO", "PRACA", "PRAÇA", "NM_PRACA"
    ])
    col_ind = resolver_coluna(df, ["INDICADOR"])
    col_seg = resolver_coluna(df, ["NM_SEG", "nm_seg", "NM_SEGMENTO", "SEGMENTO"])
    col_ref = resolver_coluna(df, ["REF_VENCTO", "MES_VENC", "MES_VENCIMENTO"])
    
    if not col_cidade or not col_sit or not col_ref:
        return 0
    
    df["_mes_venc"] = df[col_ref].apply(lambda x: mes_para_yyyymm(str(x)))
        
    if col_ind:
        df[_COL_IND] = df[col_ind].map(_normalizar_indicador)
    else:
        df[_COL_IND] = "FPD"

    if col_seg:
        df[_COL_SEG] = df[col_seg].map(_segmento_linha)
    else:
        df[_COL_SEG] = None
        
    RelatorioFPDCidade.objects.filter(lote=lote).delete()
    gerados_cidades = 0
    
    df_cid_group = df.dropna(subset=[col_cidade, "_parceiro_id", "_mes_venc"]).groupby([col_cidade, "_parceiro_id", "_mes_venc"])
    
    for (cidade_nome, parceiro_id, mes_venc), df_cid in df_cid_group:
        nome_limpo = str(cidade_nome).strip()
        if not nome_limpo:
            continue
        
        criou = False
        for indicador in INDICADORES:
            df_ind = df_cid[df_cid[_COL_IND] == indicador]
            if df_ind.empty:
                continue
            segmentos = SEGMENTOS if col_seg else ("todos",)
            for segmento in segmentos:
                bloco = _filtrar_segmento(df_ind, segmento)
                if bloco.empty:
                    continue
                    
                total = len(bloco)
                status = bloco[col_sit].fillna("").astype(str)
                abertas = int(status.apply(_status_aberta).sum())
                perc = (abertas / total * 100) if total else 0
                
                RelatorioFPDCidade.objects.create(
                    lote=lote,
                    parceiro_id=parceiro_id,
                    cidade=nome_limpo,
                    mes=mes_venc,
                    indicador=indicador,
                    segmento=segmento,
                    percentual=perc,
                    total_faturas=total,
                    total_abertas=abertas,
                )
                criou = True
        if criou:
            gerados_cidades += 1
            
    return gerados_cidades
