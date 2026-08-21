from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from django.core.files.base import ContentFile

from ..models import LoteImportacao, RelatorioVendaIndevida
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje

COL_ANOMES = "ANOMES_ABERTURA"
COL_MOTIVO = "MOTIVO_CRV"
COL_SUBMOTIVO = "SUBMOTIVO_CRV"
COL_REDE = "REDE"

COLUNAS_ANEXO = [
    "NUMERO_PEDIDO",
    "nr_ordem",
    "nm_origem",
    "BOV_PEDIDO",
    "fg_venda_valida",
    COL_ANOMES,
    "dt_venda_particao",
    "DS_PGTO",
    COL_REDE,
    "cd_sap_original",
    "cd_tr_vdd_original",
    "st_contrato",
    "nm_seg",
    COL_MOTIVO,
    COL_SUBMOTIVO,
    "DATA_DIVULG_CRV",
    "DATA_CANC_CRV",
    "nm_diretoria",
    "nm_regional",
    "cd_rede",
    "gp_canal",
    "GERENCIA",
    "nm_gc",
    "ST_SAP",
    "GERENCIA_T",
    "DESCRICAO",
]

_MESES = ("", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _normalizar_anomes(valor: Any) -> str:
    if pd.isna(valor):
        return ""
    s = str(valor).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else (s or "")


def _rotulo_anomes(codigo: str) -> str:
    if len(codigo) == 6 and codigo.isdigit():
        mi = int(codigo[4:6])
        if 1 <= mi <= 12:
            return f"{_MESES[mi]}/{codigo[:4]}"
    return codigo or "(sem período)"


def _barra(qtd: int, max_qtd: int, largura: int = 10) -> str:
    if max_qtd <= 0 or qtd <= 0:
        return "░" * largura
    cheia = min(largura, max(1, int(round(largura * qtd / max_qtd))))
    return "█" * cheia + "░" * (largura - cheia)


def _serie_contagem(serie: pd.Series, rotulo_vazio: str = "(em branco)") -> pd.Series:
    s = serie.fillna(rotulo_vazio).astype(str).str.strip().replace("", rotulo_vazio)
    return s.value_counts()


def montar_mensagem_vi(
    df: pd.DataFrame,
    *,
    titulo_linha: str,
    data_referencia: date | None = None,
    limite_submotivos: int = 22,
) -> str:
    data_ref = (data_referencia or date.today()).strftime("%d/%m/%Y")
    n = len(df)
    linhas = [
        "🚨 *VENDA INDEVIDA E ERRADA*",
        f"📅 *Referência:* {data_ref}",
        titulo_linha,
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 *Total de registros na base deste recorte:* *{n}*",
        "",
    ]
    if n == 0:
        linhas.append("_Nenhum registro neste recorte._")
        return "\n".join(linhas)

    am = df[COL_ANOMES].map(_normalizar_anomes)
    am = am[am != ""]
    if am.empty:
        linhas.extend(["📆 *ANOMES_ABERTURA*", "   _(sem valores válidos)_", ""])
    else:
        contagem = am.value_counts()
        chaves = sorted(contagem.index)
        total = int(contagem.sum())
        max_c = int(contagem.max())
        linhas.append("📆 *ANOMES_ABERTURA* _(por ano/mês)_")
        for cod in chaves:
            q = int(contagem[cod])
            pct = (100.0 * q / total) if total else 0.0
            linhas.append(f"   ▸ *{_rotulo_anomes(cod)}* `({cod})`")
            linhas.append(f"      {_barra(q, max_c, 10)}  *{q}*  ({pct:.1f}%)")
        linhas.append("")

    motivos = _serie_contagem(df[COL_MOTIVO])
    max_m = int(motivos.max()) if len(motivos) else 0
    linhas.append("🏷️ *MOTIVO_CRV* _(contagem)_")
    for nome, q in motivos.items():
        linhas.append(f"   ▸ *{nome}*")
        linhas.append(f"      {_barra(int(q), max_m, 12)}  *{int(q)}*")
    linhas.append("")

    subs = _serie_contagem(df[COL_SUBMOTIVO])
    max_s = int(subs.max()) if len(subs) else 0
    linhas.append("🔖 *SUBMOTIVO_CRV* _(contagem)_")
    for i, (nome, q) in enumerate(subs.items()):
        if i >= limite_submotivos:
            linhas.append(f"   _… e mais {len(subs) - i} submotivo(s). Veja o anexo._")
            break
        linhas.append(f"   ▸ *{nome}*")
        linhas.append(f"      {_barra(int(q), max_s, 12)}  *{int(q)}*")
    linhas.append("")

    top_m = motivos.index[0] if len(motivos) else "—"
    top_s = subs.index[0] if len(subs) else "—"
    linhas.extend(
        [
            "⚡ *Leitura rápida*",
            f"   • Motivo líder: *{top_m}*",
            f"   • Submotivo líder: *{top_s}*",
            "",
            "_Anexo: detalhamento das linhas deste recorte._",
        ]
    )
    return "\n".join(linhas)


def _df_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BASE_VI")
    return buf.getvalue()


def _salvar(
    *,
    lote: LoteImportacao,
    parceiro_id: int | None,
    pdv_nome: str,
    total: int,
    consolidado: bool,
    data_ref: date,
    mensagem: str,
    df_anexo: pd.DataFrame,
    nome_arquivo: str,
) -> RelatorioVendaIndevida:
    rel = RelatorioVendaIndevida(
        lote=lote,
        parceiro_id=parceiro_id,
        pdv_nome=pdv_nome,
        total=total,
        consolidado=consolidado,
        data_referencia=data_ref,
        mensagem=mensagem,
    )
    rel.arquivo.save(nome_arquivo, ContentFile(_df_bytes(df_anexo)), save=True)
    return rel


def processar_venda_indevida(
    arquivo,
    nome: str,
    lote: LoteImportacao,
    *,
    nome_planilha: str = "BASE_VI",
    data_referencia: date | None = None,
) -> dict:
    data_ref = data_referencia or hoje()
    caminho = None
    try:
        conteudo = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
        if hasattr(arquivo, "seek"):
            arquivo.seek(0)
        sufixo = Path(nome).suffix.lower() or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False) as tmp:
            tmp.write(conteudo)
            caminho = Path(tmp.name)
        engine = "pyxlsb" if sufixo == ".xlsb" else None
        try:
            df = pd.read_excel(caminho, sheet_name=nome_planilha, engine=engine)
        except ValueError as exc:
            # fallback: primeira aba
            if "Worksheet" in str(exc) or "does not exist" in str(exc).lower():
                df = pd.read_excel(caminho, engine=engine)
            else:
                raise
    except Exception as exc:
        raise ValueError(f"Erro ao ler arquivo VI: {exc}") from exc
    finally:
        if caminho is not None:
            try:
                caminho.unlink(missing_ok=True)
            except PermissionError:
                pass

    faltando = [c for c in (COL_ANOMES, COL_MOTIVO, COL_SUBMOTIVO) if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(faltando)}")
    if df.empty:
        raise ValueError("A planilha não contém linhas de dados.")

    cols = [c for c in COLUNAS_ANEXO if c in df.columns] or list(df.columns)
    stamp = data_ref.isoformat()

    msg_cons = montar_mensagem_vi(
        df, titulo_linha="🌐 *Visão consolidada (todos os PDVs)*", data_referencia=data_ref
    )
    _salvar(
        lote=lote,
        parceiro_id=None,
        pdv_nome="",
        total=len(df),
        consolidado=True,
        data_ref=data_ref,
        mensagem=msg_cons,
        df_anexo=df[cols],
        nome_arquivo=f"VI_{stamp}_CONSOLIDADO.xlsx",
    )

    por_pdv = 0
    sem_parceiro = 0
    if COL_REDE in df.columns:
        serie = df[COL_REDE].fillna("(sem PDV)").astype(str).str.strip().replace("", "(sem PDV)")
        indice = indice_parceiros()
        for pdv in serie.value_counts().index.tolist():
            sub = df.loc[serie == pdv].copy()
            tag = str(pdv).strip().replace("/", "-")[:80]
            msg = montar_mensagem_vi(sub, titulo_linha=f"🏬 *PDV:* {pdv}", data_referencia=data_ref)
            parceiro_id = resolver_parceiro_id(str(pdv), indice)
            if parceiro_id is None:
                sem_parceiro += 1
            _salvar(
                lote=lote,
                parceiro_id=parceiro_id,
                pdv_nome=str(pdv),
                total=len(sub),
                consolidado=False,
                data_ref=data_ref,
                mensagem=msg,
                df_anexo=sub[cols],
                nome_arquivo=f"VI_{stamp}_{tag}.xlsx",
            )
            por_pdv += 1

    return {
        "pdvs": por_pdv,
        "sem_parceiro": sem_parceiro,
        "total_linhas": int(len(df)),
        "arquivo": nome,
        "data_referencia": stamp,
    }
