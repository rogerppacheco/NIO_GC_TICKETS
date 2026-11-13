from django.db import migrations

TEMPLATE_REPARO = (
    "*MÁSCARA PADRÃO DE ACIONAMENTO PARA REPAROS DE OSS RECÉM INSTALADAS:*\n\n"
    "- *OS:* {{os}}\n"
    "- *NOME DO CLIENTE:* {{nome_cliente}}\n"
    "- *CPF DO CLIENTE:* {{documento}}\n"
    "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
    "- *CONTATO DO CLIENTE:* {{contato}}\n"
    "- *PDV:* {{pdv}} - {{parceiro}}\n"
    "- *GC:* {{nome_gc}}\n"
    "- *DATA INSTALAÇÃO:* {{data_instalacao}}\n"
    "- *DATA E HORÁRIO AGENDADO COM O CLIENTE:*\n"
    "  1) {{data}} - {{turno}}\n"
    "  2) {{data_2}} - {{turno_2}}\n"
    "- *SOLICITAÇÃO:* {{descricao}}\n"
)

TEMPLATE_REPARO_ANTIGA = (
    "*MÁSCARA PADRÃO DE ACIONAMENTO PARA REPAROS DE OSS RECÉM INSTALADAS:*\n\n"
    "- *OS:* {{os}}\n"
    "- *NOME DO CLIENTE:* {{nome_cliente}}\n"
    "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
    "- *CONTATO DO CLIENTE:* {{contato}}\n"
    "- *PDV:* {{pdv}} - {{parceiro}}\n"
    "- *GC:* {{nome_gc}}\n"
    "- *DATA INSTALAÇÃO:* {{data_instalacao}}\n"
    "- *DATA E HORÁRIO AGENDADO COM O CLIENTE:*\n"
    "  1) {{data}} - {{turno}}\n"
    "  2) {{data_2}} - {{turno_2}}\n"
    "- *SOLICITAÇÃO:* {{descricao}}\n"
)


def atualizar_mascara_reparo(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    qs = Mascara.objects.filter(tipos="reparo")
    if qs.exists():
        qs.update(template=TEMPLATE_REPARO)


def reverter_mascara_reparo(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.filter(tipos="reparo").update(template=TEMPLATE_REPARO_ANTIGA)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0040_convitereuniao"),
    ]

    operations = [
        migrations.RunPython(atualizar_mascara_reparo, reverter_mascara_reparo),
    ]
