from __future__ import annotations

import re

from django.db import connection
from django.db.models import F

from .vtal_models import VtalDadosViabilidade, VtalFonteDados


def vtal_disponivel() -> bool:
    if connection.vendor != "postgresql":
        return False
    try:
        return VtalFonteDados.objects.filter(ativa=True).exists()
    except Exception:
        return False


def normalizar_cep(valor: str | None) -> str | None:
    if not valor:
        return None
    digits = re.sub(r"[^0-9]", "", str(valor))
    return digits[:8] if digits else None


def normalizar_fachada(valor: str | None) -> str | None:
    if not valor:
        return None
    normalized = re.sub(r"[^0-9a-zA-Z]", "", str(valor))
    return normalized.lower() if normalized else None


def fontes_vtal_ativas() -> list[VtalFonteDados]:
    try:
        return list(VtalFonteDados.objects.filter(ativa=True).order_by("ordem", "nome"))
    except Exception:
        return []


def consultar_viabilidade(
    *,
    fonte: VtalFonteDados,
    cep: str | None,
    numero_fachada: str | None,
) -> list[VtalDadosViabilidade]:
    cep_norm = normalizar_cep(cep)
    fachada_norm = normalizar_fachada(numero_fachada)
    if not cep_norm and not fachada_norm:
        return []

    qs = VtalDadosViabilidade.objects.filter(fonte=fonte)
    if cep_norm:
        qs = qs.filter(cep_normalizado=cep_norm)
    if fachada_norm:
        qs = qs.filter(fachada_normalizada=fachada_norm)

    last_sheet = fonte.import_last_sheet_row_count or fonte.import_last_sheet_row_number
    if last_sheet:
        qs = qs.filter(
            numero_linha_planilha__isnull=False,
            numero_linha_planilha__lte=last_sheet,
        )

    return list(
        qs.order_by(
            "-carimbo_data_hora",
            F("numero_linha_planilha").desc(nulls_last=True),
            "-id",
        )[:20]
    )
