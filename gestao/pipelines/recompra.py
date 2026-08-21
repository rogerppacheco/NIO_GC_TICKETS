from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from django.core.files.base import ContentFile

from ..models import LoteImportacao, RelatorioRecompra
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje

COL_SAFRA = "ds_anomes"
COL_RESULTADO = "resultado"
COL_REDE = "REDE"

COLUNAS_ANEXO = [
    COL_SAFRA,
    "dt_venda_particao",
    "dt_encerramento",
    "nr_ordem",
    "st_ordem",
    "nm_seg",
    "sg_uf",
    "cd_sap_pdv",
    "cd_tr_vdd",
    "nm_municipio",
    "nm_bairro",
    COL_RESULTADO,
    "dt_inicio_ativo",
    "nm_diretoria",
    "nm_regional",
    "cd_rede",
    "gp_canal",
    "nm_pdv_rel",
    "GERENCIA",
    "nm_gc",
    COL_REDE,
]

_MESES = ("", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _normalizar_safra(valor: Any) -> str:
    if pd.isna(valor):
        return ""
    s = str(valor).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else (s or "")


def _rotulo_safra(codigo: str) -> str:
    if len(codigo) == 6 and codigo.isdigit():
        mi = int(codigo[4:6])
        if 1 <= mi <= 12:
            return f"{_MESES[mi]}/{codigo[:4]}"
    return codigo or "(sem safra)"


def _barra(qtd: int, max_qtd: int, largura: int = 10) -> str:
    if max_qtd <= 0 or qtd <= 0:
        return "░" * largura
    cheia = min(largura, max(1, int(round(largura * qtd / max_qtd))))
    return "█" * cheia + "░" * (largura - cheia)


def _serie_contagem(serie: pd.Series, rotulo_vazio: str = "(em branco)") -> pd.Series:
    s = serie.fillna(rotulo_vazio).astype(str).str.strip().replace("", rotulo_vazio)
    return s.value_counts()


def montar_mensagem_recompra(
    df: pd.DataFrame,
    *,
    titulo_linha: str,
    data_referencia: date | None = None,
    limite_resultado: int = 30,
) -> str:
    data_ref = (data_referencia or date.today()).strftime("%d/%m/%Y")
    n = len(df)
    linhas = [
        "🔁 *RECOMPRA*",
        f"📅 *Referência:* {data_ref}",
        titulo_linha,
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 *Total de linhas neste recorte:* *{n}*",
        "",
    ]
    if n == 0:
        linhas.append("_Nenhum registro neste recorte._")
        return "\n".join(linhas)

    saf = df[COL_SAFRA].map(_normalizar_safra)
    saf = saf[saf != ""]
    contagem = pd.Series(dtype=int)
    chaves: list[str] = []
    if saf.empty:
        linhas.extend(["🌾 *Safra (ds_anomes)*", "   _(sem valores válidos)_", ""])
    else:
        contagem = saf.value_counts()
        chaves = sorted(contagem.index)
        total = int(contagem.sum())
        max_c = int(contagem.max())
        linhas.append("🌾 *Safra (ds_anomes)* _(volume por período)_")
        for cod in chaves:
            q = int(contagem[cod])
            pct = (100.0 * q / total) if total else 0.0
            linhas.append(f"   ▸ *{_rotulo_safra(cod)}* `({cod})`")
            linhas.append(f"      {_barra(q, max_c, 10)}  *{q}*  ({pct:.1f}%)")
        linhas.append("")

    res = _serie_contagem(df[COL_RESULTADO])
    max_r = int(res.max()) if len(res) else 0
    linhas.append("📋 *Resultado* _(contagem de cada valor distinto)_")
    for i, (nome, q) in enumerate(res.items()):
        if i >= limite_resultado:
            linhas.append(f"   _… e mais {len(res) - i} tipo(s) de resultado. Veja o anexo._")
            break
        linhas.append(f"   ▸ *{nome}*")
        linhas.append(f"      {_barra(int(q), max_r, 12)}  *{int(q)}*")
    linhas.append("")

    if chaves:
        linhas.append("🔀 *Resultado por safra* _(resumo)_")
        for cod in chaves:
            mask = df[COL_SAFRA].map(_normalizar_safra) == cod
            rsub = _serie_contagem(df.loc[mask, COL_RESULTADO])
            linhas.append(f"   *{_rotulo_safra(cod)}* `({cod})` — {int(rsub.sum())} caso(s)")
            for nome, q in rsub.head(8).items():
                linhas.append(f"      • {nome}: *{int(q)}*")
            if len(rsub) > 8:
                linhas.append(f"      _… +{len(rsub) - 8} resultado(s)_")
        linhas.append("")

    top_r = res.index[0] if len(res) else "—"
    saf_dom = contagem.index[0] if len(contagem) else "—"
    if saf_dom != "—":
        linhas.append(f"⚡ *Leitura rápida*")
        linhas.append(f"   • Safra com mais linhas: *{_rotulo_safra(str(saf_dom))}* (`{saf_dom}`)")
    else:
        linhas.append("⚡ *Leitura rápida*")
        linhas.append("   • Safra com mais linhas: —")
    linhas.extend(
        [
            f"   • Resultado mais frequente: *{top_r}*",
            "",
            "_Anexo: linhas detalhadas deste recorte._",
        ]
    )
    return "\n".join(linhas)


def _df_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BASE")
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
) -> RelatorioRecompra:
    rel = RelatorioRecompra(
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


def processar_recompra(
    arquivo,
    nome: str,
    lote: LoteImportacao,
    *,
    nome_planilha: str = "BASE",
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
            if "Worksheet" in str(exc) or "does not exist" in str(exc).lower():
                df = pd.read_excel(caminho, engine=engine)
            else:
                raise
    except Exception as exc:
        raise ValueError(f"Erro ao ler arquivo de recompra: {exc}") from exc
    finally:
        if caminho is not None:
            try:
                caminho.unlink(missing_ok=True)
            except PermissionError:
                pass

    faltando = [c for c in (COL_SAFRA, COL_RESULTADO) if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(faltando)}")
    if df.empty:
        raise ValueError("A planilha não contém linhas de dados.")

    cols = [c for c in COLUNAS_ANEXO if c in df.columns] or list(df.columns)
    stamp = data_ref.isoformat()

    msg_cons = montar_mensagem_recompra(
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
        nome_arquivo=f"Recompra_{stamp}_CONSOLIDADO.xlsx",
    )

    por_pdv = 0
    sem_parceiro = 0
    if COL_REDE in df.columns:
        serie = df[COL_REDE].fillna("(sem PDV)").astype(str).str.strip().replace("", "(sem PDV)")
        indice = indice_parceiros()
        for pdv in serie.value_counts().index.tolist():
            sub = df.loc[serie == pdv].copy()
            tag = str(pdv).strip().replace("/", "-")[:80]
            msg = montar_mensagem_recompra(
                sub, titulo_linha=f"🏬 *PDV:* {pdv}", data_referencia=data_ref
            )
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
                nome_arquivo=f"Recompra_{stamp}_{tag}.xlsx",
            )
            por_pdv += 1

    return {
        "pdvs": por_pdv,
        "sem_parceiro": sem_parceiro,
        "total_linhas": int(len(df)),
        "arquivo": nome,
        "data_referencia": stamp,
    }
