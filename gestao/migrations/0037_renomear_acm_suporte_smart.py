from __future__ import annotations

from django.db import migrations


def renomear_acm_para_suporte_smart(apps, schema_editor):
    Parceiro = apps.get_model("tickets", "Parceiro")
    VendaOSAB = apps.get_model("gestao", "VendaOSAB")

    antigo = Parceiro.objects.filter(nome__iexact="ACM COMERCIO").order_by("id").first()
    novo = Parceiro.objects.filter(nome__iexact="SUPORTE SMART").order_by("id").first()
    if not antigo and not novo:
        return
    if antigo and not novo:
        antigo.nome = "SUPORTE SMART"
        antigo.save(update_fields=["nome"])
        alvo_id = antigo.id
    elif antigo and novo and antigo.id != novo.id:
        VendaOSAB.objects.filter(parceiro_id=antigo.id).update(parceiro_id=novo.id)
        alvo_id = novo.id
    else:
        alvo_id = novo.id if novo else None

    VendaOSAB.objects.filter(pdv_nome__iexact="ACM COMERCIO").update(pdv_nome="SUPORTE SMART")
    if alvo_id is not None:
        VendaOSAB.objects.filter(
            parceiro__isnull=True,
            pdv_nome__iexact="SUPORTE SMART",
        ).update(parceiro_id=alvo_id)


def reverter_suporte_smart_para_acm(apps, schema_editor):
    Parceiro = apps.get_model("tickets", "Parceiro")
    VendaOSAB = apps.get_model("gestao", "VendaOSAB")
    suporte = Parceiro.objects.filter(nome__iexact="SUPORTE SMART").order_by("id").first()
    if not suporte:
        return
    if Parceiro.objects.filter(nome__iexact="ACM COMERCIO").exclude(pk=suporte.id).exists():
        return
    suporte.nome = "ACM COMERCIO"
    suporte.save(update_fields=["nome"])
    VendaOSAB.objects.filter(pdv_nome__iexact="SUPORTE SMART").update(pdv_nome="ACM COMERCIO")


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0036_fechar_tickets_osab_cancelado"),
        ("tickets", "0042_ticket_avaliacao_reincidente"),
    ]

    operations = [
        migrations.RunPython(renomear_acm_para_suporte_smart, reverter_suporte_smart_para_acm),
    ]
