from __future__ import annotations

from django.core.management.base import BaseCommand

from tickets.services import resolver_tickets_osab_concluido


class Command(BaseCommand):
    help = "Atualiza para Resolvido todos os tickets cujo pedido está com situação OSAB = Concluído."

    def handle(self, *args, **options):
        total = resolver_tickets_osab_concluido()
        self.stdout.write(
            self.style.SUCCESS(
                f"Atualização concluída: {total} ticket(s) marcado(s) como Resolvido."
            )
        )
