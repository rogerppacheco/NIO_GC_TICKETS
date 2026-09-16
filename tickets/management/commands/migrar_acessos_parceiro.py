from django.core.management.base import BaseCommand
from django.db import transaction

from tickets.models import Parceiro
from tickets.seguranca import garantir_conta_parceiro


class Command(BaseCommand):
    help = (
        "Cria User Django para cada PDV: o código vira login e o token legado vira senha hasheada. "
        "PDVs sem token ficam sem conta até alguém gerar senha temporária na ficha."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só lista o que seria feito, sem gravar.",
        )
        parser.add_argument(
            "--gerar-sem-token",
            action="store_true",
            help="Gera senha temporária (troca obrigatória) para PDVs sem token e imprime uma vez.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        gerar_sem_token = opts["gerar_sem_token"]
        com_token = 0
        sem_token = 0
        erros = 0
        geradas = []

        qs = Parceiro.objects.all().order_by("codigo_pdv")
        for parceiro in qs:
            token = (parceiro.token_acesso or "").strip()
            if not token:
                sem_token += 1
                if not gerar_sem_token:
                    self.stdout.write(
                        f"  sem token: {parceiro.codigo_pdv} — {parceiro.nome}"
                    )
                    continue
                if dry:
                    geradas.append((parceiro.codigo_pdv, "(dry-run)"))
                    continue
                try:
                    with transaction.atomic():
                        _user, senha, _ = garantir_conta_parceiro(
                            parceiro, senha=None, must_change=True
                        )
                    if senha:
                        geradas.append((parceiro.codigo_pdv, senha))
                except ValueError as exc:
                    erros += 1
                    self.stderr.write(self.style.ERROR(f"  {parceiro.codigo_pdv}: {exc}"))
                continue

            com_token += 1
            if dry:
                continue
            try:
                with transaction.atomic():
                    garantir_conta_parceiro(parceiro, senha=token, must_change=False)
            except ValueError as exc:
                erros += 1
                self.stderr.write(self.style.ERROR(f"  {parceiro.codigo_pdv}: {exc}"))

        self.stdout.write(
            f"PDVs com token: {com_token}. Sem token: {sem_token}. Erros: {erros}."
        )
        if dry:
            self.stdout.write(self.style.WARNING("Dry-run: nada foi gravado."))
        elif com_token:
            self.stdout.write(
                self.style.SUCCESS(
                    "Token legado virou senha hasheada. Avise os PDVs: código = login, token = senha atual."
                )
            )
        if sem_token and not gerar_sem_token:
            self.stdout.write(
                "PDVs sem token não entram até alguém gerar senha na ficha do parceiro "
                "(ou rode de novo com --gerar-sem-token)."
            )
        if geradas:
            self.stdout.write(self.style.WARNING("Senhas temporárias (anote agora; não gravamos em claro):"))
            for codigo, senha in geradas:
                self.stdout.write(f"  {codigo}\t{senha}")
