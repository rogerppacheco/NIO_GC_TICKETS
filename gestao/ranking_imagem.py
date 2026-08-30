from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .pipelines.resultados import GRUPO_INICIANTE, GRUPO_REGULAR, GRUPO_SEM_CADASTRO, _fmt_pts

BG = (255, 255, 255)
BRAND = (15, 107, 92)
BRAND_DARK = (11, 82, 71)
INK = (21, 32, 43)
MUTED = (91, 107, 124)
LINE = (215, 222, 231)
ALT_ROW = (248, 250, 252)
HEAD_BG = (232, 244, 240)

LARGURA = 1920
PAD = 24
GAP = 16
ALT_LINHA = 28
LIMITE_LINHAS = 20

# Larguras das colunas (formato RKG_2 — uma coluna ESPECIALISTA, nome curto)
COLS = [
    ("RKG", 42),
    ("PDV", 200),
    ("ESPECIALISTA", 148),
    ("PTS", 52),
    ("BTU", 52),
    ("PADRÃO", 58),
    ("PTS", 58),
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


def _rotulo_janela(periodo: dict) -> str:
    ini = periodo.get("janela_ini")
    fim = periodo.get("janela_fim")
    if not ini or not fim:
        return "—"
    if ini.day == fim.day:
        return str(ini.day)
    return f"{ini.day}-{fim.day}"


def _rotulo_acumulado(periodo: dict) -> str:
    fim = periodo.get("fim")
    return f"ATÉ {fim.strftime('%d/%m')}" if fim else "ACUMULADO"


def _largura_tabela() -> int:
    return sum(w for _, w in COLS) + 16


def _altura_tabela(qtd: int) -> int:
    linhas = min(max(qtd, 1), LIMITE_LINHAS)
    return 78 + linhas * ALT_LINHA + (18 if qtd > LIMITE_LINHAS else 8)


def _desenhar_tabela(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    titulo_grupo: str,
    itens: list[dict[str, Any]],
    rotulo_janela: str,
    rotulo_acumulado: str,
    font_titulo,
    font_head,
    font_cell,
    font_micro,
) -> int:
    largura = _largura_tabela()
    altura = _altura_tabela(len(itens))
    draw.rounded_rectangle((x, y, x + largura, y + altura), radius=10, outline=LINE, fill=BG)

    draw.rectangle((x, y, x + largura, y + 28), fill=BRAND)
    draw.text((x + 10, y + 5), titulo_grupo, fill=(255, 255, 255), font=font_titulo)

    y_head1 = y + 30
    x_cur = x + 8
    draw.text((x_cur, y_head1), "RKG", fill=INK, font=font_head)
    x_cur += COLS[0][1]
    draw.text((x_cur, y_head1), "PDV", fill=INK, font=font_head)
    x_cur += COLS[1][1]
    draw.text((x_cur, y_head1), "ESPECIALISTA", fill=INK, font=font_head)
    x_cur += COLS[2][1]
    draw.text((x_cur, y_head1), rotulo_janela, fill=INK, font=font_head)
    x_cur += COLS[3][1] + COLS[4][1] + COLS[5][1]
    draw.text((x_cur, y_head1), rotulo_acumulado, fill=INK, font=font_head)

    y_head2 = y + 50
    x_cur = x + 8 + COLS[0][1] + COLS[1][1] + COLS[2][1]
    for rotulo, larg in COLS[3:]:
        draw.text((x_cur, y_head2), rotulo, fill=MUTED, font=font_micro)
        x_cur += larg

    draw.line((x + 6, y + 72, x + largura - 6, y + 72), fill=LINE)

    if not itens:
        draw.text((x + 10, y + 78), "Nenhum PDV neste grupo.", fill=MUTED, font=font_cell)
        return y + altura

    y_row = y + 76
    for idx, item in enumerate(itens[:LIMITE_LINHAS]):
        if idx % 2 == 1:
            draw.rectangle((x + 6, y_row, x + largura - 6, y_row + ALT_LINHA - 2), fill=ALT_ROW)
        vals = [
            str(item.get("posicao") or ""),
            _truncar(str(item.get("pdv") or ""), 24),
            _truncar(str(item.get("especialista_curto") or item.get("especialista") or "—"), 18),
            _fmt_pts(float(item.get("pontos_dia") or 0)),
            str(int(item.get("vb_btu") or 0)),
            str(int(item.get("vb_padrao") or 0)),
            _fmt_pts(float(item.get("pontos") or 0)),
        ]
        x_cur = x + 8
        for (texto, (_, larg)) in zip(vals, COLS):
            draw.text((x_cur + 2, y_row + 5), texto, fill=INK, font=font_cell)
            x_cur += larg
        y_row += ALT_LINHA

    restantes = len(itens) - LIMITE_LINHAS
    if restantes > 0:
        draw.text((x + 10, y_row + 2), f"+ {restantes} PDV(s)", fill=MUTED, font=font_cell)

    return y + altura


def imagem_ranking(ranking: dict, *, limite_por_grupo: int = LIMITE_LINHAS) -> tuple[bytes, str]:
    """Gera PNG no layout da aba RKG_2 (BASE REGULAR | INICIANTES)."""
    del limite_por_grupo  # limite fixo LIMITE_LINHAS na imagem
    periodo = ranking.get("periodo") or {}
    grupos = ranking.get("grupos") or {}
    regular = list(grupos.get(GRUPO_REGULAR) or [])
    iniciante = list(grupos.get(GRUPO_INICIANTE) or [])
    sem_cad = list(grupos.get(GRUPO_SEM_CADASTRO) or [])

    rotulo_janela = _rotulo_janela(periodo)
    rotulo_acumulado = _rotulo_acumulado(periodo)
    inicio = periodo.get("inicio")
    fim = periodo.get("fim")
    periodo_txt = ""
    if inicio and fim:
        periodo_txt = f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"

    font_titulo = _fonte(18, negrito=True)
    font_banner = _fonte(24, negrito=True)
    font_sub = _fonte(14)
    font_head = _fonte(12, negrito=True)
    font_cell = _fonte(11)
    font_micro = _fonte(10)

    tab_w = _largura_tabela()
    altura_corpo = max(_altura_tabela(len(regular)), _altura_tabela(len(iniciante)))
    altura_extra = _altura_tabela(len(sem_cad)) + GAP if sem_cad else 0
    altura = PAD + 72 + altura_corpo + altura_extra + PAD

    img = Image.new("RGB", (LARGURA, altura), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, LARGURA, 72), fill=BRAND)
    draw.text((PAD, 14), "Ranking VB", fill=(255, 255, 255), font=font_banner)
    if periodo_txt:
        draw.text((PAD, 44), periodo_txt, fill=(220, 240, 236), font=font_sub)
    draw.text(
        (LARGURA - PAD - 420, 44),
        "Padrão = 1 pt · BTU = 0,5 pt · atualização até D-1",
        fill=(200, 230, 224),
        font=font_sub,
    )

    y0 = PAD + 72
    x_reg = PAD
    x_ini = PAD + tab_w + GAP
    _desenhar_tabela(
        draw,
        x=x_reg,
        y=y0,
        titulo_grupo="BASE REGULAR",
        itens=regular,
        rotulo_janela=rotulo_janela,
        rotulo_acumulado=rotulo_acumulado,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
        font_micro=font_micro,
    )
    _desenhar_tabela(
        draw,
        x=x_ini,
        y=y0,
        titulo_grupo="INICIANTES",
        itens=iniciante,
        rotulo_janela=rotulo_janela,
        rotulo_acumulado=rotulo_acumulado,
        font_titulo=font_titulo,
        font_head=font_head,
        font_cell=font_cell,
        font_micro=font_micro,
    )

    if sem_cad:
        y_sem = y0 + altura_corpo + GAP
        _desenhar_tabela(
            draw,
            x=PAD,
            y=y_sem,
            titulo_grupo="SEM CLASSIFICAÇÃO SYSMAP",
            itens=sem_cad,
            rotulo_janela=rotulo_janela,
            rotulo_acumulado=rotulo_acumulado,
            font_titulo=font_titulo,
            font_head=font_head,
            font_cell=font_cell,
            font_micro=font_micro,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    nome = f"Ranking_VB_{fim.isoformat()}.png" if fim else "Ranking_VB.png"
    return buf.getvalue(), nome
