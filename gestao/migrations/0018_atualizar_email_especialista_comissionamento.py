from django.db import migrations
import re


def atualizar_emails_especialista(apps, schema_editor):
    RelatorioComissionamento = apps.get_model("gestao", "RelatorioComissionamento")
    for rel in RelatorioComissionamento.objects.select_related("parceiro__especialista").all():
        msg = (rel.mensagem or "").strip()
        if not msg:
            continue
        email_esp = ""
        if rel.parceiro and rel.parceiro.especialista and rel.parceiro.especialista.email:
            email_esp = rel.parceiro.especialista.email.strip()
        if not email_esp:
            email_esp = "rogerio.pacheco@niointernet.com.br"

        nova_msg = re.sub(
            r"Com c[óo]pia para:\s*[^ \t\n\r]+(?:\s*@@?\s*[^ \t\n\r]+)?\s*e\s*PP-GestaodosParceiros@niointernet\.com\.br",
            f"Com cópia para: {email_esp} e PP-GestaodosParceiros@niointernet.com.br",
            msg,
            flags=re.IGNORECASE,
        )
        if nova_msg != msg:
            rel.mensagem = nova_msg
            rel.save(update_fields=["mensagem"])


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0017_reformatar_planilhas_comissionamento"),
    ]

    operations = [
        migrations.RunPython(atualizar_emails_especialista, reverse_code=migrations.RunPython.noop),
    ]
