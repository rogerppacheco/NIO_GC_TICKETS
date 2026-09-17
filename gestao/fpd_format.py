from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import RelatorioFPD

FAIXAS_ORDEM = [
    "10 a 15 Dias",
    "15 a 30 Dias",
    "30 a 45 Dias",
    "45 a 55 Dias",
    "55 a 60 Dias",
    ">= a 61 Dias",
]

FAIXA_ROTULO = {
    "10 a 15 Dias": "10 a 15 Dias:",
    "15 a 30 Dias": "15 a 30 Dias:",
    "30 a 45 Dias": "30 a 45 Dias:",
    "45 a 55 Dias": "45 a 55 Dias:",
    "55 a 60 Dias": "55 a 60 Dias:",
    ">= a 61 Dias": ">= a 61 Dias:",
}

FAIXA_CORES = {
    "10 a 15 Dias": ("FFFF99", "000000"),
    "15 a 30 Dias": ("FFFF00", "000000"),
    "30 a 45 Dias": ("FFCCCC", "000000"),
    "45 a 55 Dias": ("FF6666", "000000"),
    "55 a 60 Dias": ("FF0000", "FFFFFF"),
    ">= a 61 Dias": ("8B0000", "FFFFFF"),
}


def _serializar_celula(valor: Any) -> Any:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (datetime, date)):
        return valor.isoformat(sep=" ", timespec="seconds") if isinstance(valor, datetime) else valor.isoformat()
    if isinstance(valor, float):
        if valor.is_integer():
            return int(valor)
        return valor
    return valor


def dataframe_para_base(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    registros = []
    for row in df.to_dict(orient="records"):
        registros.append({str(k): _serializar_celula(v) for k, v in row.items()})
    return registros


def base_para_dataframe(detalhes: dict) -> pd.DataFrame:
    colunas = detalhes.get("base_colunas") or []
    linhas = detalhes.get("base") or []
    if not linhas:
        return pd.DataFrame(columns=colunas)
    df = pd.DataFrame(linhas)
    if colunas:
        for col in colunas:
            if col not in df.columns:
                df[col] = None
        extras = [c for c in df.columns if c not in colunas]
        df = df[colunas + extras]
    return df


MESES_ABREV = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)


def mes_para_yyyymm(valor) -> str:
    if valor is None:
        return ""
    if hasattr(valor, "year") and hasattr(valor, "month"):
        try:
            return f"{int(valor.year):04d}{int(valor.month):02d}"
        except (TypeError, ValueError):
            pass
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    if texto.isdigit() and len(texto) == 6:
        return texto
    iso = re.match(r"^(\d{4})-(\d{2})", texto)
    if iso:
        return f"{iso.group(1)}{iso.group(2)}"
    if "/" in texto:
        try:
            a, b = texto.split("/", 1)
            if a[:3].title() in MESES_ABREV:
                return f"{int(b):04d}{MESES_ABREV.index(a[:3].title()) + 1:02d}"
            if len(a) == 4:
                return f"{int(a):04d}{int(b):02d}"
            return f"{int(b):04d}{int(a):02d}"
        except ValueError:
            return texto
    return texto


def rotulo_mes_venc(yyyymm: str) -> str:
    chave = mes_para_yyyymm(yyyymm)
    if len(chave) == 6 and chave.isdigit():
        mes = int(chave[4:6])
        if 1 <= mes <= 12:
            return f"{MESES_ABREV[mes - 1]}/{chave[:4]}"
    return yyyymm or ""


def mes_tratar_yyyymm(hoje: date | None = None) -> str:
    """Mês de vencimento prestes a completar 60 dias (hoje − 2 meses)."""
    from django.utils import timezone

    d = hoje or timezone.localdate()
    mes = d.month - 2
    ano = d.year
    if mes <= 0:
        mes += 12
        ano -= 1
    return f"{ano:04d}{mes:02d}"


def meses_janela_yyyymm(hoje: date | None = None) -> list[str]:
    from django.utils import timezone

    d = hoje or timezone.localdate()
    meses = []
    ano, mes = d.year, d.month
    for _ in range(3):
        meses.append(f"{ano:04d}{mes:02d}")
        mes -= 1
        if mes <= 0:
            mes = 12
            ano -= 1
    return list(reversed(meses))


def _meses_ordenados(detalhes: dict) -> list[dict]:
    meses = list((detalhes or {}).get("meses") or [])
    return sorted(meses, key=lambda m: mes_para_yyyymm(m.get("mes_yyyymm") or m.get("mes")))


def _meses_do_recorte(rel: RelatorioFPD, mes_venc: str | None) -> list[dict] | None:
    """None = PDV sem aquele MES_VENC (quando a base tem breakdown)."""
    meses = _meses_ordenados(rel.detalhes or {})
    if not mes_venc:
        return meses
    alvo = mes_para_yyyymm(mes_venc)
    filtrados = [
        m for m in meses if mes_para_yyyymm(m.get("mes_yyyymm") or m.get("mes")) == alvo
    ]
    if filtrados:
        return filtrados
    if meses:
        return None
    return []


def visao_fpd(rel: RelatorioFPD, mes_venc: str | None = None) -> dict | None:
    """Totais e texto do relatório no MES_VENC (ou consolidado se mes_venc vazio)."""
    meses = _meses_do_recorte(rel, mes_venc)
    if meses is None:
        return None
    if not meses:
        return {
            "percentual": rel.percentual,
            "total": rel.total_faturas,
            "abertas": rel.total_abertas,
            "pagas": _total_pagas(rel),
            "mensagem": rel.mensagem,
            "meses": [],
        }
    total = sum(int(m.get("total") or 0) for m in meses)
    abertas = sum(int(m.get("abertas") or 0) for m in meses)
    pagas = sum(int(m.get("pagas") or 0) for m in meses)
    perc = (abertas / total * 100) if total else 0.0
    return {
        "percentual": perc,
        "total": total,
        "abertas": abertas,
        "pagas": pagas,
        "mensagem": _mensagem_visao(rel, meses, perc, total, abertas, mes_venc),
        "meses": meses,
    }


def _mensagem_visao(
    rel: RelatorioFPD,
    meses: list[dict],
    perc: float,
    total: int,
    abertas: int,
    mes_venc: str | None,
) -> str:
    ind = rel.indicador or "FPD"
    sub = {
        "FPD": "Primeira fatura",
        "SPD": "Segunda fatura",
        "TPD": "Terceira fatura",
    }.get(ind, ind)
    if (rel.segmento or "todos") != "todos":
        sub += f" · {rel.get_segmento_display()}"
    if mes_venc:
        sub += f" · MES_VENC {rotulo_mes_venc(mes_venc)}"
    linhas = [f"📊 *Relatório {ind} - {rel.pdv_nome}*", f"_({sub})_", ""]
    for mes in meses:
        faixas = mes.get("faixas") or {}
        linhas.append(f"🗓️ *Mês fatura: {mes.get('mes') or rotulo_mes_venc(str(mes.get('mes_yyyymm') or ''))}*")
        linhas.append(f"   - Total: *{int(mes.get('total') or 0)}*")
        linhas.append(f"   - Pagas: *{int(mes.get('pagas') or 0)}*")
        linhas.append(f"   - Em aberto: *{int(mes.get('abertas') or 0)}*")
        linhas.append(f"   - % em aberto: *{float(mes.get('perc_aberto') or 0):.2f}%*")
        if int(mes.get("abertas") or 0):
            linhas.append("   *Abertas por faixa:*")
            linhas.append(f"     - 10 a 15: {int(faixas.get('10 a 15 Dias') or 0)}")
            linhas.append(f"     - 15 a 30: {int(faixas.get('15 a 30 Dias') or 0)}")
            linhas.append(f"     - 30 a 45: {int(faixas.get('30 a 45 Dias') or 0)}")
            linhas.append(f"     - 45 a 55: {int(faixas.get('45 a 55 Dias') or 0)}")
            linhas.append(f"     - 55 a 60: {int(faixas.get('55 a 60 Dias') or 0)}")
            linhas.append(f"     - >60: {int(faixas.get('>= a 61 Dias') or 0)}")
        linhas.append("")
    consolidado = f"{ind} consolidado"
    if (rel.segmento or "todos") != "todos":
        consolidado += f" · {rel.get_segmento_display()}"
    if mes_venc:
        consolidado += f" · {rotulo_mes_venc(mes_venc)}"
    linhas.append(f"📌 *{consolidado}:* {perc:.2f}% (Abertas: {abertas} / Total: {total})")
    return "\n".join(linhas).strip()


def _intervalo_meses(meses: list[dict]) -> str:
    chaves = [mes_para_yyyymm(m.get("mes_yyyymm") or m.get("mes")) for m in meses]
    chaves = [c for c in chaves if c]
    if not chaves:
        return ""
    if len(chaves) == 1:
        return chaves[0]
    return f"{chaves[0]} a {chaves[-1]}"


def _tag_arquivo(nome: str) -> str:
    limpo = re.sub(r"[^\w\-]+", "_", (nome or "PDV").strip(), flags=re.UNICODE)
    return limpo.strip("_")[:50] or "PDV"


def _codigo_rede(rel: RelatorioFPD) -> str:
    det = rel.detalhes or {}
    codigo = str(det.get("codigo_rede") or "").strip()
    if codigo.endswith(".0") and codigo[:-2].isdigit():
        codigo = codigo[:-2]
    return codigo


def _total_pagas(rel: RelatorioFPD) -> int:
    det = rel.detalhes or {}
    if det.get("total_pagas") is not None:
        return int(det["total_pagas"])
    meses = _meses_ordenados(det)
    if meses:
        return sum(int(m.get("pagas") or 0) for m in meses)
    return max(rel.total_faturas - rel.total_abertas, 0)


def _fmt_percentual_br(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",") + "%"


def _tabela_resumo(rel: RelatorioFPD, mes_venc: str | None = None) -> list[list[str]]:
    recorte = _meses_do_recorte(rel, mes_venc)
    if recorte is None:
        meses = []
    elif recorte:
        meses = recorte
    else:
        meses = _meses_ordenados(rel.detalhes or {})
    cabecalho = ["MÊS FATURA"] + [mes_para_yyyymm(m.get("mes_yyyymm") or m.get("mes")) for m in meses]
    linhas = [cabecalho]
    linhas.append(["FATURA PAGA"] + [str(int(m.get("pagas") or 0)) for m in meses])
    linhas.append(["TOTAL FATURA"] + [str(int(m.get("total") or 0)) for m in meses])
    linhas.append(
        ["% ABERTO"]
        + [
            _fmt_percentual_br(
                (int(m.get("abertas") or 0) / int(m.get("total") or 1) * 100)
                if int(m.get("total") or 0)
                else 0.0
            )
            for m in meses
        ]
    )
    for faixa in FAIXAS_ORDEM:
        linha = [FAIXA_ROTULO[faixa]]
        for mes in meses:
            faixas = mes.get("faixas") or {}
            linha.append(str(int(faixas.get(faixa) or 0)))
        linhas.append(linha)
    return linhas


def _estilo_faixa(label: str) -> tuple[str, str]:
    for chave, estilo in FAIXA_CORES.items():
        if chave in label:
            return estilo
    return ("FFFFFF", "000000")


def _filtrar_base_mes(df: pd.DataFrame, mes_venc: str | None) -> pd.DataFrame:
    if df.empty or not mes_venc:
        return df
    alvo = mes_para_yyyymm(mes_venc)
    for col in ("REF_VENCTO", "MES_VENC", "MES_VENCIMENTO"):
        if col in df.columns:
            return df[df[col].map(lambda v: mes_para_yyyymm(v) == alvo)]
    return df


def planilha_fpd(rel: RelatorioFPD, mes_venc: str | None = None) -> tuple[bytes, str]:
    wb = Workbook()
    ws_resumo = wb.active
    ws_resumo.title = "Planilha1"

    tabela = _tabela_resumo(rel, mes_venc)
    for r_idx, linha in enumerate(tabela, start=1):
        for c_idx, valor in enumerate(linha, start=1):
            cell = ws_resumo.cell(row=r_idx, column=c_idx, value=valor)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if r_idx == 1 or c_idx == 1:
                cell.font = Font(bold=True)
            if r_idx >= 5 and c_idx > 1:
                fundo, fonte = _estilo_faixa(linha[0])
                cell.fill = PatternFill("solid", fgColor=fundo)
                cell.font = Font(color=fonte, bold=True)
            if linha[0] == "% ABERTO" and c_idx > 1:
                cell.font = Font(bold=True, underline="single")

    for col in range(1, max(len(tabela[0]) if tabela else 1, 1) + 1):
        ws_resumo.column_dimensions[get_column_letter(col)].width = 16

    ws_base = wb.create_sheet("BASE_PRE_FPD_ABERTO")
    df_base = _filtrar_base_mes(base_para_dataframe(rel.detalhes or {}), mes_venc)
    if df_base.empty:
        ws_base.append(["Sem base detalhada para este PDV."])
    else:
        ws_base.append(list(df_base.columns))
        for row in df_base.itertuples(index=False, name=None):
            ws_base.append([_serializar_celula(v) for v in row])
        for cell in ws_base[1]:
            cell.font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    codigo = _codigo_rede(rel)
    sufixo = f"{codigo}-" if codigo else ""
    recorte = _recorte_arquivo(rel, mes_venc)
    nome = f"FATURAS_ABERTAS_PRE-FIBRA-{recorte}{sufixo}{_tag_arquivo(rel.pdv_nome)}.xlsx"
    return buf.getvalue(), nome


def _recorte_arquivo(rel: RelatorioFPD, mes_venc: str | None = None) -> str:
    ind = (rel.indicador or "FPD").upper()
    seg = (rel.segmento or "todos").lower()
    partes = [ind]
    if seg != "todos":
        partes.append(seg.upper())
    if mes_venc:
        partes.append(mes_para_yyyymm(mes_venc))
    return "-".join(partes) + "-"


def _recorte_texto(rel: RelatorioFPD) -> str:
    ind = rel.indicador or "FPD"
    if (rel.segmento or "todos") == "todos":
        return ind
    return f"{ind} · {rel.get_segmento_display()}"


def assunto_email_fpd(rel: RelatorioFPD, mes_venc: str | None = None) -> str:
    codigo = _codigo_rede(rel)
    pdv = (rel.pdv_nome or rel.parceiro.nome or "PDV").strip().upper()
    recorte = _recorte_arquivo(rel, mes_venc).rstrip("-")
    if codigo:
        return f"FATURAS_ABERTAS_PRÉ-FIBRA-{recorte}{codigo}-{pdv}"
    return f"FATURAS_ABERTAS_PRÉ-FIBRA-{recorte}-{pdv}"


def html_email_fpd(rel: RelatorioFPD, mes_venc: str | None = None) -> str:
    visao = visao_fpd(rel, mes_venc) or {
        "percentual": rel.percentual,
        "total": rel.total_faturas,
        "abertas": rel.total_abertas,
        "pagas": _total_pagas(rel),
        "meses": _meses_ordenados(rel.detalhes or {}),
    }
    pdv = (rel.pdv_nome or rel.parceiro.nome or "PDV").strip().upper()
    meses = visao.get("meses") or _meses_ordenados(rel.detalhes or {})
    intervalo = rotulo_mes_venc(mes_venc) if mes_venc else _intervalo_meses(meses)
    total = visao["total"]
    pagas = visao["pagas"]
    abertas = visao["abertas"]
    perc = visao["percentual"]
    recorte = _recorte_texto(rel)
    if mes_venc:
        recorte = f"{recorte} · {rotulo_mes_venc(mes_venc)}"

    linhas_html = []
    tabela = _tabela_resumo(rel, mes_venc)
    for r_idx, linha in enumerate(tabela):
        cells = []
        for c_idx, valor in enumerate(linha):
            estilo = ""
            if r_idx == 0 and c_idx > 0:
                estilo = ' style="font-size:13.5pt;font-weight:bold;text-decoration:underline"'
            elif linha[0] == "% ABERTO" and c_idx > 0:
                estilo = ' style="font-weight:bold;text-decoration:underline"'
            elif r_idx >= 4 and c_idx > 0 and str(valor) not in {"0", "0,00%"}:
                fundo, cor = _estilo_faixa(linha[0])
                estilo = f' style="background:#{fundo};color:#{cor};font-weight:bold"'
            cells.append(
                f'<td align="center" style="text-align:center"{estilo}>'
                f'<p align="center" style="text-align:center;margin:0">{valor}</p></td>'
            )
        linhas_html.append("<tr>" + "".join(cells) + "</tr>")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"></head>
<body bgcolor="#EBF0EA" style="font-family:Calibri,Arial,sans-serif;color:#000">
<p><b>Bom dia, prezado parceiro!</b></p>
<p><b><span style="font-size:21pt;color:#21C002">{pdv}</span></b></p>
<p>Segue <b>Faturas abertas</b> ({recorte}) <b>15 a 60 dias em aberto com vencimento no meses de {intervalo}</b><br>
Faturas Abertas com vencimento menor que 61 dias.<br>
<b>{pdv}</b> - Com o total de faturas de
<b><u><span style="font-size:18pt;color:blue">{total}</span></u></b> e
<b><u><span style="font-size:18pt;color:green">{pagas}</span></u></b> Pagas, sendo com risco de {rel.indicador or "FPD"}
<b><u><span style="font-size:18pt;color:red">{abertas}</span></u></b> com o Percentual de
<b><u><span style="font-size:18pt;color:red">{perc:.2f}%</span></u></b> Das Faturas Totais<br>
<b>Faixas e Quantidades, Faturas Abertas a tratar</b></p>
<table border="1" cellpadding="4" cellspacing="0" style="background:white;border-collapse:collapse">
{"".join(linhas_html)}
</table>
<p>Planilha detalhada em anexo.</p>
</body></html>"""


def corpo_texto_email_fpd(rel: RelatorioFPD, mes_venc: str | None = None) -> str:
    visao = visao_fpd(rel, mes_venc)
    pdv = (rel.pdv_nome or rel.parceiro.nome or "PDV").strip().upper()
    meses = (visao or {}).get("meses") or _meses_ordenados(rel.detalhes or {})
    intervalo = rotulo_mes_venc(mes_venc) if mes_venc else _intervalo_meses(meses)
    recorte = _recorte_texto(rel)
    if mes_venc:
        recorte = f"{recorte} · {rotulo_mes_venc(mes_venc)}"
    total = visao["total"] if visao else rel.total_faturas
    pagas = visao["pagas"] if visao else _total_pagas(rel)
    abertas = visao["abertas"] if visao else rel.total_abertas
    perc = visao["percentual"] if visao else rel.percentual
    return (
        f"Bom dia, prezado parceiro!\n\n"
        f"{pdv}\n\n"
        f"Segue Faturas abertas ({recorte}) 15 a 60 dias em aberto "
        f"com vencimento nos meses de {intervalo}.\n"
        f"Total: {total} | Pagas: {pagas} | "
        f"Em aberto ({rel.indicador or 'FPD'}): {abertas} | "
        f"Percentual: {perc:.2f}%\n\n"
        f"Planilha detalhada em anexo."
    )
