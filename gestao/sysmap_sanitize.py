"""Sanitiza export Sysmap HTML-as-.xls esvaziando a coluna CPF sem quebrar <table>.

Usado no upload (DLP corporativo), no import e no comando `sysmap_sem_cpf`.
Não registra nem devolve valores de CPF.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from .excel import _decodificar_html, _parece_html


@dataclass(frozen=True)
class ResultadoSanitizeCpf:
    conteudo: bytes
    alterou: bool
    coluna_cpf: int | None
    celulas_esvaziadas: int


def _indice_coluna_cpf(table) -> tuple[int | None, int | None]:
    """Retorna (índice da coluna CPF, índice da linha de cabeçalho)."""
    for i, tr in enumerate(table.find_all("tr")):
        cells = tr.find_all(["th", "td"])
        for j, cell in enumerate(cells):
            if cell.get_text(strip=True).casefold() == "cpf":
                return j, i
    return None, None


def esvaziar_cpf_html(conteudo: bytes) -> ResultadoSanitizeCpf:
    """Esvazia células da coluna CPF mantendo cabeçalho e estrutura da tabela."""
    if not conteudo or not _parece_html(conteudo):
        return ResultadoSanitizeCpf(conteudo, False, None, 0)

    soup = BeautifulSoup(_decodificar_html(conteudo), "html5lib")
    table = soup.find("table")
    if table is None:
        return ResultadoSanitizeCpf(conteudo, False, None, 0)

    col, hdr = _indice_coluna_cpf(table)
    if col is None or hdr is None:
        return ResultadoSanitizeCpf(conteudo, False, None, 0)

    esvaziadas = 0
    for i, tr in enumerate(table.find_all("tr")):
        if i <= hdr:
            continue
        cells = tr.find_all(["th", "td"])
        if len(cells) <= col:
            continue
        cell = cells[col]
        if cell.get_text(strip=True):
            cell.clear()
            esvaziadas += 1

    if esvaziadas == 0:
        return ResultadoSanitizeCpf(conteudo, False, col, 0)

    # html5lib reescreve o documento; tables permanecem parseáveis pelo leitor.
    saida = str(soup).encode("utf-8")
    return ResultadoSanitizeCpf(saida, True, col, esvaziadas)


def sanitizar_planilha_sysmap(conteudo: bytes, nome: str = "") -> ResultadoSanitizeCpf:
    """Aplica sanitize quando o arquivo é HTML-as-xls; demais formatos inalterados."""
    _ = nome
    return esvaziar_cpf_html(conteudo)
