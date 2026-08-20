from __future__ import annotations

from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ..excel import ler_planilha, resolver_coluna
from ..models import GrossMensal, HistoricoChurn
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import label_anomes
from tickets.models import Parceiro


def _to_int(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_bool_mei(valor) -> bool:
    return str(valor or "").strip().lower() in {"1", "true", "t", "sim", "s", "mei"}


def formatar_moeda(valor) -> str:
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def processar_churn(arquivo, nome_arquivo: str) -> dict:
    df = ler_planilha(arquivo, nome_arquivo)
    col_pdv = resolver_coluna(df, ["DESC_APELIDO", "nm_pdv_rel"])
    col_anomes = resolver_coluna(df, ["ANOMES_GROSS"])
    col_tp = resolver_coluna(df, ["TP_RETIRADA"])
    col_mei = resolver_coluna(df, ["FLG_MEI"])
    col_seg = resolver_coluna(df, ["NM_SEG", "nm_seg"])
    col_motivo = resolver_coluna(df, ["DS_MOTIVO_RETIRADA"])
    if not col_pdv or not col_anomes:
        raise ValueError("Colunas obrigatórias: DESC_APELIDO/nm_pdv_rel e ANOMES_GROSS.")

    contagem = df.groupby([col_pdv, col_anomes]).size().reset_index(name="total_churn")
    indice = indice_parceiros()
    mapa_gross = {(g.parceiro_id, g.anomes): g.gross for g in GrossMensal.objects.all()}

    hoje_dt = timezone.localtime()
    inicio = hoje_dt - relativedelta(months=5)
    janela = [int((inicio + relativedelta(months=i)).strftime("%Y%m")) for i in range(6)]
    data_analise = timezone.localdate()

    ultima = HistoricoChurn.objects.order_by("-data_analise").first()
    if ultima:
        HistoricoChurn.objects.filter(data_analise=ultima.data_analise).delete()

    linhas = 0
    mensagens_pdv = 0
    sem_parceiro = set()

    for apelido in sorted({str(x) for x in df[col_pdv].dropna().unique()}):
        parceiro_id = resolver_parceiro_id(apelido, indice)
        if not parceiro_id:
            sem_parceiro.add(apelido)
            continue
        parceiro = Parceiro.objects.get(pk=parceiro_id)
        churn_pdv = contagem[contagem[col_pdv] == apelido]
        mensagem = f"*Relatório de Churn - {parceiro.nome}*\n\nAnálise de cancelamentos por safra:\n\n"
        bonus_total = 0
        teve = False
        linhas_hist = []

        for anomes in sorted(janela, reverse=True):
            gross = _to_int(mapa_gross.get((parceiro_id, anomes), 0))
            churn_linhas = churn_pdv[churn_pdv[col_anomes] == anomes]
            if churn_linhas.empty:
                churn_linhas = churn_pdv[churn_pdv[col_anomes].astype(str) == str(anomes)]
            churn = _to_int(churn_linhas["total_churn"].sum() if not churn_linhas.empty else 0)
            df_safra = df[(df[col_pdv] == apelido) & (df[col_anomes].astype(str) == str(anomes))].copy()
            if gross == 0 and churn == 0:
                continue
            teve = True
            taxa = _to_float((churn / gross * 100) if gross > 0 else 0)
            rem = max(0, gross - churn)
            bonus = rem * 150
            bonus_total += bonus
            mensagem += f"*Safra:* {label_anomes(anomes)}\n"
            mensagem += f"   - Instalados (Gross): *{gross}*\n"
            mensagem += f"   - Cancelados (Churn): *{churn}*\n"
            mensagem += f"   - Taxa: *{taxa:.2f}%*\n"
            if col_tp and not df_safra.empty:
                qtd_vol = int(
                    df_safra[col_tp].fillna("").astype(str).str.strip().str.upper().eq("VOL").sum()
                )
                mensagem += f"   - VOL: *{qtd_vol}* ({(qtd_vol / gross * 100) if gross else 0:.2f}% do gross)\n"
            if col_mei and not df_safra.empty:
                mei_mask = df_safra[col_mei].apply(_to_bool_mei)
                qtd_mei = int(mei_mask.sum())
                mensagem += f"   - MEI: *{qtd_mei}* ({(qtd_mei / gross * 100) if gross else 0:.2f}% do gross)\n"
                if col_seg:
                    emp = df_safra[col_seg].fillna("").astype(str).str.strip().str.lower().eq("empresarial")
                    qtd_mei_emp = int((mei_mask & emp).sum())
                    mensagem += (
                        f"   - MEI empresarial: *{qtd_mei_emp}* "
                        f"({(qtd_mei_emp / gross * 100) if gross else 0:.2f}% do gross)\n"
                    )
            if col_motivo and churn > 0 and not df_safra.empty:
                top = (
                    df_safra[col_motivo]
                    .fillna("Motivo não informado")
                    .astype(str)
                    .str.strip()
                    .replace("", "Motivo não informado")
                    .value_counts()
                    .head(4)
                )
                if not top.empty:
                    mensagem += "   - Top motivos:\n"
                    for motivo, qtd in top.items():
                        mensagem += f"      · {motivo}: {(qtd / churn * 100):.2f}% ({qtd})\n"
            mensagem += f"   - Bônus potencial [{rem}] x [R$ 150,00]: {formatar_moeda(bonus)}\n\n"
            linhas_hist.append(
                HistoricoChurn(
                    data_analise=data_analise,
                    parceiro=parceiro,
                    pdv_nome=parceiro.nome,
                    anomes_gross=anomes,
                    gross=gross,
                    churn=churn,
                    taxa_churn=taxa,
                    remanescentes=rem,
                    bonus_m10=bonus,
                    mensagem="",
                )
            )

        if teve:
            mensagem += f"*Bônus potencial total:* {formatar_moeda(bonus_total)}\n"
            mensagem += "_Valores simulados. Elegibilidade exige adimplência e sem downgrade._"
            if linhas_hist:
                linhas_hist[0].mensagem = mensagem
            HistoricoChurn.objects.bulk_create(linhas_hist)
            linhas += len(linhas_hist)
            mensagens_pdv += 1

    return {
        "linhas": linhas,
        "pdvs": mensagens_pdv,
        "sem_parceiro": sorted(sem_parceiro),
    }
