from django.db import migrations

TEMPLATE_ELITE = (
    "*MÁSCARA PADRÃO DE ACIONAMENTO - GRUPO ELITE:*\n\n"
    "- *OS:* {{os}}\n"
    "- *NOME/TITULAR:* {{nome_cliente}}\n"
    "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
    "- *NOME DO PDV:* {{pdv}} - {{parceiro}}\n"
    "- *DATA AGENDADA NO SISTEMA:* {{data}} - {{turno}}\n"
    "- *NOME DE CONTATO DA INSTALAÇÃO:* {{solicitante}}\n"
    "- *TELEFONE DE CONTATO:* {{contato}}\n"
    "- *DESCRIÇÃO DETALHADA DA SOLICITAÇÃO:* {{descricao}}\n"
)

TEMPLATE_ELITE_ANTIGA = (
    "*MÁSCARA PADRÃO DE ACIONAMENTO - GRUPO ELITE:*\n\n"
    "- *OS:* {{os}}\n"
    "- *NOME/TITULAR:* {{nome_cliente}}\n"
    "- *CPF TITULAR:* {{documento}}\n"
    "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
    "- *NOME DO PDV:* {{pdv}} - {{parceiro}}\n"
    "- *DATA AGENDADA NO SISTEMA:* {{data}} - {{turno}}\n"
    "- *NOME DE CONTATO DA INSTALAÇÃO:* {{solicitante}}\n"
    "- *TELEFONE DE CONTATO:* {{contato}}\n"
    "- *DESCRIÇÃO DETALHADA DA SOLICITAÇÃO:* {{descricao}}\n"
)


def atualizar_mascara_elite(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    qs = Mascara.objects.filter(tipos="prioridade_elite")
    if qs.exists():
        qs.update(template=TEMPLATE_ELITE)


def reverter_mascara_elite(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.filter(tipos="prioridade_elite").update(template=TEMPLATE_ELITE_ANTIGA)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0043_mascaras_ti_mobilidade_pendencia_tecnica"),
    ]

    operations = [
        migrations.RunPython(atualizar_mascara_elite, reverter_mascara_elite),
    ]
