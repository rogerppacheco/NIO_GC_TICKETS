from pathlib import Path

from django.core.management.base import BaseCommand

from gestao.pipelines.carteira import processar_carteira


class Command(BaseCommand):
    help = "Importa data credenciamento (DT_CREDENC) da Carteira PP para os parceiros."

    def add_arguments(self, parser):
        parser.add_argument("arquivo", type=str, help="Caminho do Carteira_PP_….xlsx")

    def handle(self, *args, **options):
        path = Path(options["arquivo"])
        if not path.is_file():
            self.stderr.write(self.style.ERROR(f"Arquivo não encontrado: {path}"))
            return
        with path.open("rb") as f:
            resumo = processar_carteira(f, path.name)
        self.stdout.write(
            self.style.SUCCESS(
                f"{resumo['atualizados']} PDV(s) atualizados · "
                f"{resumo['sem_cadastro_n']} sem cadastro · "
                f"{resumo['ignorados']} linha(s) sem data"
            )
        )
        if resumo.get("sem_cadastro"):
            self.stdout.write("Sem match: " + ", ".join(resumo["sem_cadastro"][:12]))
