from __future__ import annotations

import re

from tickets.models import Parceiro

RAZAO_ALIASES_PDV = {
    "GOMES OLIVEIRA TELECOM": "GM TELECOM",
    "LUISA SERVICOS DE TELEFONIA MOVEL": "INOVA MG",
    "VIP TELEFONIA E EQUIPAMENTOS": "POINT CELL",
}


def normalizar_razao(razao: str) -> str:
    texto = str(razao or "").upper().strip()
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    for sufixo in (" LTDA", " LTDA ME", " ME", " EPP", " EIRELI", " SA"):
        if texto.endswith(sufixo):
            texto = texto[: -len(sufixo)].strip()
    return texto


def normalizar_pdv(nome: str) -> str:
    return normalizar_razao(nome)


def indice_parceiros() -> list[tuple[int, str, str]]:
    return [
        (p.id, p.nome, normalizar_pdv(p.nome))
        for p in Parceiro.objects.filter(ativo=True).order_by("nome")
    ]


def resolver_parceiro_id(nome: str, indice: list[tuple[int, str, str]] | None = None) -> int | None:
    """Resolve nome/razão social da planilha para o Parceiro do NIO."""
    if indice is None:
        indice = indice_parceiros()
    bruto = str(nome or "").strip()
    if not bruto:
        return None

    for pid, nome_cad, _ in indice:
        if nome_cad.casefold() == bruto.casefold():
            return pid

    razao_norm = normalizar_razao(bruto)
    if not razao_norm:
        return None

    alvo = RAZAO_ALIASES_PDV.get(razao_norm)
    if not alvo:
        for prefixo, pdv_nome in RAZAO_ALIASES_PDV.items():
            if razao_norm.startswith(prefixo):
                alvo = pdv_nome
                break
    if alvo:
        alvo_norm = normalizar_pdv(alvo)
        for pid, _, pdv_norm in indice:
            if pdv_norm == alvo_norm:
                return pid

    melhor_id = None
    melhor_score = 0
    for pid, _, pdv_norm in indice:
        if not pdv_norm:
            continue
        if razao_norm == pdv_norm:
            return pid
        if razao_norm.startswith(pdv_norm + " ") or pdv_norm in razao_norm.split():
            score = len(pdv_norm)
            if score > melhor_score:
                melhor_score = score
                melhor_id = pid
        elif pdv_norm in razao_norm:
            score = len(pdv_norm) - 1
            if score > melhor_score:
                melhor_score = score
                melhor_id = pid
    return melhor_id


def mapa_nome_parceiro() -> dict[str, int]:
    return {p.nome: p.id for p in Parceiro.objects.filter(ativo=True)}
