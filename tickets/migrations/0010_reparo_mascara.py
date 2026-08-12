from django.db import migrations, models


TIPO_CHOICES = [
    ("agendar_reagendar", "Agendar/Reagendar pedido (7095, 7029, 7037)"),
    ("endereco_doc", "Endereço do Pedido"),
    ("status_pedido", "Status do pedido - agendamento atual"),
    ("prioridade_elite", "Prioridade na instalação (Grupo Elite)"),
    ("reset_senha", "Reset de senha"),
    ("viabilidade", "Consulta de viabilidade (sistema fora)"),
    ("acesso_app", "Chamado acesso App NIO"),
    ("abrir_chamado_ti", "Abrir chamado com TI"),
    ("sem_slot", "Sinalização — sem slot / liberação de agenda"),
    ("instalacao_fisica", "Sinalização — instalação física / pendência"),
    ("reparo", "Reparo — internet pós-instalação (até 14 dias)"),
    ("outros", "Outros / suporte geral"),
]

MASCARA_REPARO = {
    "nome": "Reparo — OS recém instalada",
    "destino": "Grupo Elite / Reparo",
    "tipos": "reparo",
    "template": (
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
    ),
}


def criar_mascara_reparo(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.update_or_create(
        nome=MASCARA_REPARO["nome"],
        defaults={
            "destino": MASCARA_REPARO["destino"],
            "tipos": MASCARA_REPARO["tipos"],
            "template": MASCARA_REPARO["template"],
            "ativo": True,
        },
    )


def remover_mascara_reparo(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.filter(nome=MASCARA_REPARO["nome"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0009_config_resposta_tipo"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="nome_cliente",
            field=models.CharField(blank=True, max_length=180, verbose_name="Nome do cliente"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="data_instalacao",
            field=models.DateField(blank=True, null=True, verbose_name="Data da instalação"),
        ),
        migrations.AddField(
            model_name="ticket",
            name="data_alternativa",
            field=models.DateField(
                blank=True,
                help_text="Segunda opção de data para retorno do técnico (reparo).",
                null=True,
                verbose_name="Opção 2 — Data",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="turno_alternativo",
            field=models.CharField(
                blank=True,
                choices=[
                    ("manha", "Manhã"),
                    ("tarde", "Tarde"),
                    ("integral", "Integral / indiferente"),
                ],
                max_length=20,
                verbose_name="Opção 2 — Turno",
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="tipo",
            field=models.CharField(choices=TIPO_CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name="configrespostatipo",
            name="tipo",
            field=models.CharField(
                choices=TIPO_CHOICES, db_index=True, max_length=40, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="mascara",
            name="template",
            field=models.TextField(
                help_text=(
                    "Variáveis: {{protocolo}} {{parceiro}} {{pdv}} {{tipo}} {{pedido}} "
                    "{{documento}} {{endereco}} {{cep}} {{fachada}} {{data}} {{turno}} "
                    "{{data_2}} {{turno_2}} {{nome_cliente}} {{data_instalacao}} {{nome_gc}} "
                    "{{descricao}} {{observacoes}} {{solicitante}} {{contato}} {{tt}} "
                    "{{tt_vendedor}} {{tt_backoffice}} {{os}}"
                )
            ),
        ),
        migrations.RunPython(criar_mascara_reparo, remover_mascara_reparo),
    ]
