from __future__ import annotations

from datetime import date

from django.utils import timezone

from .models import GestaoConfig


def periodo_ativo() -> tuple[int, int]:
    hoje = timezone.localdate()
    ano = _int_config("ANO_ATIVO", hoje.year)
    mes = _int_config("MES_ATIVO", hoje.month)
    if mes < 1 or mes > 12:
        mes = hoje.month
    return ano, mes


def salvar_periodo(ano: int, mes: int) -> None:
    GestaoConfig.objects.update_or_create(chave="ANO_ATIVO", defaults={"valor": str(int(ano))})
    GestaoConfig.objects.update_or_create(chave="MES_ATIVO", defaults={"valor": str(int(mes))})


def _int_config(chave: str, padrao: int) -> int:
    row = GestaoConfig.objects.filter(chave=chave).first()
    if not row or not str(row.valor).strip():
        return padrao
    try:
        return int(row.valor)
    except ValueError:
        return padrao


def anomes(ano: int, mes: int) -> int:
    return int(f"{int(ano):04d}{int(mes):02d}")


def label_anomes(valor: int) -> str:
    texto = str(int(valor))
    if len(texto) != 6:
        return texto
    return f"{texto[4:]}/{texto[:4]}"


def hoje() -> date:
    return timezone.localdate()
