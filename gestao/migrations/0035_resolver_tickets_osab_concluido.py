from __future__ import annotations

from django.db import migrations


def resolver_tickets_concluidos_na_osab(apps, schema_editor):
    from tickets.services import resolver_tickets_osab_concluido

    Ticket = apps.get_model("tickets", "Ticket")
    VendaOSAB = apps.get_model("gestao", "VendaOSAB")
    resolver_tickets_osab_concluido(Ticket_model=Ticket, VendaOSAB_model=VendaOSAB)


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0034_renomear_dsc_umufibra"),
        ("tickets", "0040_convitereuniao"),
    ]

    operations = [
        migrations.RunPython(
            resolver_tickets_concluidos_na_osab,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
