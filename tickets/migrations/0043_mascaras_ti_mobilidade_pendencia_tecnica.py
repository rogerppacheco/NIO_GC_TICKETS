from django.db import migrations, models

TIPOS_CHOICES = [
    ("agendar_reagendar", "Orientações de pendências"),
    ("endereco_doc", "Endereço do Pedido"),
    ("status_pedido", "Status do pedido - agendamento atual"),
    ("prioridade_elite", "Prioridade na instalação (Grupo Elite)"),
    ("reset_senha", "Reset de senha"),
    ("viabilidade", "Consulta de viabilidade (sistema fora)"),
    ("acesso_app", "Chamado acesso App NIO"),
    ("abrir_chamado_ti", "Abrir chamado com TI"),
    (
        "mobilidade_5g_chip",
        "Problema Mobilidade 5G - Solicitação de recebimento do Chip",
    ),
    ("sem_slot", "Sinalização — sem slot / liberação de agenda"),
    ("instalacao_fisica", "Sinalização — instalação física / pendência"),
    ("reparo", "Reparo — internet pós-instalação (até 14 dias)"),
    ("pendencia_indevida", "Pendência indevida"),
    ("pendencia_tecnica", "Pendência técnica"),
    ("agenda_nao_cumprida", "Agenda não cumprida"),
    ("slot_alongado", "Slot alongado"),
    ("reagendamento_nao_solicitado", "Reagendamento não solicitado"),
    ("agendamento_cancelado", "Agendamento cancelado"),
    ("cancelamento_reemissao_indevida", "Cancelamento/reemissão indevida"),
    ("os_nao_atribuida", "OS não atribuída"),
    ("vazamento_dados", "Vazamento de dados"),
    ("gestao_acessos", "Apoio gestão de acessos"),
    ("abrir_ga_brpronto", "Abrir GA para BrPronto"),
    ("outros", "Outros / suporte geral"),
]

TEMPLATE_TI = (
    "*PEDIDO DE AJUDA — ABRIR CHAMADO COM TI*\n\n"
    "*Nome do Gerente de Contas:* {{nome_gc}}\n"
    "*PDV do usuário:* {{pdv}} - {{parceiro}}\n"
    "*TT do vendedor:* {{tt_vendedor}}\n"
    "*TT do backoffice de cadastro:* {{tt_backoffice}}\n"
    "*CNPJ/CPF do cliente:* {{documento}}\n"
    "*Número do Pedido (se houver):* {{pedido}}\n"
    "*Contato:* {{contato}}\n"
    "*Qual etapa do erro:* {{etapa_erro}}\n"
    "*Detalhar o cenário reportado:* {{detalhe_cenario}}\n"
    "*Número do registro do atendimento:* {{numero_registro}}\n\n"
    "*Importante!* É obrigatório anexar as evidências contendo data e hora do erro.\n"
)

TEMPLATE_TI_ANTIGA = (
    "*PEDIDO DE AJUDA — ABRIR CHAMADO COM TI*\n\n"
    "*Nome do Gerente de Contas:* {{nome_gc}}\n"
    "*PDV do usuário:* {{pdv}} - {{parceiro}}\n"
    "*Login BO (se houver):* {{login_bo}}\n"
    "*Login vendedor:* {{login_vendedor}}\n"
    "*TT do vendedor:* {{tt_vendedor}}\n"
    "*TT do backoffice de cadastro:* {{tt_backoffice}}\n"
    "*CNPJ/CPF do cliente:* {{documento}}\n"
    "*Número do Pedido (se houver):* {{pedido}}\n"
    "*Contato:* {{contato}}\n"
    "*Qual etapa do erro:* {{etapa_erro}}\n"
    "*Detalhar o cenário reportado:* {{detalhe_cenario}}\n"
    "*Número do registro do atendimento:* {{numero_registro}}\n\n"
    "*Importante!* É obrigatório anexar as evidências contendo data e hora do erro.\n"
)

TEMPLATE_MOBILIDADE = (
    "*PEDIDO DE AJUDA — PROBLEMA MOBILIDADE 5G — RECEBIMENTO DO CHIP*\n\n"
    "*Nome do Gerente de Contas:* {{nome_gc}}\n"
    "*PDV do usuário:* {{pdv}} - {{parceiro}}\n"
    "*TT do vendedor:* {{tt_vendedor}}\n"
    "*TT do backoffice de cadastro:* {{tt_backoffice}}\n"
    "*CNPJ/CPF do cliente:* {{documento}}\n"
    "*Número do Pedido (se houver):* {{pedido}}\n"
    "*Contato:* {{contato}}\n"
    "*Endereço de entrega do chip:* {{endereco}}\n"
    "*Qual etapa do erro:* {{etapa_erro}}\n"
    "*Detalhar o cenário reportado:* {{detalhe_cenario}}\n"
    "*Número do registro do atendimento:* {{numero_registro}}\n\n"
    "*Importante!* É obrigatório anexar as evidências contendo data e hora do erro.\n"
)

TIPOS_KIT = (
    "pendencia_indevida,pendencia_tecnica,agenda_nao_cumprida,slot_alongado,"
    "reagendamento_nao_solicitado,agendamento_cancelado,"
    "cancelamento_reemissao_indevida,os_nao_atribuida"
)

TIPOS_KIT_ANTIGO = (
    "pendencia_indevida,agenda_nao_cumprida,slot_alongado,"
    "reagendamento_nao_solicitado,agendamento_cancelado,"
    "cancelamento_reemissao_indevida,os_nao_atribuida"
)

NOME_MOBILIDADE = "Problema Mobilidade 5G — recebimento do Chip"


def atualizar_mascaras(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.filter(tipos="abrir_chamado_ti").update(template=TEMPLATE_TI)
    Mascara.objects.filter(nome="Kit operação — OS / pendência / agenda").update(
        tipos=TIPOS_KIT
    )
    Mascara.objects.update_or_create(
        nome=NOME_MOBILIDADE,
        defaults={
            "destino": "GC / TI / Mobilidade 5G",
            "tipos": "mobilidade_5g_chip",
            "template": TEMPLATE_MOBILIDADE,
            "ativo": True,
        },
    )


def reverter_mascaras(apps, schema_editor):
    Mascara = apps.get_model("tickets", "Mascara")
    Mascara.objects.filter(tipos="abrir_chamado_ti").update(template=TEMPLATE_TI_ANTIGA)
    Mascara.objects.filter(nome="Kit operação — OS / pendência / agenda").update(
        tipos=TIPOS_KIT_ANTIGO
    )
    Mascara.objects.filter(nome=NOME_MOBILIDADE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0042_ticket_avaliacao_reincidente"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configrespostatipo",
            name="tipo",
            field=models.CharField(
                choices=TIPOS_CHOICES,
                db_index=True,
                max_length=40,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="tipo",
            field=models.CharField(choices=TIPOS_CHOICES, max_length=40),
        ),
        migrations.RunPython(atualizar_mascaras, reverter_mascaras),
    ]
