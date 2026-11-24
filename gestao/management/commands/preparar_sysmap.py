"""Alias de ``sysmap_sem_cpf``: esvazia CPF no .xls HTML do Sysmap.

Uso::

    python manage.py preparar_sysmap "C:\\Downloads\\Relatório Executivo - Terceiros.xls"
"""

from __future__ import annotations

from gestao.management.commands.sysmap_sem_cpf import Command as SysmapSemCpfCommand


class Command(SysmapSemCpfCommand):
    help = (
        "Prepara o .xls HTML do Sysmap esvaziando a coluna CPF (mesmo que sysmap_sem_cpf). "
        "Mantém extensão .xls e as tabelas intactas — sem abrir o Excel."
    )
