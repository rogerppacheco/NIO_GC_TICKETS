"""Gera cópia do Relatório Executivo Sysmap (.xls HTML) com coluna CPF vazia.

Uso (no PC, antes do upload corporativo se o DLP bloquear o original)::

    python manage.py sysmap_sem_cpf "C:\\Downloads\\Relatório Executivo - Terceiros.xls"

Saída padrão: mesmo diretório, sufixo ``_sem_cpf.xls`` (ainda HTML, com <table>).
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from gestao.sysmap_sanitize import sanitizar_planilha_sysmap


class Command(BaseCommand):
    help = (
        "Esvazia a coluna CPF de um .xls HTML do Sysmap preservando as tabelas. "
        "Use o arquivo gerado no upload quando o DLP bloquear o original."
    )

    def add_arguments(self, parser):
        parser.add_argument("caminho", type=str, help="Caminho do .xls original do Sysmap")
        parser.add_argument(
            "-o",
            "--saida",
            type=str,
            default="",
            help="Arquivo de saída (default: <nome>_sem_cpf.xls)",
        )

    def handle(self, *args, **options):
        origem = Path(options["caminho"]).expanduser()
        if not origem.is_file():
            raise CommandError(f"Arquivo não encontrado: {origem}")

        bruto = origem.read_bytes()
        resultado = sanitizar_planilha_sysmap(bruto, origem.name)
        if resultado.coluna_cpf is None:
            raise CommandError(
                "Nenhuma coluna CPF encontrada (ou o arquivo não é HTML-as-xls do Sysmap)."
            )

        if options["saida"]:
            destino = Path(options["saida"]).expanduser()
        else:
            destino = origem.with_name(f"{origem.stem}_sem_cpf.xls")

        destino.write_bytes(resultado.conteudo)
        self.stdout.write(
            self.style.SUCCESS(
                f"OK: {destino.name} "
                f"(coluna CPF={resultado.coluna_cpf}, "
                f"células esvaziadas={resultado.celulas_esvaziadas}, "
                f"{destino.stat().st_size} bytes)"
            )
        )
        if not resultado.alterou:
            self.stdout.write("Nenhuma célula de CPF tinha valor — cópia equivalente gerada.")
