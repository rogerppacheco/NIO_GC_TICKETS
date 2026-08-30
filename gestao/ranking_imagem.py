from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .pipelines.resultados import (
    GRUPO_INICIANTE,
    GRUPO_REGULAR,
    GRUPO_SEM_CADASTRO,
    _fmt_pts,
)

BG = (255, 255, 255)
BRAND = (15, 107, 92)
BRAND_LIGHT = (238, 248, 245)
INK = (21, 32, 43)
MUTED = (91, 107, 124)
LINE = (215, 222, 231)
ALT_ROW = (248, 250, 252)

LARGURA = 1080
PAD = 32
GAP_COL = 20
ALT_LINHA = 34
ALT_HEADER_TABELA = 30


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


def _titulo_janela(periodo: dict) -> str:
    ini = periodo.get("janela_ini")
    fim = periodo.get("janela_fim")
    if not ini or not fim:
        return ""
    if ini == fim:
        return ini.strftime("%d/%m")
    return f"{ini.strftime('%d/%m')}–{fim.strftime('%d/%m')}"


def _altura_bloco(qtd: int) -> int:
    linhas = min(max(qtd, 1), 15)
    return 44 + ALT_HEADER_TABELA + linhas * ALT_LINHA + 8


def _desenhar_bloco(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    largura: int,
    titulo: str,
    itens: list[dict[str, Any]],
    janela: str,
    font_titulo,
    font_head,
    font_cell,
    limite: int,
) -> int:
    draw.rounded_rectangle(
        (x, y, x + largura, y + _altura_bloco(len(itens))),
        radius=12,
        fill=BRAND_LIGHT,
        outline=LINE,
    )
    draw.text((x + 14, y + 10), titulo, fill=INK, font=font_titulo)

    y_table = y + 44
    cols = [(" #", 34), ("Vendedor", 200), ("Pts", 58), (janela or "Ant.", 58)]
    x_cur = x + 10
    for rotulo, cw in cols:
        draw.text((x_cur + 4, y_table + 6), rotulo, fill=MUTED, font=font_head)
        x_cur += cw

    draw.line((x + 8, y_table + ALT_HEADER_TABELA, x + largura - 8, y_table + ALT_HEADER_TABELA), fill=LINE)

    if not itens:
        draw.text((x + 14, y_table + ALT_HEADER_TABELA + 8), "Ninguém neste grupo.", fill=MUTED, font=font_cell)
        return y + _altura_bloco(0)

    y_row = y_table + ALT_HEADER_TABELA + 4
    for idx, item in enumerate(itens[:limite]):
        if idx % 2 == 1:
            draw.rectangle(
                (x + 8, y_row - 2, x + largura - 8, y_row + ALT_LINHA - 6),
                fill=ALT_ROW,
            )
        vals = [
            (str(item.get("posicao") or ""), 34),
            (_truncar(str(item.get("nome") or ""), 22), 200),
            (_fmt_pts(float(item.get("pontos") or 0)), 58),
            (_fmt_pts(float(item.get("pontos_dia") or 0)), 58),
        ]
        x_cur = x + 10
        for texto, cw in vals:
            draw.text((x_cur + 4, y_row + 4), texto, fill=INK, font=font_cell)
            x_cur += cw
        y_row += ALT_LINHA

    restantes = len(itens) - limite
    if restantes > 0:
        draw.text(
            (x + 14, y_row + 2),
            f"+ {restantes} vendedor(es)",
            fill=MUTED,
            font=font_cell,
        )

    return y + _altura_bloco(len(itens))


def imagem_ranking(ranking: dict, *, limite_por_grupo: int = 15) -> tuple[bytes, str]:
    """Gera PNG do ranking para envio no WhatsApp (preview = anexo enviado)."""
    periodo = ranking.get("periodo") or {}
    grupos = ranking.get("grupos") or {}
    regular = list(grupos.get(GRUPO_REGULAR) or [])
    iniciante = list(grupos.get(GRUPO_INICIANTE) or [])
    sem_cad = list(grupos.get(GRUPO_SEM_CADASTRO) or [])

    janela = _titulo_janela(periodo)
    inicio = periodo.get("inicio")
    fim = periodo.get("fim")
    periodo_txt = ""
    if inicio and fim:
        periodo_txt = f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"

    font_titulo = _fonte(22, negrito=True)
    font_sub = _fonte(15)
    font_titulo_bloco = _fonte(16, negrito=True)
    font_head = _fonte(13, negrito=True)
    font_cell = _fonte(14)

    col_w = (LARGURA - PAD * 2 - GAP_COL) // 2
    altura_corpo = max(_altura_bloco(len(regular)), _altura_bloco(len(iniciante)))
    altura_extra = _altura_bloco(len(sem_cad)) + 16 if sem_cad else 0
    altura = PAD + 92 + altura_corpo + altura_extra + PAD

    img = Image.new("RGB", (LARGURA, altura), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, LARGURA, 92), fill=BRAND)
    draw.text((PAD, 18), "Ranking VB", fill=(255, 255, 255), font=font_titulo)
    if periodo_txt:
        draw.text((PAD, 52), periodo_txt, fill=(220, 240, 236), font=font_sub)
    if janela:
        draw.text(
            (PAD, 72),
            f"Pontuação do período anterior: {janela} · padrão 1 pt · BTU 0,5 pt",
            fill=(200, 230, 224),
            font=_fonte(13),
        )

    y0 = PAD + 92
    _desenhar_bloco(
        draw,
        x=PAD,
        y=y0,
        largura=col_w,
        titulo="Base Regular (>6 meses)",
        itens=regular,
        janela=janela,
        font_titulo=font_titulo_bloco,
        font_head=font_head,
        font_cell=font_cell,
        limite=limite_por_grupo,
    )
    _desenhar_bloco(
        draw,
        x=PAD + col_w + GAP_COL,
        y=y0,
        largura=col_w,
        titulo="Iniciante (≤6 meses)",
        itens=iniciante,
        janela=janela,
        font_titulo=font_titulo_bloco,
        font_head=font_head,
        font_cell=font_cell,
        limite=limite_por_grupo,
    )

    if sem_cad:
        y_sem = y0 + altura_corpo + 16
        largura_full = LARGURA - PAD * 2
        _desenhar_bloco(
            draw,
            x=PAD,
            y=y_sem,
            largura=largura_full,
            titulo="Sem data de alocação / Sysmap",
            itens=sem_cad,
            janela=janela,
            font_titulo=font_titulo_bloco,
            font_head=font_head,
            font_cell=font_cell,
            limite=limite_por_grupo,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    nome = f"Ranking_VB_{fim.isoformat()}.png" if fim else "Ranking_VB.png"
    return buf.getvalue(), nome
