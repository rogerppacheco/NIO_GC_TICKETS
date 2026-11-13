from __future__ import annotations

from django.core.management.base import BaseCommand

from tickets.services import (
    fechar_tickets_osab_cancelado,
    resolver_tickets_osab_concluido,
)


class Command(BaseCommand):
    help = "Sincroniza status dos tickets com a OSAB (Concluído -> Resolvido, Cancelado -> Fechado)."

    def handle(self, *args, **options):
        resolvidos = resolver_tickets_osab_concluido()
        fechados = fechar_tickets_osab_cancelado()
        self.stdout.write(
            self.style.SUCCESS(
                f"Atualização concluída: {resolvidos} ticket(s) marcado(s) como Resolvido e {fechados} marcado(s) como Fechado."
            )
        )
