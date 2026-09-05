from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from tickets.models import ContatoParceiro, Mascara, Parceiro, TipoDemanda


PARCEIROS = [
    ("1068281", "INOVA MG"),
    ("1067100", "RECORD"),
    ("1068271", "MILA"),
    ("1068279", "APOLO"),
    ("1068432", "HF SERVIÇOS"),
    ("1068966", "ALLVO"),
]

MASCARAS = [
    {
        "nome": "Grupo Elite — Prioridade instalação",
        "destino": "Grupo Elite",
        "tipos": TipoDemanda.PRIORIDADE_ELITE,
        "template": (
            "*MÁSCARA PADRÃO DE ACIONAMENTO - GRUPO ELITE:*\n\n"
            "- *OS:* {{os}}\n"
            "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
            "- *NOME DO PDV:* {{pdv}} - {{parceiro}}\n"
            "- *DATA AGENDADA:* {{data}} - {{turno}}\n"
            "- *DESCRIÇÃO DETALHADA DA SOLICITAÇÃO:* {{descricao}}\n"
        ),
    },
    {
        "nome": "Abrir chamado com TI",
        "destino": "GC / TI",
        "tipos": TipoDemanda.ABRIR_CHAMADO_TI,
        "template": (
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
        ),
    },
    {
        "nome": "Sinalização — Sem slot / liberação de agenda",
        "destino": "GC / Diretoria",
        "tipos": TipoDemanda.SEM_SLOT,
        "enviar_whatsapp": True,
        "template": (
            "Sem SLOT em {{uf}}\n\n"
            "Pedido: {{pedido}}\n"
            "Endereço: {{endereco}}\n"
            "Data e turno que o cliente deseja: {{data}} - {{turno}}\n"
            "Tel. de contato: {{contato}}\n"
        ),
    },
    {
        "nome": "Sinalização — Instalação física / pendência",
        "destino": "GC / Esteira",
        "tipos": TipoDemanda.INSTALACAO_FISICA,
        "template": (
            "*SINALIZAÇÃO - INSTALAÇÃO FÍSICA / PENDÊNCIA NO SISTEMA:*\n\n"
            "- *OS:* {{os}}\n"
            "- *ENDEREÇO COMPLETO:* {{endereco}}\n"
            "- *NOME DO PDV:* {{pdv}} - {{parceiro}}\n"
            "- *DATA INSTALAÇÃO FÍSICA (NO CLIENTE):* {{data}}\n"
            "- *CONTEXTO:* Houve instalação física; o pedido segue com pendência na esteira.\n"
            "- *DESCRIÇÃO DETALHADA:* {{descricao}}\n"
        ),
    },
    {
        "nome": "Reparo — OS recém instalada",
        "destino": "Grupo Elite / Reparo",
        "tipos": TipoDemanda.REPARO,
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
    },
    {
        "nome": "BO Agendamento / Reagendamento",
        "destino": "BO Agendamento (7095/7029/7037)",
        "tipos": TipoDemanda.AGENDAR_REAGENDAR,
        "template": (
            "*BO AGENDAR/REAGENDAR*\n"
            "Protocolo: {{protocolo}}\n"
            "PDV: {{pdv}} — {{parceiro}}\n"
            "Pedido(s):\n{{pedidos}}\n"
            "CPF: {{documento}}\n"
            "Data desejada: {{data}} | Turno: {{turno}}\n"
            "Contato: {{solicitante}} / {{contato}}\n"
            "Obs: {{observacoes}}\n"
        ),
    },
    {
        "nome": "Consulta viabilidade",
        "destino": "Viabilidade",
        "tipos": TipoDemanda.VIABILIDADE,
        "template": (
            "*CONSULTA VIABILIDADE*\n"
            "Protocolo: {{protocolo}}\n"
            "PDV: {{pdv}} — {{parceiro}}\n"
            "CEP: {{cep}}\n"
            "Logradouro: {{logradouro}}\n"
            "Nº fachada: {{fachada}}\n"
            "Bairro: {{bairro}}\n"
            "Cidade/UF: {{cidade}} - {{uf}}\n"
            "Endereço: {{endereco}}\n"
            "Contato: {{solicitante}} / {{contato}}\n"
        ),
    },
    {
        "nome": "Reset de senha",
        "destino": "Reset senha",
        "tipos": TipoDemanda.RESET_SENHA,
        "template": (
            "*RESET DE SENHA*\n"
            "Protocolo: {{protocolo}}\n"
            "PDV: {{pdv}} — {{parceiro}}\n"
            "TT: {{tt}}\n"
            "Solicitante: {{solicitante}} | Contato: {{contato}}\n"
        ),
    },
    {
        "nome": "Acesso App NIO",
        "destino": "Suporte App NIO",
        "tipos": TipoDemanda.ACESSO_APP,
        "template": (
            "*CHAMADO ACESSO APP NIO*\n"
            "Protocolo: {{protocolo}}\n"
            "PDV: {{pdv}} — {{parceiro}}\n"
            "CPF: {{documento}}\n"
            "Descrição: {{descricao}}\n"
            "Contato: {{solicitante}} / {{contato}}\n"
        ),
    },
]


class Command(BaseCommand):
    help = "Carrega parceiros e máscaras iniciais + cria usuário admin se informado"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default="admin123")
        parser.add_argument("--email", default="admin@example.com")

    def handle(self, *args, **options):
        if Parceiro.objects.exists():
            self.stdout.write(
                "parceiros: já existem — seed não recria PDVs excluídos nem reativa inativos"
            )
        else:
            for codigo, nome in PARCEIROS:
                parceiro, _ = Parceiro.objects.get_or_create(
                    codigo_pdv=codigo,
                    defaults={"nome": nome, "ativo": True},
                )
                if not parceiro.contatos.exists():
                    ContatoParceiro.objects.create(
                        parceiro=parceiro,
                        nome=f"Contato {nome}",
                        ativo=True,
                    )
            self.stdout.write(self.style.SUCCESS(f"{len(PARCEIROS)} parceiros ok"))

        # Migra contato legado do PDV → ContatoParceiro, se ainda não existir
        for p in Parceiro.objects.all():
            if p.contato_nome and not p.contatos.filter(nome=p.contato_nome).exists():
                ContatoParceiro.objects.create(
                    parceiro=p,
                    nome=p.contato_nome,
                    email=p.email or "",
                    telefone=p.telefone or "",
                    ativo=True,
                )

        for data in MASCARAS:
            Mascara.objects.update_or_create(
                nome=data["nome"],
                defaults={
                    "destino": data["destino"],
                    "tipos": data["tipos"],
                    "template": data["template"],
                    "enviar_whatsapp": data.get("enviar_whatsapp", False),
                    "ativo": True,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"{len(MASCARAS)} máscaras ok"))

        from tickets.demanda_campos import garantir_config_resposta_padrao

        n = garantir_config_resposta_padrao()
        self.stdout.write(self.style.SUCCESS(f"configs resposta: {n} novas"))

        User = get_user_model()
        username = options["username"]
        from tickets.models import PerfilStaff

        if not User.objects.filter(username=username).exists():
            user = User.objects.create_superuser(
                username=username,
                email=options["email"],
                password=options["password"],
            )
            PerfilStaff.objects.get_or_create(
                user=user, defaults={"papel": PerfilStaff.Papel.GESTOR}
            )
            self.stdout.write(self.style.SUCCESS(f"Superuser {username} criado"))
        else:
            user = User.objects.get(username=username)
            PerfilStaff.objects.get_or_create(
                user=user, defaults={"papel": PerfilStaff.Papel.GESTOR}
            )
            self.stdout.write(f"Superuser {username} já existe")
