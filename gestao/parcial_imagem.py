from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

BG = (255, 255, 255)
BRAND = (15, 107, 92)
INK = (21, 32, 43)
MUTED = (91, 107, 124)
LINE = (215, 222, 231)
ALT_ROW = (248, 250, 252)
POS = (22, 128, 88)
NEG = (196, 64, 54)

PAD = 20
ALT_LINHA = 32
HEADER_H = 96

COLS_GERENCIA = [
    ("PDV", 240),
    ("TOTAL", 72),
    ("D-7", 72),
    ("∆", 64),
]

COLS_CARTEIRA = [
    ("PDV", 200),
    ("TOTAL", 68),
    ("D-7", 68),
    ("∆", 60),
]


def _fonte(tamanho: int, negrito: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidatos = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ]
        if negrito
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    )
    for caminho in candidatos:
        if Path(caminho).is_file():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default()


def _truncar(texto: str, max_chars: int) -> str:
    t = (texto or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def _fmt_delta(valor: int) -> str:
    if valor > 0:
        return f"+{valor}"
    return str(valor)


def _cor_delta(valor: int) -> tuple[int, int, int]:
    if valor > 0:
        return POS
    if valor < 0:
        return NEG
    return INK


def _largura_cols(cols: list[tuple[str, int]]) -> int:
    return sum(w for _, w in cols) + 16


def _desenhar_header(
    draw: ImageDraw.ImageDraw,
    *,
    largura: int,
    titulo: str,
    subtitulo: str,
    metricas: str,
    font_banner,
    font_sub,
) -> None:
    draw.rectangle((0, 0, largura, HEADER_H), fill=BRAND)
    draw.text((PAD, 14), titulo, fill=(255, 255, 255), font=font_banner)
    draw.text((PAD, 48), subtitulo, fill=(220, 240, 236), font=font_sub)
    draw.text((PAD, 70), metricas, fill=(200, 230, 224), font=font_sub)


def _desenhar_tabela(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    titulo_secao: str,
    itens: list[dict[str, Any]],
    cols: list[tuple[str, int]],
    font_titulo,
    font_head,
    font_cell,
) -> int:
    largura = _largura_cols(cols)
    n = max(len(itens), 1)
    altura = 36 + n * ALT_LINHA + 12
    draw.rounded_rectangle((x, y, x + largura, y + altura), radius=10, outline=LINE, fill=BG)
    draw.rectangle((x, y, x + largura, y + 28), fill=BRAND)
    draw.text((x + 10, y + 5), titulo_secao, fill=(255, 255, 255), font=font_titulo)

    y_head = y + 32
    x_cur = x + 8
    for rotulo, larg in cols:
        draw.text((x_cur, y_head), rotulo, fill=MUTED, font=font_head)
        x_cur += larg
    draw.line((x + 6, y + 52, x + largura - 6, y + 52), fill=LINE)

    if not itens:
        draw.text((x + 10, y + 58), "Sem dados.", fill=MUTED, font=font_cell)
        return y + altura

    y_row = y + 54
    for idx, item in enumerate(itens):
        if idx % 2 == 1:
            draw.rectangle((x + 6, y_row, x + largura - 6, y_row + ALT_LINHA - 2), fill=ALT_ROW)
        delta = int(item.get("delta") or 0)
        vals = [
            (_truncar(str(item.get("pdv") or ""), 26), INK),
            (str(int(item.get("vendas") or 0)), INK),
            (str(int(item.get("d7") or 0)), INK),
            (_fmt_delta(delta), _cor_delta(delta)),
        ]
        x_cur = x + 8
        for (texto, cor), (_, larg) in zip(vals, cols):
            draw.text((x_cur + 2, y_row + 7), texto, fill=cor, font=font_cell)
            x_cur += larg
        y_row += ALT_LINHA
    return y + altura


def _subtitulo(dados: dict) -> str:
    ano, mes = dados.get("ano"), dados.get("mes")
    rotulo = dados.get("rotulo_turno") or "—"
    data_txt = ""
    raw = dados.get("data_ref")
    if raw:
        try:
            data_txt = date.fromisoformat(str(raw)).strftime("%d/%m/%Y")
        except ValueError:
            data_txt = str(raw)
    return f"{data_txt} · Mês {mes:02d}/{ano} · corte {rotulo}" if ano and mes else rotulo


def _metricas_totais(dados: dict) -> str:
    return (
        f"Total: {dados.get('total_pp', 0)} VB · "
        f"D-7: {dados.get('total_d7', 0)} · "
        f"∆ {_fmt_delta(int(dados.get('delta_pp') or 0))} · "
        f"{dados.get('qtd_pdvs', 0)} PDV(s)"
    )


def imagem_parcial_gerencia(dados: dict) -> tuple[bytes, str]:
    """Visão gerência: total PP + top/pior 5 por ∆ absoluto D-7."""
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(13)
    font_titulo = _fonte(14, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    cols = COLS_GERENCIA
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    altura = (
        HEADER_H
        + _altura_bloco(len(dados.get("top5") or []))
        + 12
        + _altura_bloco(len(dados.get("pior5") or []))
        + PAD
    )

    img = Image.new("RGB", (largura, altura), BG)
    draw = ImageDraw.Draw(img)
    _desenhar_header(
        draw,
        largura=largura,
        titulo="Parcial de vendas · Gerência PP",
        subtitulo=_subtitulo(dados),
        metricas=_metricas_totais(dados),
        font_banner=font_banner,
        font_sub=font_sub,
    )

    y = HEADER_H
    y = _desenhar_tabela(
        draw,
        x=PAD,
        y=y,
        titulo_secao="▲ Top 5 — ∆ absoluto D-7",
        itens=dados.get("top5") or [],
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
    )
    y += 12
    _desenhar_tabela(
        draw,
        x=PAD,
        y=y,
        titulo_secao="▼ Piores 5 — ∆ absoluto D-7",
        itens=dados.get("pior5") or [],
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    mes, ano = dados.get("mes"), dados.get("ano")
    turno = dados.get("rotulo_turno") or "parcial"
    nome = f"Parcial_Gerencia_{mes:02d}_{ano}_{turno}.png" if mes and ano else "Parcial_Gerencia.png"
    return buf.getvalue(), nome


def _altura_bloco(qtd: int) -> int:
    n = max(qtd, 1)
    return 36 + n * ALT_LINHA + 12


def imagem_parcial_carteira(dados: dict, *, titulo: str = "Minha carteira") -> tuple[bytes, str]:
    """Visão especialista: total da carteira + PDV a PDV."""
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(13)
    font_titulo = _fonte(14, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    linhas = sorted(
        dados.get("linhas") or [],
        key=lambda l: (-l.get("vendas", 0), l.get("pdv", "").upper()),
    )
    cols = COLS_CARTEIRA
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    altura = HEADER_H + _altura_bloco(len(linhas)) + PAD

    img = Image.new("RGB", (largura, altura), BG)
    draw = ImageDraw.Draw(img)
    _desenhar_header(
        draw,
        largura=largura,
        titulo=f"Parcial · {titulo}",
        subtitulo=_subtitulo(dados),
        metricas=_metricas_totais(dados),
        font_banner=font_banner,
        font_sub=font_sub,
    )
    _desenhar_tabela(
        draw,
        x=PAD,
        y=HEADER_H,
        titulo_secao="PDV a PDV — Total / D-7",
        itens=linhas,
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    mes, ano = dados.get("mes"), dados.get("ano")
    turno = dados.get("rotulo_turno") or "parcial"
    nome = f"Parcial_Carteira_{mes:02d}_{ano}_{turno}.png" if mes and ano else "Parcial_Carteira.png"
    return buf.getvalue(), nome


def imagem_parcial_pdv(linha: dict, dados: dict) -> tuple[bytes, str]:
    """Card compacto para envio ao grupo do parceiro."""
    font_banner = _fonte(26, negrito=True)
    font_sub = _fonte(15)
    font_metric = _fonte(20, negrito=True)

    largura = 420
    altura = 200
    img = Image.new("RGB", (largura, altura), BG)
    draw = ImageDraw.Draw(img)
    pdv = linha.get("pdv") or "PDV"
    delta = int(linha.get("delta") or 0)
    rotulo = dados.get("rotulo_turno") or "—"
    mes, ano = dados.get("mes"), dados.get("ano")

    draw.rounded_rectangle((0, 0, largura, altura), radius=14, outline=LINE, fill=BG)
    draw.rectangle((0, 0, largura, 72), fill=BRAND)
    draw.text((PAD, 14), _truncar(pdv, 28), fill=(255, 255, 255), font=font_banner)
    draw.text(
        (PAD, 46),
        f"Parcial · {mes:02d}/{ano} · {rotulo}" if mes and ano else f"Parcial · {rotulo}",
        fill=(220, 240, 236),
        font=font_sub,
    )

    y = 88
    draw.text((PAD, y), "Vendas acumuladas", fill=MUTED, font=font_sub)
    draw.text((PAD, y + 22), str(int(linha.get("vendas") or 0)), fill=INK, font=font_metric)

    x2 = largura // 2 + 8
    draw.text((x2, y), "Referência D-7", fill=MUTED, font=font_sub)
    draw.text((x2, y + 22), str(int(linha.get("d7") or 0)), fill=INK, font=font_metric)

    draw.line((PAD, 158, largura - PAD, 158), fill=LINE)
    draw.text((PAD, 168), "Variação absoluta D-7", fill=MUTED, font=font_sub)
    delta_txt = _fmt_delta(delta)
    bbox = draw.textbbox((0, 0), delta_txt, font=font_metric)
    tw = bbox[2] - bbox[0]
    draw.text((largura - PAD - tw, 166), delta_txt, fill=_cor_delta(delta), font=font_metric)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    slug = "".join(ch for ch in pdv if ch.isalnum())[:20] or "pdv"
    nome = f"Parcial_{slug}_{rotulo}.png"
    return buf.getvalue(), nome
