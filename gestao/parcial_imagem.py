from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .pipelines.parcial_vendas import agrupar_por_especialista

BG = (255, 255, 255)
BRAND = (15, 107, 92)
BRAND_SOFT = (232, 245, 242)
INK = (21, 32, 43)
MUTED = (91, 107, 124)
LINE = (215, 222, 231)
ALT_ROW = (248, 250, 252)
POS = (22, 128, 88)
NEG = (196, 64, 54)

PAD = 20
ALT_LINHA = 30
ALT_ESP = 26
HEADER_H = 96
FOOTER_H = 34

COLS = [
    ("PDV", 220),
    ("TOTAL", 68),
    ("D-7", 68),
    ("∆", 58),
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


def _desenhar_linha_dados(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    largura: int,
    item: dict,
    cols: list[tuple[str, int]],
    font_cell,
    fundo: tuple[int, int, int] | None = None,
    negrito: bool = False,
) -> int:
    if fundo:
        draw.rectangle((x + 6, y, x + largura - 6, y + ALT_LINHA - 2), fill=fundo)
    delta = int(item.get("delta") if "delta" in item else (item.get("vendas", 0) - item.get("d7", 0)))
    rotulo = str(item.get("pdv") or item.get("rotulo") or "")
    vals = [
        (_truncar(rotulo, 28), INK),
        (str(int(item.get("vendas") or 0)), INK),
        (str(int(item.get("d7") or 0)), INK),
        (_fmt_delta(delta), _cor_delta(delta)),
    ]
    x_cur = x + 8
    for (texto, cor), (_, larg) in zip(vals, cols):
        draw.text((x_cur + 2, y + 7), texto, fill=cor, font=font_cell)
        x_cur += larg
    return y + ALT_LINHA


def _altura_tabela_simples(qtd_linhas: int, *, com_total: bool = False) -> int:
    linhas = max(qtd_linhas, 1)
    extra = ALT_LINHA if com_total else 0
    return 36 + linhas * ALT_LINHA + extra + 12


def _desenhar_tabela_simples(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    titulo_secao: str,
    itens: list[dict],
    cols: list[tuple[str, int]],
    font_titulo,
    font_head,
    font_cell,
    total: dict | None = None,
    vazio_msg: str = "Sem dados.",
) -> int:
    largura = _largura_cols(cols)
    qtd = len(itens) if itens else 1
    if total and itens:
        qtd += 1
    altura = _altura_tabela_simples(len(itens) if itens else 1, com_total=bool(total and itens))
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
        draw.text((x + 10, y + 58), vazio_msg, fill=MUTED, font=font_cell)
        return y + altura

    y_row = y + 54
    for idx, item in enumerate(itens):
        y_row = _desenhar_linha_dados(
            draw,
            x=x,
            y=y_row,
            largura=largura,
            item=item,
            cols=cols,
            font_cell=font_cell,
            fundo=ALT_ROW if idx % 2 == 1 else None,
        )

    if total:
        draw.line((x + 6, y_row - 2, x + largura - 6, y_row - 2), fill=LINE)
        _desenhar_linha_dados(
            draw,
            x=x,
            y=y_row,
            largura=largura,
            item={
                "pdv": total.get("rotulo", "TOTAL"),
                "vendas": total.get("vendas", 0),
                "d7": total.get("d7", 0),
                "delta": total.get("delta", 0),
            },
            cols=cols,
            font_cell=font_head,
            fundo=BRAND_SOFT,
        )
    return y + altura


def _desenhar_total_pp(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    dados: dict,
    cols: list[tuple[str, int]],
    font_head,
) -> int:
    largura = _largura_cols(cols)
    altura = ALT_LINHA + 16
    draw.rounded_rectangle((x, y, x + largura, y + altura), radius=10, outline=LINE, fill=BG)
    _desenhar_linha_dados(
        draw,
        x=x,
        y=y + 6,
        largura=largura,
        item={
            "pdv": "TOTAL PP",
            "vendas": dados.get("total_pp", 0),
            "d7": dados.get("total_d7", 0),
            "delta": dados.get("delta_pp", 0),
        },
        cols=cols,
        font_cell=font_head,
        fundo=BRAND_SOFT,
    )
    return y + altura


def imagem_parcial_gerencia(dados: dict) -> tuple[bytes, str]:
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(13)
    font_titulo = _fonte(14, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    cols = COLS
    top5 = dados.get("top5") or []
    pior5 = dados.get("pior5") or []
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    altura = (
        HEADER_H
        + _altura_tabela_simples(max(len(top5), 1))
        + 12
        + _altura_tabela_simples(len(pior5) if pior5 else 1)
        + 12
        + ALT_LINHA + 16
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
    y = _desenhar_tabela_simples(
        draw,
        x=PAD,
        y=y,
        titulo_secao="▲ Top 5 — ∆ absoluto D-7",
        itens=top5,
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
    )
    y += 12
    y = _desenhar_tabela_simples(
        draw,
        x=PAD,
        y=y,
        titulo_secao="▼ Bottom 5 — ∆ absoluto D-7",
        itens=pior5,
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
        vazio_msg="Nenhum PDV adicional (≤5 no escopo).",
    )
    y += 12
    _desenhar_total_pp(draw, x=PAD, y=y, dados=dados, cols=cols, font_head=font_head)

    return _salvar_png(img, dados, "Gerencia")


def _altura_grupo(qtd_pdvs: int) -> int:
    return ALT_ESP + 22 + max(qtd_pdvs, 0) * ALT_LINHA + 4


def _altura_por_especialistas(grupos: list[dict]) -> int:
    total = 52 + FOOTER_H
    for g in grupos:
        total += _altura_grupo(len(g.get("linhas") or []))
    return total


def _desenhar_por_especialista(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    grupos: list[dict],
    cols: list[tuple[str, int]],
    font_esp,
    font_head,
    font_cell,
    total_pp: dict | None = None,
) -> int:
    largura = _largura_cols(cols)
    y_cur = y + 8
    x_cur = x + 8
    for rotulo, larg in cols:
        draw.text((x_cur, y_cur), rotulo, fill=MUTED, font=font_head)
        x_cur += larg
    draw.line((x + 6, y_cur + 18, x + largura - 6, y_cur + 18), fill=LINE)
    y_cur += 24

    for grupo in grupos:
        draw.rectangle((x + 6, y_cur, x + largura - 6, y_cur + ALT_ESP), fill=BRAND)
        draw.text(
            (x + 10, y_cur + 5),
            _truncar(str(grupo.get("especialista") or "Sem especialista"), 36).upper(),
            fill=(255, 255, 255),
            font=font_esp,
        )
        y_cur += ALT_ESP
        for idx, item in enumerate(grupo.get("linhas") or []):
            y_cur = _desenhar_linha_dados(
                draw,
                x=x,
                y=y_cur,
                largura=largura,
                item=item,
                cols=cols,
                font_cell=font_cell,
                fundo=ALT_ROW if idx % 2 == 1 else None,
            )
        y_cur += 4

    if total_pp:
        draw.line((x + 6, y_cur, x + largura - 6, y_cur), fill=LINE)
        y_cur = _desenhar_linha_dados(
            draw,
            x=x,
            y=y_cur + 2,
            largura=largura,
            item={
                "pdv": total_pp.get("rotulo", "TOTAL PP"),
                "vendas": total_pp.get("vendas", 0),
                "d7": total_pp.get("d7", 0),
                "delta": total_pp.get("delta", 0),
            },
            cols=cols,
            font_cell=font_head,
            fundo=BRAND_SOFT,
        )
    return y_cur + 8


def imagem_parcial_especialistas(dados: dict, *, titulo: str = "Carteira PP") -> tuple[bytes, str]:
    """Visão completa: especialista → parceiros + linha TOTAL PP."""
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(13)
    font_esp = _fonte(13, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    linhas = dados.get("linhas") or []
    grupos = agrupar_por_especialista(linhas)
    cols = COLS
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    altura = HEADER_H + _altura_por_especialistas(grupos) + PAD + 16

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

    draw.rounded_rectangle(
        (PAD, HEADER_H, PAD + tab_w, altura - PAD),
        radius=10,
        outline=LINE,
        fill=BG,
    )
    _desenhar_por_especialista(
        draw,
        x=PAD,
        y=HEADER_H,
        grupos=grupos,
        cols=cols,
        font_esp=font_esp,
        font_head=font_head,
        font_cell=font_cell,
        total_pp={
            "rotulo": "TOTAL PP",
            "vendas": dados.get("total_pp", 0),
            "d7": dados.get("total_d7", 0),
            "delta": dados.get("delta_pp", 0),
        },
    )

    return _salvar_png(img, dados, "Especialistas")


def imagem_parcial_especialista(grupo: dict, dados: dict) -> tuple[bytes, str]:
    """Carteira de um especialista: nome + parceiros + subtotal."""
    font_banner = _fonte(22, negrito=True)
    font_sub = _fonte(13)
    font_esp = _fonte(13, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    cols = COLS
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    linhas = grupo.get("linhas") or []
    altura = HEADER_H + _altura_grupo(len(linhas)) + FOOTER_H + PAD + 24

    img = Image.new("RGB", (largura, altura), BG)
    draw = ImageDraw.Draw(img)
    esp = grupo.get("especialista") or "Especialista"
    _desenhar_header(
        draw,
        largura=largura,
        titulo=f"Parcial · {_truncar(esp, 32)}",
        subtitulo=_subtitulo(dados),
        metricas=(
            f"Total: {grupo.get('total_vendas', 0)} VB · "
            f"D-7: {grupo.get('total_d7', 0)} · "
            f"∆ {_fmt_delta(int(grupo.get('delta') or 0))} · "
            f"{grupo.get('qtd_pdvs', 0)} PDV(s)"
        ),
        font_banner=font_banner,
        font_sub=font_sub,
    )

    draw.rounded_rectangle(
        (PAD, HEADER_H, PAD + tab_w, altura - PAD),
        radius=10,
        outline=LINE,
        fill=BG,
    )
    _desenhar_por_especialista(
        draw,
        x=PAD,
        y=HEADER_H,
        grupos=[grupo],
        cols=cols,
        font_esp=font_esp,
        font_head=font_head,
        font_cell=font_cell,
        total_pp={
            "rotulo": "TOTAL CARTEIRA",
            "vendas": grupo.get("total_vendas", 0),
            "d7": grupo.get("total_d7", 0),
            "delta": grupo.get("delta", 0),
        },
    )

    slug = "".join(ch for ch in esp if ch.isalnum())[:16] or "esp"
    return _salvar_png(img, dados, slug)


def imagem_parcial_pdv(linha: dict, dados: dict) -> tuple[bytes, str]:
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(13)
    font_titulo = _fonte(14, negrito=True)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(12)

    cols = COLS
    tab_w = _largura_cols(cols)
    largura = tab_w + 2 * PAD
    altura = HEADER_H + 36 + ALT_LINHA + FOOTER_H + 8 + PAD

    img = Image.new("RGB", (largura, altura), BG)
    draw = ImageDraw.Draw(img)
    pdv = linha.get("pdv") or "PDV"
    _desenhar_header(
        draw,
        largura=largura,
        titulo=f"Parcial · {_truncar(pdv, 28)}",
        subtitulo=_subtitulo(dados),
        metricas=f"Especialista: {linha.get('especialista') or '—'}",
        font_banner=font_banner,
        font_sub=font_sub,
    )
    _desenhar_tabela_simples(
        draw,
        x=PAD,
        y=HEADER_H,
        titulo_secao="Resultado do PDV",
        itens=[linha],
        cols=cols,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
        total={
            "rotulo": "TOTAL",
            "vendas": linha.get("vendas", 0),
            "d7": linha.get("d7", 0),
            "delta": linha.get("delta", 0),
        },
    )

    slug = "".join(ch for ch in pdv if ch.isalnum())[:20] or "pdv"
    return _salvar_png(img, dados, slug)


def _salvar_png(img: Image.Image, dados: dict, slug: str) -> tuple[bytes, str]:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    mes, ano = dados.get("mes"), dados.get("ano")
    turno = dados.get("rotulo_turno") or "parcial"
    nome = f"Parcial_{slug}_{mes:02d}_{ano}_{turno}.png" if mes and ano else f"Parcial_{slug}.png"
    return buf.getvalue(), nome


# Compatibilidade com chamadas antigas
def imagem_parcial_carteira(dados: dict, *, titulo: str = "Minha carteira") -> tuple[bytes, str]:
    return imagem_parcial_especialistas(dados, titulo=titulo)
