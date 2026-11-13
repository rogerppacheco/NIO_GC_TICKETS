from __future__ import annotations

from django.db import migrations


def fechar_tickets_cancelados_na_osab(apps, schema_editor):
    from tickets.services import fechar_tickets_osab_cancelado

    Ticket = apps.get_model("tickets", "Ticket")
    VendaOSAB = apps.get_model("gestao", "VendaOSAB")
    fechar_tickets_osab_cancelado(Ticket_model=Ticket, VendaOSAB_model=VendaOSAB)


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0035_resolver_tickets_osab_concluido"),
        ("tickets", "0040_convitereuniao"),
    ]

    operations = [
        migrations.RunPython(
            fechar_tickets_cancelados_na_osab,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
