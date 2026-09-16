from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from .acesso import eh_gestor, qs_equipe, qs_especialistas, tickets_visiveis
from .demanda_campos import (
    LABELS_POR_TIPO,
    TIPOS_KIT_OPERACAO,
    contexto_demanda_para_resposta,
    montar_abas_tratamento,
    schema_para_js,
    schema_tipo,
)
from .forms import LoginForm, MultipleFileField, ParceiroForm, TicketCreateForm, TicketTreatForm
from .models import (
    Anexo,
    Mascara,
    Mensagem,
    Parceiro,
    PerfilStaff,
    Recorrencia,
    StatusTicket,
    Ticket,
    TipoDemanda,
    VariacaoSemSlot,
    formatar_duracao,
)


STORAGES_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


class MultipleFileFieldTests(SimpleTestCase):
    def test_aceita_lista_de_arquivos(self):
        campo = MultipleFileField(required=False)
        arquivo = SimpleUploadedFile("evidencia.jpeg", b"fake-image", content_type="image/jpeg")
        limpo = campo.clean([arquivo])
        self.assertEqual(len(limpo), 1)
        self.assertEqual(limpo[0].name, "evidencia.jpeg")

    def test_lista_vazia_quando_opcional(self):
        campo = MultipleFileField(required=False)
        self.assertEqual(campo.clean([]), [])


class TicketCreateEvidenciasTests(SimpleTestCase):
    def test_abrir_chamado_ti_aceita_anexo_via_getlist(self):
        """request.FILES.getlist devolve lista; FileField padrão acusava encoding."""
        arquivo = SimpleUploadedFile("10843955.jpeg", b"conteudo", content_type="image/jpeg")
        files = MultiValueDict({"evidencias": [arquivo]})
        form = TicketCreateForm(
            data={
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
                "pedido": "10843955",
                "documento_cliente": "37161261600",
                "solicitante_nome": "WALTER",
                "solicitante_contato": "11999999999",
                "tt_vendedor": "TT832209",
                "tt_backoffice": "TT832207",
                "observacoes": "AGENDAMENTO REALIZADO NAO ATRIBUI",
                "descricao": "PEDIDO NAO GEROU ATRIBUICAO",
            },
            files=files,
        )
        form.is_valid()
        self.assertNotIn("evidencias", form.errors)
        erros = " ".join(str(e) for e in form.errors.get("evidencias", []))
        self.assertNotIn("codificação", erros)
        self.assertEqual(len(form.cleaned_data.get("evidencias") or []), 1)


@override_settings(STORAGES=STORAGES_TESTE)
class DemandaComAnexoNotificacaoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec = User.objects.create_user(
            "spec_anexo",
            "spec.anexo@x.com",
            "x",
            is_staff=True,
            first_name="Ana Anexo",
        )
        PerfilStaff.objects.create(
            user=self.spec,
            papel=PerfilStaff.Papel.ESPECIALISTA,
            whatsapp="5531999990000",
        )
        self.pdv = Parceiro.objects.create(
            codigo_pdv="ANX1", nome="PDV Anexo", especialista=self.spec
        )
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.ACESSO_APP,
            documento_cliente="12345678901",
            descricao="Erro ao abrir o app",
        )

    def _anexo(self, nome="print.jpeg"):
        return Anexo.objects.create(
            ticket=self.ticket,
            arquivo=SimpleUploadedFile(nome, b"conteudo-img", content_type="image/jpeg"),
            nome_original=nome,
        )

    def test_resumo_traz_campos_preenchidos_pelo_parceiro(self):
        from tickets.services import resumo_demanda_parceiro

        self._anexo()
        texto = resumo_demanda_parceiro(self.ticket)
        self.assertIn("Demanda com anexo", texto)
        self.assertIn(self.ticket.protocolo, texto)
        self.assertIn("PDV Anexo", texto)
        self.assertIn("12345678901", texto)
        self.assertIn("Erro ao abrir o app", texto)
        self.assertIn("print.jpeg", texto)
        self.assertNotIn("Pedido / OS", texto)

    def test_sem_anexo_nao_envia(self):
        from tickets.services import notificar_demanda_com_anexo

        self.assertEqual(notificar_demanda_com_anexo(self.ticket), 0)

    def test_envia_resumo_e_arquivo_ao_especialista(self):
        from unittest.mock import patch

        from gestao.messaging.syncwa import SyncWAResult
        from tickets.services import notificar_demanda_com_anexo

        self._anexo("evidencia.png")
        fake = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake) as mock_txt, \
             patch("gestao.messaging.syncwa.enviar_documento", return_value=fake) as mock_doc:
            n = notificar_demanda_com_anexo(self.ticket)
        self.assertGreaterEqual(n, 2)
        mock_txt.assert_called_once()
        jid, texto = mock_txt.call_args.args
        self.assertEqual(jid, "5531999990000")
        self.assertIn(self.ticket.protocolo, texto)
        self.assertIn("12345678901", texto)
        mock_doc.assert_called_once()
        self.assertEqual(mock_doc.call_args.args[0], "5531999990000")
        self.assertEqual(mock_doc.call_args.kwargs["file_name"], "evidencia.png")
        self.assertEqual(mock_doc.call_args.kwargs["conteudo"], b"conteudo-img")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)
        self.assertTrue(
            self.ticket.mensagens.filter(interno=True, corpo__contains="anexo").exists()
        )

    def test_especialista_nao_recebe_quando_ele_mesmo_abre(self):
        from unittest.mock import patch

        from tickets.services import notificar_demanda_com_anexo

        self._anexo()
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto") as mock_txt:
            n = notificar_demanda_com_anexo(self.ticket, ator=self.spec)
        self.assertEqual(n, 0)
        mock_txt.assert_not_called()

    def test_portal_com_evidencia_dispara_envio(self):
        from unittest.mock import patch

        from tickets.models import ContatoParceiro
        from tickets.seguranca import garantir_conta_parceiro

        contato = ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Empresário Loja", cargo="Empresário"
        )
        user_pdv, _, _ = garantir_conta_parceiro(self.pdv, senha="token-anx", must_change=False)
        self.client.force_login(user_pdv)
        session = self.client.session
        session["contato_id"] = contato.id
        session.save()
        with patch("tickets.views.notificar_demanda_com_anexo") as mock_n, \
             patch("tickets.views.notificar_mascaras_por_email", return_value=0), \
             patch("tickets.views.notificar_mascaras_por_whatsapp", return_value=0):
            r = self.client.post(
                reverse("abrir_demanda_form"),
                {
                    "tipo": TipoDemanda.ACESSO_APP,
                    "documento_cliente": "99988877766",
                    "descricao": "Tela travou",
                    "evidencias": SimpleUploadedFile(
                        "erro.jpeg", b"img", content_type="image/jpeg"
                    ),
                },
            )
        self.assertEqual(r.status_code, 302)
        mock_n.assert_called_once()
        ticket = mock_n.call_args.kwargs.get("ticket") or mock_n.call_args.args[0]
        self.assertTrue(ticket.anexos.exists())
        self.assertEqual(ticket.documento_cliente, "99988877766")


class PrioridadeEliteDemandaTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1069399", nome="CONNECTX")

    def _dados(self, **extra):
        data = {
            "parceiro": str(self.pdv.pk),
            "tipo": TipoDemanda.PRIORIDADE_ELITE,
            "pedido": "11250952",
            "cep": "72885095",
            "numero_fachada": "16",
            "data_desejada": "2026-09-14",
            "turno": "integral",
            "solicitante_nome": "Maria Silva",
            "solicitante_contato": "61999999999",
            "descricao": (
                "cliente contratou mas só deseja a instalação se for na segunda feira"
            ),
        }
        data.update(extra)
        return data

    def test_schema_pede_data_agendada_e_contato(self):
        cfg = schema_tipo(TipoDemanda.PRIORIDADE_ELITE)
        self.assertIn("solicitante_nome", cfg["campos"])
        self.assertIn("solicitante_contato", cfg["campos"])
        self.assertIn("solicitante_nome", cfg["obrigatorios"])
        self.assertIn("solicitante_contato", cfg["obrigatorios"])
        labels = schema_para_js()[TipoDemanda.PRIORIDADE_ELITE]["labels"]
        self.assertEqual(labels["data_desejada"], "Data agendada no sistema")
        self.assertEqual(labels["solicitante_nome"], "Nome de contato da instalação")
        self.assertEqual(
            labels["solicitante_contato"], "Telefone de contato com o cliente"
        )
        self.assertEqual(
            LABELS_POR_TIPO[TipoDemanda.AGENDAR_REAGENDAR].get("data_desejada"),
            None,
        )

    def test_formulario_exige_nome_e_telefone(self):
        form = TicketCreateForm(
            data=self._dados(solicitante_nome="", solicitante_contato="")
        )
        self.assertFalse(form.is_valid())
        self.assertIn("solicitante_nome", form.errors)
        self.assertIn("solicitante_contato", form.errors)
        self.assertIn(
            "Nome de contato da instalação", str(form.errors["solicitante_nome"])
        )
        self.assertIn(
            "Telefone de contato com o cliente",
            str(form.errors["solicitante_contato"]),
        )

    def test_formulario_valido_com_contato(self):
        form = TicketCreateForm(data=self._dados())
        self.assertTrue(form.is_valid(), form.errors)

    def test_mascara_inclui_data_agendada_e_contato(self):
        from tickets.management.commands.seed_nio import MASCARAS
        from tickets.services import render_mascara

        template = next(
            m["template"]
            for m in MASCARAS
            if m["tipos"] == TipoDemanda.PRIORIDADE_ELITE
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.PRIORIDADE_ELITE,
            pedido="11250952",
            endereco_completo=(
                "Quadra 26, 16, apartamento 203, Parque Nápolis A, "
                "Cidade Ocidental - GO, 72885-095"
            ),
            data_desejada="2026-09-14",
            turno="integral",
            solicitante_nome="Maria Silva",
            solicitante_contato="61999999999",
            descricao="cliente contratou mas só deseja a instalação se for na segunda feira",
        )
        texto = render_mascara(Mascara(template=template), ticket)
        self.assertIn("DATA AGENDADA NO SISTEMA", texto)
        self.assertIn("NOME DE CONTATO DA INSTALAÇÃO", texto)
        self.assertIn("TELEFONE DE CONTATO", texto)
        self.assertIn("Maria Silva", texto)
        self.assertIn("61999999999", texto)
        self.assertIn("11250952", texto)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_pagina_nova_demanda_traz_labels_elite(self):
        User = get_user_model()
        user = User.objects.create_superuser("elite_admin", "e@x.com", "x")
        PerfilStaff.objects.create(user=user, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(user)
        resp = self.client.get(reverse("ticket_criar"))
        self.assertEqual(resp.status_code, 200)
        corpo = resp.content.decode("utf-8")
        self.assertIn("Data agendada no sistema", corpo)
        self.assertIn("Nome de contato da instala", corpo)
        self.assertIn("Telefone de contato com o cliente", corpo)


class MatrizOperacaoDemandaTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1069400", nome="MATRIZ PDV")

    def _kit(self, tipo=TipoDemanda.PENDENCIA_INDEVIDA, **extra):
        data = {
            "parceiro": str(self.pdv.pk),
            "tipo": tipo,
            "pedido": "11260001",
            "sa": "SA-9001",
            "nome_cliente": "Cliente Teste",
            "solicitante_nome": "Ana Contato",
            "solicitante_contato": "61988887777",
            "cep": "72885095",
            "numero_fachada": "10",
            "cidade": "Brasília",
            "data_desejada": "2026-09-20",
            "tipo_pendencia": "Documentação",
            "recorrencia": Recorrencia.NAO,
            "descricao": "Pendência lançada sem lastro no pedido.",
        }
        data.update(extra)
        return data

    def test_agendar_passa_a_orientacoes_de_pendencias(self):
        self.assertEqual(
            TipoDemanda.AGENDAR_REAGENDAR.label, "Orientações de pendências"
        )
        cfg = schema_tipo(TipoDemanda.AGENDAR_REAGENDAR)
        self.assertEqual(
            cfg["obrigatorios"],
            ["pedido", "documento_cliente", "data_desejada", "turno"],
        )
        self.assertIn("observacoes", cfg["campos"])

    def test_abrir_chamado_ti_exige_contato_e_documento(self):
        cfg = schema_tipo(TipoDemanda.ABRIR_CHAMADO_TI)
        self.assertIn("solicitante_contato", cfg["obrigatorios"])
        self.assertIn("documento_cliente", cfg["obrigatorios"])
        self.assertNotIn("pedido", cfg["obrigatorios"])
        form = TicketCreateForm(
            data={
                "parceiro": str(self.pdv.pk),
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
                "tt_vendedor": "TT1",
                "tt_backoffice": "TT2",
                "observacoes": "Etapa 3",
                "descricao": "Erro no cadastro",
            },
            files=MultiValueDict(
                {
                    "evidencias": [
                        SimpleUploadedFile("e.jpeg", b"x", content_type="image/jpeg")
                    ]
                }
            ),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("solicitante_contato", form.errors)
        self.assertIn("documento_cliente", form.errors)

    def test_schema_js_sem_slot_tem_variacao_e_labels(self):
        js = schema_para_js()[TipoDemanda.SEM_SLOT]
        self.assertEqual(
            js["visivel_se"]["data_alternativa"]["valor"],
            VariacaoSemSlot.AGENDADO_D1,
        )
        self.assertIn("data_desejada", js["labels_se"]["variacao_sem_slot"]["sem_agenda"])
        self.assertIn("data_alternativa", js["labels_se"]["variacao_sem_slot"]["agendado_d1"])

    def test_sem_slot_sem_agenda_nao_exige_data_d1(self):
        form = TicketCreateForm(
            data={
                "parceiro": str(self.pdv.pk),
                "tipo": TipoDemanda.SEM_SLOT,
                "variacao_sem_slot": VariacaoSemSlot.SEM_AGENDA,
                "pedido": "11260002",
                "data_desejada": "2026-09-21",
                "turno": "tarde",
                "solicitante_contato": "61977776666",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data.get("data_alternativa"))

    def test_sem_slot_d1_exige_segunda_data(self):
        base = {
            "parceiro": str(self.pdv.pk),
            "tipo": TipoDemanda.SEM_SLOT,
            "variacao_sem_slot": VariacaoSemSlot.AGENDADO_D1,
            "pedido": "11260003",
            "data_desejada": "2026-09-21",
            "turno": "manha",
            "solicitante_contato": "61977776666",
        }
        vazio = TicketCreateForm(data=base)
        self.assertFalse(vazio.is_valid())
        self.assertIn("data_alternativa", vazio.errors)
        ok = TicketCreateForm(data={**base, "data_alternativa": "2026-09-22"})
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_kit_operacao_compartilha_campos(self):
        for tipo in TIPOS_KIT_OPERACAO:
            cfg = schema_tipo(tipo)
            for campo in (
                "pedido",
                "sa",
                "nome_cliente",
                "solicitante_contato",
                "tipo_pendencia",
                "recorrencia",
                "descricao",
            ):
                self.assertIn(campo, cfg["campos"], tipo)
                self.assertIn(campo, cfg["obrigatorios"], tipo)
            self.assertNotIn("evidencias", cfg["obrigatorios"], tipo)

    def test_pendencia_indevida_valida(self):
        form = TicketCreateForm(data=self._kit())
        self.assertTrue(form.is_valid(), form.errors)

    def test_pendencia_indevida_exige_sa(self):
        form = TicketCreateForm(data=self._kit(sa=""))
        self.assertFalse(form.is_valid())
        self.assertIn("sa", form.errors)

    def test_vazamento_exige_evidencia_e_data(self):
        form = TicketCreateForm(
            data={
                "parceiro": str(self.pdv.pk),
                "tipo": TipoDemanda.VAZAMENTO_DADOS,
                "documento_cliente": "12345678901",
                "descricao": "Cliente relatou exposição de dados.",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("data_desejada", form.errors)
        self.assertIn("evidencias", form.errors)

    def test_gestao_acessos_valida(self):
        form = TicketCreateForm(
            data={
                "parceiro": str(self.pdv.pk),
                "tipo": TipoDemanda.GESTAO_ACESSOS,
                "tt": "TT9001",
                "cargo_acesso": "Vendedor",
                "solicitante_nome": "João Silva",
                "documento_cliente": "12345678901",
                "rg": "1234567",
                "email_solicitante": "joao@pdv.com",
                "descricao": "Liberar perfil de vendas.",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_mascara_kit_inclui_sa_e_recorrencia(self):
        from tickets.management.commands.seed_nio import MASCARAS
        from tickets.services import render_mascara

        template = next(
            m["template"]
            for m in MASCARAS
            if m["nome"].startswith("Kit operação")
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.AGENDA_NAO_CUMPRIDA,
            pedido="11260001",
            sa="SA-9001",
            nome_cliente="Cliente Teste",
            solicitante_nome="Ana Contato",
            solicitante_contato="61988887777",
            cidade="Brasília",
            data_desejada="2026-09-20",
            tipo_pendencia="Documentação",
            recorrencia=Recorrencia.SIM,
            descricao="Técnico não compareceu.",
        )
        texto = render_mascara(Mascara(template=template), ticket)
        self.assertIn("SA-9001", texto)
        self.assertIn("Agenda não cumprida", texto)
        self.assertIn("Sim", texto)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_pagina_nova_demanda_traz_tipos_novos(self):
        User = get_user_model()
        user = User.objects.create_superuser("matriz_admin", "m@x.com", "x")
        PerfilStaff.objects.create(user=user, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(user)
        resp = self.client.get(reverse("ticket_criar"))
        self.assertEqual(resp.status_code, 200)
        corpo = resp.content.decode("utf-8")
        self.assertIn("Orientações de pendências", corpo)
        self.assertIn("Pendência indevida", corpo)
        self.assertIn("Vazamento de dados", corpo)
        self.assertIn("Apoio gestão de acessos", corpo)
        self.assertIn("Situação do pedido", corpo)
        self.assertIn("agendado_d1", corpo)


class FormatacaoDuracaoTests(SimpleTestCase):
    def test_formatos(self):
        self.assertEqual(formatar_duracao(None), "—")
        self.assertEqual(formatar_duracao(8), "8s")
        self.assertEqual(formatar_duracao(90), "1min 30s")
        self.assertEqual(formatar_duracao(3600), "1h 00min")


class EspecialistaAcessoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        self.spec = User.objects.create_user("ana", "a@x.com", "x", is_staff=True, first_name="Ana")
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv_ana = Parceiro.objects.create(
            codigo_pdv="100", nome="PDV Ana", especialista=self.spec
        )
        self.pdv_outro = Parceiro.objects.create(codigo_pdv="200", nome="PDV Outro")
        self.ticket_ana = Ticket.objects.create(
            parceiro=self.pdv_ana, tipo=TipoDemanda.RESET_SENHA, tt="TT1"
        )
        self.ticket_outro = Ticket.objects.create(
            parceiro=self.pdv_outro, tipo=TipoDemanda.STATUS_PEDIDO, pedido="99"
        )

    def test_lista_parceiros_sem_especialista_nao_quebra(self):
        from django.template import Context, Template

        html = Template(
            "{% if p.especialista %}"
            "{{ p.especialista.get_full_name|default:p.especialista.username }}"
            "{% else %}—{% endif %}"
        ).render(Context({"p": self.pdv_outro}))
        self.assertEqual(html, "—")
        html_ana = Template(
            "{% if p.especialista %}"
            "{{ p.especialista.get_full_name|default:p.especialista.username }}"
            "{% else %}—{% endif %}"
        ).render(Context({"p": self.pdv_ana}))
        self.assertIn("Ana", html_ana)

    def test_gestor_ve_todos(self):
        self.assertTrue(eh_gestor(self.gestor))
        self.assertEqual(tickets_visiveis(self.gestor).count(), 2)

    def test_especialista_ve_so_os_seus(self):
        self.assertFalse(eh_gestor(self.spec))
        qs = tickets_visiveis(self.spec)
        self.assertEqual(list(qs), [self.ticket_ana])

    def test_gestao_escopo_nao_altera_fila(self):
        from tickets.acesso import parceiros_gestao, parceiros_visiveis

        self.assertEqual(list(parceiros_visiveis(self.spec)), [self.pdv_ana])
        self.assertEqual(list(parceiros_gestao(self.spec, "meus")), [self.pdv_ana])
        self.assertEqual(list(parceiros_gestao(self.spec, "outros")), [])
        self.assertEqual(tickets_visiveis(self.spec).count(), 1)


    def test_especialista_nao_abre_ticket_alheio(self):
        self.client.force_login(self.spec)
        r = self.client.get(
            reverse("ticket_detalhe", args=[self.ticket_outro.protocolo])
        )
        self.assertEqual(r.status_code, 404)

    def test_criar_especialista_pelo_gestor(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Bruno",
                "username": "bruno",
                "email": "b@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="bruno")
        self.assertTrue(u.is_staff)
        self.assertEqual(u.perfil_staff.papel, PerfilStaff.Papel.ESPECIALISTA)
        self.assertEqual(u.perfil_staff.fte, Decimal("1.00"))

    def test_criar_especialista_com_gerencia(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Elisa",
                "username": "elisa",
                "email": "e@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
                "gerencia": "MG INTERIOR",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="elisa")
        self.assertEqual(u.perfil_staff.gerencia, "MG INTERIOR")

    def test_form_especialista_mostra_whatsapp(self):
        from tickets.forms import EspecialistaForm

        form = EspecialistaForm()
        self.assertIn("whatsapp", form.fields)
        self.assertIn("DDI", form.fields["whatsapp"].help_text)
        self.assertIn("gerencia", form.fields)

    def test_criar_especialista_com_fte_meio_periodo(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Diego",
                "username": "diego",
                "email": "d@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
                "fte": "0.50",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="diego")
        self.assertEqual(u.perfil_staff.fte, Decimal("0.50"))

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_dashboard_calcula_fte_e_tickets_por_fte(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["fte_total"], Decimal("2.00"))
        self.assertEqual(r.context["tickets_mes"], 2)
        self.assertEqual(r.context["tickets_por_fte"], 1.0)
        self.assertContains(r, "FTE da equipe")
        self.assertContains(r, "Tickets / FTE")
        self.assertContains(r, "Este mês")
        self.assertContains(r, "Todos parceiros")
        self.ticket_ana.tipo = TipoDemanda.SEM_SLOT
        self.ticket_ana.save(update_fields=["tipo"])
        r = self.client.get(reverse("dashboard"))
        labels = [row["label"] for row in r.context["por_tipo"]]
        self.assertIn(TipoDemanda.SEM_SLOT.label, labels)
        self.assertNotIn("Sinalização", labels)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_dashboard_filtra_periodo_parceiro_e_especialista(self):
        antigo = Ticket.objects.create(
            parceiro=self.pdv_ana, tipo=TipoDemanda.RESET_SENHA, tt="TT-OLD"
        )
        Ticket.objects.filter(pk=antigo.pk).update(
            criado_em=timezone.now() - timedelta(days=40)
        )
        self.client.force_login(self.gestor)
        mes = self.client.get(reverse("dashboard"))
        self.assertEqual(mes.context["periodo"], "mes")
        self.assertEqual(mes.context["total"], 2)

        tudo = self.client.get(reverse("dashboard"), {"periodo": "tudo"})
        self.assertEqual(tudo.context["periodo"], "tudo")
        self.assertEqual(tudo.context["total"], 3)

        pdv = self.client.get(
            reverse("dashboard"),
            {"periodo": "tudo", "parceiro": self.pdv_ana.pk},
        )
        self.assertEqual(pdv.context["total"], 2)
        self.assertContains(pdv, "PDV Ana")

        spec = self.client.get(
            reverse("dashboard"),
            {"periodo": "tudo", "especialista": self.spec.pk},
        )
        self.assertEqual(spec.context["total"], 2)
        self.assertEqual(spec.context["fte_total"], Decimal("1.00"))
        self.assertContains(spec, "FTE do especialista")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_cabecalho_mostra_primeiro_nome_e_menu_sair(self):
        self.gestor.first_name = "Rogério Pereira"
        self.gestor.save(update_fields=["first_name"])
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "nav-account")
        self.assertContains(r, ">Rogério</a>")
        self.assertContains(r, "Meu perfil")
        self.assertContains(r, "Sair")

    def test_nao_permite_renomear_especialista_para_login_do_gestor(self):
        from .forms import EspecialistaForm

        form = EspecialistaForm(
            {
                "first_name": "Ana",
                "username": "gestor",
                "email": "a@x.com",
                "is_active": "on",
            },
            instance=self.spec,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.username, "ana")

    def test_dropdown_parceiro_mostra_equipe_deste_app(self):
        User = get_user_model()
        User.objects.create_user("DANIEL", "d@x.com", "x", is_staff=True)
        User.objects.create_user("VT35879", "v@x.com", "x", is_staff=True)
        nomes = set(qs_equipe().values_list("username", flat=True))
        self.assertEqual(nomes, {"ana", "gestor"})
        self.assertEqual(
            set(qs_especialistas().values_list("username", flat=True)),
            {"ana"},
        )
        form = ParceiroForm()
        self.assertEqual(
            set(form.fields["especialista"].queryset.values_list("username", flat=True)),
            {"ana", "gestor"},
        )

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_pagina_especialistas_mostra_gestor_e_especialista(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialistas"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "gestor")
        self.assertContains(r, "Ana")
        self.assertContains(r, "Admin")
        self.assertContains(r, "Editar")
        self.assertContains(r, "Excluir")
        self.assertContains(r, "wrap wrap-wide")
        self.assertContains(r, "data-tabela-busca")
        self.assertContains(r, "spec-card")
        self.assertNotContains(r, "DANIEL")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_lista_parceiros_tem_meus_e_outros(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("parceiros"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Meus parceiros")
        self.assertContains(r, "Outros especialistas")
        self.assertContains(r, "Inativos")
        self.assertContains(r, "Empresários")
        self.assertContains(r, "data-tabela-busca")
        self.assertContains(r, "Buscar código")
        meus = self.client.get(reverse("parceiros"), {"escopo": "meus"})
        self.assertNotContains(meus, "PDV Ana")
        outros = self.client.get(reverse("parceiros"), {"escopo": "outros"})
        self.assertContains(outros, "PDV Ana")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_lista_parceiros_aba_inativos(self):
        self.pdv_outro.ativo = False
        self.pdv_outro.save(update_fields=["ativo"])
        self.client.force_login(self.gestor)
        outros = self.client.get(reverse("parceiros"), {"escopo": "outros"})
        self.assertNotContains(outros, "PDV Outro")
        inativos = self.client.get(reverse("parceiros"), {"escopo": "inativos"})
        self.assertEqual(inativos.status_code, 200)
        self.assertContains(inativos, "PDV Outro")
        self.assertContains(inativos, "Reativar")
        self.assertNotContains(inativos, "PDV Ana")
        self.assertContains(inativos, 'href="?escopo=inativos"')

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_inativar_abre_aba_inativos(self):
        self.client.force_login(self.spec)
        r = self.client.post(reverse("parceiro_inativar", args=[self.pdv_ana.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("escopo=inativos", r["Location"])
        lista = self.client.get(reverse("parceiros"), {"escopo": "inativos"})
        self.assertContains(lista, "PDV Ana")
        self.assertContains(lista, "Reativar")
        meus = self.client.get(reverse("parceiros"), {"escopo": "meus"})
        self.assertNotContains(meus, "PDV Ana")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_reativar_devolve_parceiro_a_lista(self):
        self.pdv_ana.ativo = False
        self.pdv_ana.save(update_fields=["ativo"])
        self.client.force_login(self.spec)
        r = self.client.post(reverse("parceiro_reativar", args=[self.pdv_ana.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("escopo=meus", r["Location"])
        self.pdv_ana.refresh_from_db()
        self.assertTrue(self.pdv_ana.ativo)
        meus = self.client.get(reverse("parceiros"), {"escopo": "meus"})
        self.assertContains(meus, "PDV Ana")
        inativos = self.client.get(reverse("parceiros"), {"escopo": "inativos"})
        self.assertNotContains(inativos, "PDV Ana")
        editar = self.client.get(reverse("parceiro_editar", args=[self.pdv_ana.pk]))
        self.assertContains(editar, "Inativar PDV")
        self.pdv_ana.ativo = False
        self.pdv_ana.save(update_fields=["ativo"])
        editar_inativo = self.client.get(reverse("parceiro_editar", args=[self.pdv_ana.pk]))
        self.assertContains(editar_inativo, "Reativar PDV")

    def test_staff_de_outro_sistema_nao_e_gestor_nem_loga(self):
        User = get_user_model()
        externo = User.objects.create_user("DANIEL", "d@x.com", "x", is_staff=True)
        self.assertFalse(eh_gestor(externo))
        form = LoginForm(
            data={"username": "DANIEL", "password": "x"},
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_superuser_sem_perfil_nao_e_gestor(self):
        User = get_user_model()
        solto = User.objects.create_superuser("vt-admin", "vt@x.com", "x")
        self.assertFalse(eh_gestor(solto))

    def test_middleware_desloga_quem_nao_tem_perfil(self):
        User = get_user_model()
        externo = User.objects.create_user("VT35558", "v@x.com", "x", is_staff=True)
        self.client.force_login(externo)
        r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_perfil_nao_renomeia_para_login_de_outra_conta(self):
        from .forms import StaffPerfilForm

        form = StaffPerfilForm(
            {
                "first_name": "Admin",
                "username": "gestor",
                "email": "a@x.com",
            },
            instance=self.spec,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_promover_especialista_a_admin_ve_todos(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_editar", args=[self.spec.pk]),
            {
                "first_name": "Ana",
                "username": "ana",
                "email": "a@x.com",
                "is_active": "on",
                "eh_admin": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.spec.refresh_from_db()
        self.assertEqual(self.spec.perfil_staff.papel, PerfilStaff.Papel.GESTOR)
        self.assertTrue(eh_gestor(self.spec))
        self.assertEqual(tickets_visiveis(self.spec).count(), 2)

    def test_criar_especialista_como_admin(self):
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("especialista_novo"),
            {
                "first_name": "Carla",
                "username": "carla",
                "email": "c@x.com",
                "password": "SenhaForte123",
                "is_active": "on",
                "eh_admin": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        User = get_user_model()
        u = User.objects.get(username="carla")
        self.assertEqual(u.perfil_staff.papel, PerfilStaff.Papel.GESTOR)
        self.assertTrue(eh_gestor(u))

    def test_nao_remove_ultimo_admin(self):
        from .forms import EspecialistaForm

        form = EspecialistaForm(
            {
                "first_name": "Gestor",
                "username": "gestor",
                "email": "g@x.com",
                "is_active": "on",
            },
            instance=self.gestor,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("eh_admin", form.errors)
        self.gestor.refresh_from_db()
        self.assertEqual(self.gestor.perfil_staff.papel, PerfilStaff.Papel.GESTOR)

    def test_nao_edita_a_si_mesmo_nesta_tela(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialista_editar", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/perfil/", r["Location"])

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_editar_outro_admin(self):
        User = get_user_model()
        outro = User.objects.create_user(
            "bruno", "br@x.com", "x", is_staff=True, first_name="Bruno"
        )
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("especialista_editar", args=[outro.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Bruno")
        r = self.client.post(
            reverse("especialista_editar", args=[outro.pk]),
            {
                "first_name": "Bruno",
                "username": "bruno",
                "email": "br@x.com",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        outro.refresh_from_db()
        outro.perfil_staff.refresh_from_db()
        self.assertEqual(outro.perfil_staff.papel, PerfilStaff.Papel.ESPECIALISTA)
        self.assertFalse(eh_gestor(outro))

    def test_excluir_especialista(self):
        User = get_user_model()
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.spec.pk).exists())
        self.pdv_ana.refresh_from_db()
        self.assertIsNone(self.pdv_ana.especialista_id)

    def test_nao_exclui_a_si_mesmo(self):
        User = get_user_model()
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.gestor.pk).exists())

    def test_excluir_outro_admin_quando_ha_mais_de_um(self):
        User = get_user_model()
        outro = User.objects.create_user(
            "bruno", "br@x.com", "x", is_staff=True, first_name="Bruno"
        )
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("especialista_excluir", args=[outro.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=outro.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.gestor.pk).exists())

    def test_especialista_nao_exclui(self):
        self.client.force_login(self.spec)
        r = self.client.post(reverse("especialista_excluir", args=[self.gestor.pk]))
        self.assertEqual(r.status_code, 404)


class TratamentoModalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.user, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="100", nome="PDV")
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.RESET_SENHA, tt="TT99"
        )

    def test_primeira_aba_e_campo_da_resposta(self):
        form = TicketTreatForm(instance=self.ticket)
        abas = montar_abas_tratamento(form)
        self.assertTrue(abas[0]["principal"])
        self.assertEqual(abas[0]["id"], "senha_resetada")
        self.assertFalse(any(aba["id"] == "status" for aba in abas))

    def test_clicar_responder_inicia_cronometro_e_salvar_registra(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.resposta_iniciada_em)
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)
        self.assertContains(r, "Selecione a situação")
        self.ticket.resposta_iniciada_em = timezone.now() - timedelta(seconds=12)
        self.ticket.save(update_fields=["resposta_iniciada_em"])

        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.EM_ANALISE)
        self.assertIsNotNone(self.ticket.tempo_retorno_segundos)
        self.assertGreaterEqual(self.ticket.tempo_retorno_segundos, 12)
        self.assertIn("Nio@123", self.ticket.resposta_publica)

    def test_salvar_resposta_preserva_filtro_da_fila(self):
        self.client.force_login(self.user)
        destino = reverse("fila") + "?situacao_osab=Em+Aprovisionamento&status=em_analise"
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
                "next": destino,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["redirect"], destino)

    def test_abrir_modal_nao_muda_situacao_na_fila(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)

    def test_salvar_como_novo_e_rejeitado(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.NOVO,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)
        self.assertContains(r, "não pode permanecer como Novo", status_code=400)
        self.assertContains(r, "Situação na fila", status_code=400)

    def test_salvar_sem_situacao_retorna_json_claro_para_ajax(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": "",
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(r.status_code, 400)
        data = r.json()
        self.assertFalse(data["ok"])
        self.assertIn("Situação", data["error"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, StatusTicket.NOVO)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_modal_mostra_anexo_e_permite_copiar_mascara(self):
        from .models import Mascara

        Anexo.objects.create(
            ticket=self.ticket,
            arquivo=SimpleUploadedFile("print.jpeg", b"fake-image", content_type="image/jpeg"),
            nome_original="print.jpeg",
        )
        Mascara.objects.create(
            nome="Reset",
            destino="GC",
            tipos=TipoDemanda.RESET_SENHA,
            template="*TT:* {{tt}}",
            ativo=True,
        )
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "print.jpeg")
        self.assertContains(r, "modal-anexo-img")
        self.assertContains(r, 'data-tab="mascaras"')
        self.assertContains(r, "Copiar")
        self.assertContains(r, "*TT:* TT99")

    def test_modal_mostra_historico_de_respostas(self):
        Mensagem.objects.create(
            ticket=self.ticket,
            autor=self.user,
            autor_nome="gestor",
            corpo="Chamado 998877 aberto na TI",
            interno=False,
        )
        self.ticket.resposta_publica = "Chamado 998877 aberto na TI"
        self.ticket.resultado_status = "CHAMADO ABERTO"
        self.ticket.save(update_fields=["resposta_publica", "resultado_status"])
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-tab="historico"')
        self.assertContains(r, "Chamado 998877 aberto na TI")
        self.assertContains(r, "CHAMADO ABERTO")

    def test_salvar_sem_campo_obrigatorio_mostra_erro_no_modal(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": StatusTicket.EM_ANALISE,
                "prioridade": self.ticket.prioridade,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Não foi possível salvar", status_code=400)
        self.assertContains(r, "Senha resetada", status_code=400)

    def test_modal_permite_alterar_tipo_da_demanda(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(r, "Aplicar tipo")
        self.assertContains(r, "id_tipo_tratamento")
        self.assertContains(r, "Situação na fila")
        self.assertNotContains(r, 'data-tab="status"')

        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "atualizar_tipo",
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.tipo, TipoDemanda.ABRIR_CHAMADO_TI)
        self.assertContains(r, "Nº do chamado TI")
        self.assertContains(r, "Tipo alterado")
        self.assertContains(r, "CNPJ/CPF do cliente")

    def test_abrir_chamado_ti_mostra_cpf_no_contexto(self):
        self.ticket.tipo = TipoDemanda.ABRIR_CHAMADO_TI
        self.ticket.documento_cliente = "37161261600"
        self.ticket.tt_vendedor = "Tr832209"
        self.ticket.tt_backoffice = "Tr832215"
        self.ticket.pedido = "10958838"
        self.ticket.save()
        itens = contexto_demanda_para_resposta(self.ticket)
        nomes = [i["name"] for i in itens]
        self.assertIn("documento_cliente", nomes)
        cpf = next(i for i in itens if i["name"] == "documento_cliente")
        self.assertEqual(cpf["valor"], "37161261600")
        self.assertIn("CPF", cpf["label"])


class IsolamentoAuthTests(SimpleTestCase):
    def test_schema_padrao_valido(self):
        from tickets.isolamento_auth import nome_schema

        self.assertEqual(nome_schema(), "nio_gc_tickets")

    def test_isolamento_e_noop_fora_do_postgres(self):
        from django.db import connection

        from tickets.isolamento_auth import isolar_auth_schema

        resultado = isolar_auth_schema(connection)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado.get("motivo"), "nao_postgres")


class FilaOsabTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(
            codigo_pdv="100", nome="PDV", especialista=self.gestor
        )
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.STATUS_PEDIDO,
            pedido="10721324",
        )
        self.storages = {
            "STORAGES": {
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        }

    def test_fila_mostra_situacao_e_atualizacao_osab(self):
        from gestao.models import VendaOSAB

        dt_ref = timezone.now().replace(year=2026, month=8, day=21, hour=14, minute=30)
        VendaOSAB.objects.create(
            pedido="10721324",
            pdv_nome="PDV",
            situacao="Concluído",
            dt_ref=dt_ref,
        )
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Situação OSAB")
        self.assertNotContains(r, "Atualiz. OSAB")
        self.assertContains(r, "fila-action-group")
        self.assertContains(r, "Responder")
        self.assertContains(r, "Concluído")
        self.assertContains(r, "21/08/26")
        ticket = r.context["tickets"][0]
        self.assertEqual(ticket.osab_situacao, "Concluído")
        self.assertEqual(ticket.osab_atualizacao, dt_ref)

    def test_fila_sem_osab_fica_em_branco(self):
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        ticket = r.context["tickets"][0]
        self.assertEqual(ticket.osab_situacao, "")
        self.assertIsNone(ticket.osab_atualizacao)

    def test_filtro_situacao_osab(self):
        from gestao.models import VendaOSAB

        Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.RESET_SENHA,
            pedido="99999999",
        )
        VendaOSAB.objects.create(
            pedido="10721324",
            pdv_nome="PDV",
            situacao="Em Aprovisionamento",
        )
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"), {"situacao_osab": "Em Aprovisionamento"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["tickets"]), 1)
        self.assertEqual(r.context["tickets"][0].pedido, "10721324")
        self.assertContains(r, "Todas situações OSAB")
        with override_settings(**self.storages):
            r = self.client.get(reverse("fila"), {"situacao_osab": "__sem__"})
        self.assertEqual(len(r.context["tickets"]), 1)
        self.assertEqual(r.context["tickets"][0].pedido, "99999999")

    def test_botao_responder_leva_filtros_no_next(self):
        self.client.force_login(self.gestor)
        with override_settings(**self.storages):
            r = self.client.get(
                reverse("fila"),
                {"tipo": TipoDemanda.STATUS_PEDIDO, "situacao_osab": "__sem__"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-next=")
        self.assertContains(r, "tipo=status_pedido")
        self.assertContains(r, "situacao_osab=__sem__")


@override_settings(STORAGES=STORAGES_TESTE)
class FilaCoberturaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            "admin_fila", "adm@x.com", "x", is_staff=True, first_name="Admin"
        )
        self.ana = User.objects.create_user(
            "ana_fila", "ana@x.com", "x", is_staff=True, first_name="Ana"
        )
        self.bruno = User.objects.create_user(
            "bruno_fila", "bruno@x.com", "x", is_staff=True, first_name="Bruno"
        )
        self.carla = User.objects.create_user(
            "carla_fila", "carla@x.com", "x", is_staff=True, first_name="Carla"
        )
        self.ger = User.objects.create_user(
            "ger_fila", "ger@x.com", "x", is_staff=True, first_name="Gerencia"
        )
        PerfilStaff.objects.create(user=self.admin, papel=PerfilStaff.Papel.GESTOR)
        PerfilStaff.objects.create(
            user=self.ana, papel=PerfilStaff.Papel.ESPECIALISTA, gerencia="MG INTERIOR"
        )
        PerfilStaff.objects.create(
            user=self.bruno, papel=PerfilStaff.Papel.ESPECIALISTA, gerencia="MG INTERIOR"
        )
        PerfilStaff.objects.create(
            user=self.carla, papel=PerfilStaff.Papel.ESPECIALISTA, gerencia="SP METRO"
        )
        PerfilStaff.objects.create(
            user=self.ger, papel=PerfilStaff.Papel.GERENCIA, gerencia="MG INTERIOR"
        )
        self.pdv_admin = Parceiro.objects.create(
            codigo_pdv="A1", nome="PDV Admin", especialista=self.admin
        )
        self.pdv_ana = Parceiro.objects.create(
            codigo_pdv="A2", nome="PDV Ana", especialista=self.ana
        )
        self.pdv_bruno = Parceiro.objects.create(
            codigo_pdv="A3", nome="PDV Bruno", especialista=self.bruno
        )
        self.pdv_carla = Parceiro.objects.create(
            codigo_pdv="A4", nome="PDV Carla", especialista=self.carla
        )
        self.ticket_admin = Ticket.objects.create(
            parceiro=self.pdv_admin, tipo=TipoDemanda.RESET_SENHA, tt="TTA"
        )
        self.ticket_ana = Ticket.objects.create(
            parceiro=self.pdv_ana, tipo=TipoDemanda.RESET_SENHA, tt="TTN"
        )
        self.ticket_bruno = Ticket.objects.create(
            parceiro=self.pdv_bruno, tipo=TipoDemanda.STATUS_PEDIDO, pedido="88"
        )
        self.ticket_carla = Ticket.objects.create(
            parceiro=self.pdv_carla, tipo=TipoDemanda.RESET_SENHA, tt="TTC"
        )

    def _protocolos(self, response):
        return [t.protocolo for t in response.context["tickets"]]

    def test_admin_fila_padrao_so_os_seus(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._protocolos(r), [self.ticket_admin.protocolo])
        self.assertContains(r, "Meus parceiros")
        self.assertContains(r, "Ana")
        self.assertContains(r, "Bruno")
        self.assertContains(r, "Carla")

    def test_admin_escolhe_especialista_da_gerencia(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["gestao_gerencia"] = "MG INTERIOR"
        session.save()
        r = self.client.get(reverse("fila"), {"especialista": self.ana.pk})
        self.assertEqual(self._protocolos(r), [self.ticket_ana.protocolo])
        html = r.content.decode()
        self.assertIn(f'value="{self.ana.pk}"', html)
        self.assertIn(f'value="{self.bruno.pk}"', html)
        self.assertNotIn(f'value="{self.carla.pk}"', html)

    def test_especialista_ve_filtro_e_so_os_seus_por_padrao(self):
        self.client.force_login(self.ana)
        r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._protocolos(r), [self.ticket_ana.protocolo])
        self.assertContains(r, "Meus parceiros")
        self.assertContains(r, "Bruno")
        self.assertNotContains(r, "Carla")
        parceiros = list(r.context["form"].fields["parceiro"].queryset.values_list("nome", flat=True))
        self.assertEqual(parceiros, ["PDV Ana"])

    def test_especialista_cobre_colega_da_mesma_gerencia(self):
        self.client.force_login(self.ana)
        r = self.client.get(reverse("fila"), {"especialista": self.bruno.pk})
        self.assertEqual(self._protocolos(r), [self.ticket_bruno.protocolo])
        parceiros = list(r.context["form"].fields["parceiro"].queryset.values_list("nome", flat=True))
        self.assertEqual(parceiros, ["PDV Bruno"])
        r2 = self.client.get(
            reverse("fila"),
            {"especialista": self.bruno.pk, "parceiro": self.pdv_ana.pk},
        )
        self.assertEqual(self._protocolos(r2), [self.ticket_bruno.protocolo])

    def test_especialista_nao_cobre_outra_gerencia_pelo_filtro(self):
        self.client.force_login(self.ana)
        r = self.client.get(reverse("fila"), {"especialista": self.carla.pk})
        self.assertEqual(self._protocolos(r), [self.ticket_ana.protocolo])

    def test_especialista_responde_na_ausencia_do_colega(self):
        self.client.force_login(self.ana)
        detalhe = self.client.get(
            reverse("ticket_detalhe", args=[self.ticket_bruno.protocolo])
        )
        self.assertEqual(detalhe.status_code, 200)
        abrir = self.client.post(
            reverse("ticket_responder", args=[self.ticket_bruno.protocolo]),
            {"action": "abrir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(abrir.status_code, 200)
        self.assertContains(abrir, "Selecione a situação")

    def test_especialista_nao_abre_ticket_de_outra_gerencia(self):
        self.client.force_login(self.ana)
        r = self.client.get(reverse("ticket_detalhe", args=[self.ticket_carla.protocolo]))
        self.assertEqual(r.status_code, 404)

    def test_gerencia_fila_padrao_so_os_seus(self):
        self.client.force_login(self.ger)
        r = self.client.get(reverse("fila"))
        self.assertEqual(self._protocolos(r), [])
        r = self.client.get(reverse("fila"), {"especialista": self.ana.pk})
        self.assertEqual(self._protocolos(r), [self.ticket_ana.protocolo])


class SeedNioParceirosTests(TestCase):
    def test_primeira_carga_cria_parceiros_iniciais(self):
        from django.core.management import call_command

        from tickets.management.commands.seed_nio import PARCEIROS

        call_command("seed_nio")
        self.assertEqual(Parceiro.objects.count(), len(PARCEIROS))
        self.assertTrue(Parceiro.objects.filter(codigo_pdv="1068279", nome="APOLO").exists())

    def test_seed_nao_recria_parceiro_excluido(self):
        from django.core.management import call_command

        call_command("seed_nio")
        Parceiro.objects.filter(codigo_pdv="1068279").delete()
        call_command("seed_nio")
        self.assertFalse(Parceiro.objects.filter(codigo_pdv="1068279").exists())
        self.assertTrue(Parceiro.objects.filter(codigo_pdv="1068432").exists())

    def test_seed_nao_reativa_parceiro_inativo(self):
        from django.core.management import call_command

        call_command("seed_nio")
        p = Parceiro.objects.get(codigo_pdv="1068279")
        p.ativo = False
        p.save(update_fields=["ativo"])
        call_command("seed_nio")
        p.refresh_from_db()
        self.assertFalse(p.ativo)


class MascaraEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec = User.objects.create_user(
            "specmail", "spec@x.com", "x", is_staff=True
        )
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        self.pdv = Parceiro.objects.create(
            codigo_pdv="m1",
            nome="PDV Mail",
            especialista=self.spec,
            email="pdv@x.com",
        )

    @override_settings(SMTP_HOST="smtp.test", SMTP_FROM="from@test.com")
    def test_envia_mascara_marcada(self):
        from unittest.mock import patch

        from tickets.models import Mascara
        from tickets.services import notificar_mascaras_por_email

        Mascara.objects.create(
            nome="Elite",
            destino="Grupo Elite",
            tipos=TipoDemanda.PRIORIDADE_ELITE,
            template="Pedido {{pedido}}",
            enviar_email=True,
            ativo=True,
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.PRIORIDADE_ELITE, pedido="123"
        )
        with patch(
            "gestao.messaging.email_smtp.enviar_email_com_anexos",
            return_value=(True, ""),
        ) as send:
            n = notificar_mascaras_por_email(ticket)
        self.assertEqual(n, 1)
        destinos = send.call_args.args[0]
        self.assertIn("spec@x.com", destinos)
        self.assertIn("pdv@x.com", destinos)
        self.assertIn("123", send.call_args.kwargs["corpo_texto"])

    @override_settings(SMTP_HOST="smtp.test", SMTP_FROM="from@test.com")
    def test_ignora_mascara_de_outro_tipo(self):
        from unittest.mock import patch

        from tickets.models import Mascara
        from tickets.services import notificar_mascaras_por_email

        Mascara.objects.create(
            nome="Reset",
            destino="GC",
            tipos=TipoDemanda.RESET_SENHA,
            template="TT {{tt}}",
            enviar_email=True,
            ativo=True,
        )
        ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.PRIORIDADE_ELITE, pedido="9"
        )
        with patch(
            "gestao.messaging.email_smtp.enviar_email_com_anexos",
            return_value=(True, ""),
        ) as send:
            n = notificar_mascaras_por_email(ticket)
        self.assertEqual(n, 0)
        send.assert_not_called()


@override_settings(STORAGES=STORAGES_TESTE)
class MascaraWhatsAppTests(TestCase):
    def setUp(self):
        from unittest.mock import patch
        from tickets.models import Mascara
        User = get_user_model()
        self.spec = User.objects.create_user(
            "specricardo", "ricardo@test.com", "x", is_staff=True, first_name="Ricardo Santos"
        )
        self.perfil_spec = PerfilStaff.objects.create(
            user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA, whatsapp="5521999575120"
        )
        self.admin_user = User.objects.create_superuser("admin", "admin@test.com", "x")
        PerfilStaff.objects.create(user=self.admin_user, papel=PerfilStaff.Papel.GESTOR)
        self.pdv_spec = Parceiro.objects.create(
            codigo_pdv="pdv_spec",
            nome="PDV Ricardo",
            especialista=self.spec,
        )
        self.pdv_admin = Parceiro.objects.create(
            codigo_pdv="pdv_admin",
            nome="PDV Admin",
            especialista=self.admin_user,
        )
        self.mascara_slot = Mascara.objects.create(
            nome="Sinalização — Sem slot / liberação de agenda",
            destino="GC / Diretoria",
            tipos=TipoDemanda.SEM_SLOT,
            template="Sem SLOT em {{uf}}\nPedido: {{pedido}}\nContato: {{contato}}",
            enviar_whatsapp=True,
            ativo=True,
        )

    def test_enviar_mascara_whatsapp_especialista_nao_admin(self):
        from unittest.mock import patch
        from tickets.services import enviar_mascara_whatsapp
        from gestao.messaging.syncwa import SyncWAResult

        ticket = Ticket.objects.create(
            parceiro=self.pdv_spec,
            tipo=TipoDemanda.SEM_SLOT,
            pedido="PED-100",
            solicitante_contato="21999999999",
            uf="RJ",
        )
        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp) as mock_send:
            ok, msg = enviar_mascara_whatsapp(ticket, self.mascara_slot)
            self.assertTrue(ok)
            self.assertIn("Ricardo Santos", msg)
            mock_send.assert_called_once()
            jid, texto = mock_send.call_args.args
            self.assertEqual(jid, "5521999575120")
            self.assertIn("Sem SLOT em RJ", texto)
            self.assertIn("Pedido: PED-100", texto)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, StatusTicket.ENCAMINHADO)
        self.assertTrue(ticket.encaminhamentos.filter(destino__contains="5521999575120").exists())

    def test_enviar_mascara_whatsapp_especialista_admin_com_destino_escolhido(self):
        from unittest.mock import patch
        from tickets.services import enviar_mascara_whatsapp
        from gestao.messaging.syncwa import SyncWAResult

        ticket = Ticket.objects.create(
            parceiro=self.pdv_admin,
            tipo=TipoDemanda.SEM_SLOT,
            pedido="PED-200",
            uf="SP",
        )
        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp) as mock_send:
            ok, msg = enviar_mascara_whatsapp(
                ticket,
                self.mascara_slot,
                destino_jid="120363000000000@g.us",
                destino_nome="Grupo Elite",
            )
            self.assertTrue(ok)
            self.assertIn("Grupo Elite", msg)
            mock_send.assert_called_once()
            jid, texto = mock_send.call_args.args
            self.assertEqual(jid, "120363000000000@g.us")
            self.assertIn("Sem SLOT em SP", texto)

    def test_enviar_mascara_whatsapp_admin_sem_destino_falha(self):
        from unittest.mock import patch
        from tickets.services import enviar_mascara_whatsapp

        ticket = Ticket.objects.create(
            parceiro=self.pdv_admin,
            tipo=TipoDemanda.SEM_SLOT,
            pedido="PED-300",
        )
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True):
            ok, msg = enviar_mascara_whatsapp(ticket, self.mascara_slot)
            self.assertFalse(ok)
            self.assertIn("admin", msg.lower())

    def test_notificar_mascaras_por_whatsapp_ao_criar_ticket(self):
        from unittest.mock import patch
        from tickets.services import notificar_mascaras_por_whatsapp
        from gestao.messaging.syncwa import SyncWAResult

        ticket = Ticket.objects.create(
            parceiro=self.pdv_spec,
            tipo=TipoDemanda.SEM_SLOT,
            pedido="PED-AUTO",
            uf="RJ",
        )
        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp) as mock_send:
            n = notificar_mascaras_por_whatsapp(ticket)
            self.assertEqual(n, 1)
            mock_send.assert_called_once()
            jid, texto = mock_send.call_args.args
            self.assertEqual(jid, "5521999575120")

    def test_view_enviar_mascara_wpp(self):
        from unittest.mock import patch
        from gestao.messaging.syncwa import SyncWAResult

        ticket = Ticket.objects.create(
            parceiro=self.pdv_spec,
            tipo=TipoDemanda.SEM_SLOT,
            pedido="PED-VIEW",
            uf="RJ",
        )
        self.client.force_login(self.admin_user)
        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp):
            resp = self.client.post(
                f"/tickets/{ticket.protocolo}/",
                {"action": "enviar_mascara_wpp", "mascara_id": self.mascara_slot.id},
                follow=True,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "enviada com sucesso")


class ContatoCargoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="100", nome="PDV")
        self.client.force_login(self.gestor)
        self.storages = override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        )

    def test_novo_contato_cargo_e_lista_empresario_backoffice(self):
        from .models import ContatoParceiro

        with self.storages:
            r = self.client.get(reverse("parceiro_editar", args=[self.pdv.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Novo contato")
        self.assertContains(r, "Empresário")
        self.assertContains(r, "Backoffice")
        form = r.context["contato_form"]
        valores = {c[0] for c in form.fields["cargo"].choices}
        self.assertIn(ContatoParceiro.Cargo.EMPRESARIO, valores)
        self.assertIn(ContatoParceiro.Cargo.BACKOFFICE, valores)

    def test_adiciona_contato_empresario(self):
        from .models import ContatoParceiro

        with self.storages:
            r = self.client.post(
                reverse("parceiro_editar", args=[self.pdv.pk]),
                {
                    "action": "add_contato",
                    "nome": "João Dono",
                    "email": "joao@x.com",
                    "telefone": "21988887777",
                    "cargo": ContatoParceiro.Cargo.EMPRESARIO,
                    "ativo": "on",
                },
            )
        self.assertEqual(r.status_code, 302)
        contato = ContatoParceiro.objects.get(parceiro=self.pdv, nome="João Dono")
        self.assertEqual(contato.cargo, "Empresário")
        self.assertTrue(contato.eh_empresario())


class DfvRegioesBrasilTests(SimpleTestCase):
    def test_cobre_todas_as_ufs_e_roteia_co_e_nne(self):
        from tickets.consultas.dfv_powerbi_service import (
            CDOE_UFS,
            listar_regioes_dfv,
            regiao_por_uf,
        )

        ufs_brasil = {
            "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
            "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
            "RO", "RR", "RS", "SC", "SE", "SP", "TO",
        }
        self.assertEqual(set(CDOE_UFS), ufs_brasil)
        self.assertEqual({r.code for r in listar_regioes_dfv()}, {"SUDESTE", "SP", "SUL", "CO", "NNE"})
        self.assertEqual(regiao_por_uf("GO").code, "CO")
        self.assertEqual(regiao_por_uf("BA").code, "NNE")
        self.assertEqual(regiao_por_uf("AC").code, "CO")
        self.assertEqual(regiao_por_uf("AM").code, "NNE")
        self.assertEqual(regiao_por_uf("SP").code, "SP")


class VtalPortalCardTests(SimpleTestCase):
    def test_contexto_traz_url_do_forms(self):
        from django.test import override_settings

        from tickets.consultas.vtal_service import contexto_portal_vtal

        url = "https://docs.google.com/forms/d/e/exemplo/viewform"
        with override_settings(VIABILIDADE_FORMS_URL=url):
            ctx = contexto_portal_vtal()
        self.assertEqual(ctx["vtal_forms_url"], url)
        self.assertIn("vtal_ultima_importacao", ctx)


@override_settings(STORAGES=STORAGES_TESTE)
class EspecialistaDestinoMascaraTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec_user = User.objects.create_user(
            username="lucas_spec",
            password="123",
            first_name="Lucas Especialista",
            email="lucas@example.com",
            is_staff=True,
        )
        self.perfil = PerfilStaff.objects.create(
            user=self.spec_user,
            papel=PerfilStaff.Papel.ESPECIALISTA,
            whatsapp="5531988880000",
        )
        self.pdv = Parceiro.objects.create(
            codigo_pdv="PDV-LUCAS",
            nome="Parceiro Lucas",
            especialista=self.spec_user,
        )
        from gestao.models import Destinatario
        self.grupo = Destinatario.objects.create(
            nome="Grupo Suporte Central",
            jid="120363999999999@g.us",
            tipo=Destinatario.TipoDestino.GRUPO,
            ativo=True,
        )
        self.mascara = Mascara.objects.create(
            nome="Máscara Genérica",
            tipos="",  # todos
            destino="Central Suporte",
            template="Protocolo: {{protocolo}} - Parceiro: {{parceiro}}",
            ativo=True,
        )
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv,
            tipo=TipoDemanda.OUTROS,
            pedido="PED-999",
            descricao="Demanda de teste",
        )

    def test_obter_destino_mascara_proprio(self):
        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.PROPRIO
        dest = self.perfil.obter_destino_mascara()
        self.assertEqual(dest["tipo"], "proprio")
        self.assertEqual(dest["jid"], "5531988880000")
        self.assertIn("Lucas Especialista", dest["nome"])
        self.assertTrue(dest["configurado"])

    def test_obter_destino_mascara_grupo(self):
        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.GRUPO
        self.perfil.mascara_grupo = self.grupo
        dest = self.perfil.obter_destino_mascara()
        self.assertEqual(dest["tipo"], "grupo")
        self.assertEqual(dest["jid"], "120363999999999@g.us")
        self.assertEqual(dest["nome"], "Grupo Suporte Central")
        self.assertTrue(dest["configurado"])

    def test_obter_destino_mascara_individual(self):
        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.INDIVIDUAL
        self.perfil.mascara_numero = "5511977776666"
        self.perfil.mascara_numero_nome = "Backoffice SP"
        dest = self.perfil.obter_destino_mascara()
        self.assertEqual(dest["tipo"], "individual")
        self.assertEqual(dest["jid"], "5511977776666")
        self.assertEqual(dest["nome"], "Backoffice SP")
        self.assertTrue(dest["configurado"])

    def test_form_salva_destino_grupo(self):
        from tickets.forms import EspecialistaForm

        form = EspecialistaForm(
            data={
                "first_name": "Lucas Atualizado",
                "username": "lucas_spec",
                "email": "lucas@example.com",
                "password": "",
                "fte": "1.00",
                "is_active": True,
                "eh_admin": False,
                "whatsapp": "5531988880000",
                "gerencia": "MG",
                "tipo_destino_mascara": PerfilStaff.TipoDestinoMascara.GRUPO,
                "mascara_grupo": self.grupo.pk,
                "mascara_grupo_custom": "",
                "mascara_numero": "",
                "mascara_numero_nome": "",
            },
            instance=self.spec_user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.tipo_destino_mascara, PerfilStaff.TipoDestinoMascara.GRUPO)
        self.assertEqual(self.perfil.mascara_grupo, self.grupo)

    def test_enviar_mascara_whatsapp_destino_grupo_do_especialista(self):
        from unittest.mock import patch
        from gestao.messaging.syncwa import SyncWAResult
        from tickets.services import enviar_mascara_whatsapp

        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.GRUPO
        self.perfil.mascara_grupo = self.grupo
        self.perfil.save()

        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp) as mock_send:
            ok, msg = enviar_mascara_whatsapp(self.ticket, self.mascara, user=self.spec_user)
            self.assertTrue(ok)
            self.assertIn("Grupo Suporte Central", msg)
            mock_send.assert_called_once()
            jid, texto = mock_send.call_args.args
            self.assertEqual(jid, "120363999999999@g.us")
            self.assertIn("Parceiro: Parceiro Lucas", texto)

    def test_ticket_mascaras_json_traz_destino_especialista(self):
        self.client.force_login(self.spec_user)
        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.GRUPO
        self.perfil.mascara_grupo = self.grupo
        self.perfil.save()

        url = reverse("ticket_mascaras_json", args=[self.ticket.protocolo])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("especialista", data)
        self.assertEqual(data["especialista"]["destino_tipo"], "grupo")
        self.assertEqual(data["especialista"]["destino_jid"], "120363999999999@g.us")
        self.assertTrue(data["especialista"]["configurado"])
        self.assertIn("destinos_disponiveis", data)

    def test_ticket_enviar_mascara_api(self):
        from unittest.mock import patch
        from gestao.messaging.syncwa import SyncWAResult

        self.client.force_login(self.spec_user)
        self.perfil.tipo_destino_mascara = PerfilStaff.TipoDestinoMascara.INDIVIDUAL
        self.perfil.mascara_numero = "5531999991234"
        self.perfil.mascara_numero_nome = "WhatsApp Central"
        self.perfil.save()

        url = reverse("ticket_enviar_mascara_api", args=[self.ticket.protocolo])
        fake_resp = SyncWAResult(ok=True)
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True), \
             patch("gestao.messaging.syncwa.enviar_texto", return_value=fake_resp):
            resp = self.client.post(url, {"mascara_id": self.mascara.id})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["ok"])
            self.assertIn("sucesso", data["mensagem"])

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )
    def test_fila_renderiza_botao_enviar_mascara(self):
        self.client.force_login(self.spec_user)
        url = reverse("fila")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'data-send-maska="{self.ticket.protocolo}"')
        self.assertContains(resp, "fila-action-group")
        self.assertContains(resp, "Responder")
        self.assertContains(resp, 'id="modal-enviar-mascara"')

    def test_especialista_form_renderiza_com_destinatario_sem_parceiro(self):
        from gestao.models import Destinatario
        User = get_user_model()
        gestor = User.objects.create_user(
            username="gestor_test",
            password="123",
            first_name="Admin Test",
            is_staff=True,
        )
        PerfilStaff.objects.create(
            user=gestor,
            papel=PerfilStaff.Papel.GESTOR,
        )
        # Cria grupo de WhatsApp sem parceiro vinculado (ex: grupo geral da gerência)
        Destinatario.objects.create(
            nome="Grupo Geral Operação",
            jid="120363000111222@g.us",
            tipo=Destinatario.TipoDestino.GRUPO,
            parceiro=None,
            ativo=True,
        )
        self.client.force_login(gestor)
        # GET /especialistas/<id>/ não deve dar 500
        url = reverse("especialista_editar", args=[self.spec_user.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Destino das Máscaras (WhatsApp)")
        self.assertContains(resp, "Grupo Geral Operação")

        # GET /perfil/ também deve renderizar normalmente
        self.client.force_login(self.spec_user)
        resp_perfil = self.client.get(reverse("meu_perfil"))
        self.assertEqual(resp_perfil.status_code, 200)
        self.assertContains(resp_perfil, "Destino das Máscaras (WhatsApp)")


@override_settings(STORAGES=STORAGES_TESTE)
class LoginUnificadoTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        from .models import ContaAcesso, ContatoParceiro, RegistroAcesso
        from .seguranca import garantir_conta_parceiro

        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user(
            "admin_nio", "a@x.com", "senha-admin-ok", first_name="Admin", is_staff=True
        )
        self.spec = User.objects.create_user(
            "spec_nio", "s@x.com", "senha-spec-ok1", first_name="Spec", is_staff=True
        )
        self.ger = User.objects.create_user(
            "ger_nio", "g@x.com", "senha-ger-ok01", first_name="Ger", is_staff=True
        )
        PerfilStaff.objects.create(user=self.admin, papel=PerfilStaff.Papel.GESTOR)
        PerfilStaff.objects.create(
            user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA, gerencia="MG INTERIOR"
        )
        PerfilStaff.objects.create(
            user=self.ger, papel=PerfilStaff.Papel.GERENCIA, gerencia="MG INTERIOR"
        )
        self.pdv = Parceiro.objects.create(
            codigo_pdv="9001",
            nome="PDV Login",
            especialista=self.spec,
            token_acesso="token-legado",
        )
        self.pdv_outro = Parceiro.objects.create(
            codigo_pdv="9002", nome="PDV Alheio", token_acesso="outro-token"
        )
        self.contato = ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Empresário Loja", cargo="Empresário"
        )
        self.user_pdv, _, _ = garantir_conta_parceiro(
            self.pdv, senha="token-legado", must_change=False
        )
        self.user_outro, _, _ = garantir_conta_parceiro(
            self.pdv_outro, senha="outro-token", must_change=False
        )
        self.ticket_pdv = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.RESET_SENHA, tt="TT9"
        )
        self.ticket_outro = Ticket.objects.create(
            parceiro=self.pdv_outro, tipo=TipoDemanda.STATUS_PEDIDO, pedido="1"
        )
        self.RegistroAcesso = RegistroAcesso
        self.ContaAcesso = ContaAcesso

    def test_visitante_nao_ve_lista_de_pdvs(self):
        r = self.client.get(reverse("abrir_demanda"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
        login = self.client.get(reverse("login"))
        self.assertEqual(login.status_code, 200)
        self.assertNotContains(login, "PDV Login")
        self.assertNotContains(login, "token-legado")
        self.assertContains(login, "Código PDV ou usuário")

    def test_dfv_e_consulta_exigem_login(self):
        for nome in ("consulta_dfv", "consulta_busca", "repositorio_lista", "tradehub"):
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 302, nome)
            self.assertIn("/login/", r["Location"])

    def test_parceiro_loga_com_codigo_e_token(self):
        r = self.client.post(
            reverse("login"),
            {"username": "9001", "password": "token-legado"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/abrir/inicio/") or "/abrir/" in r["Location"])

    def test_login_invalido_e_generico(self):
        r = self.client.post(
            reverse("login"),
            {"username": "9001", "password": "errada-demais"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuário ou senha inválidos")
        self.assertNotContains(r, "9001 não existe")

    def test_pdv_inativo_nao_loga(self):
        self.pdv.ativo = False
        self.pdv.save(update_fields=["ativo"])
        self.user_pdv.is_active = False
        self.user_pdv.save(update_fields=["is_active"])
        r = self.client.post(
            reverse("login"),
            {"username": "9001", "password": "token-legado"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuário ou senha inválidos")

    def test_troca_obrigatoria_prende_na_senha(self):
        self.ContaAcesso.objects.update_or_create(
            user=self.user_pdv, defaults={"must_change_password": True}
        )
        self.client.force_login(self.user_pdv)
        r = self.client.get(reverse("portal_parceiro"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/senha/trocar/", r["Location"])

    def test_protocolo_so_do_proprio_pdv(self):
        self.client.force_login(self.user_pdv)
        ok = self.client.get(reverse("consulta_protocolo", args=[self.ticket_pdv.protocolo]))
        self.assertEqual(ok.status_code, 200)
        outro = self.client.get(
            reverse("consulta_protocolo", args=[self.ticket_outro.protocolo])
        )
        self.assertEqual(outro.status_code, 404)

    def test_parceiro_nao_entra_na_fila(self):
        self.client.force_login(self.user_pdv)
        r = self.client.get(reverse("fila"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/abrir/", r["Location"])

    def test_gerencia_ve_pdv_da_gerencia(self):
        from .acesso import tickets_visiveis

        visiveis = list(tickets_visiveis(self.ger).values_list("id", flat=True))
        self.assertIn(self.ticket_pdv.id, visiveis)
        self.assertNotIn(self.ticket_outro.id, visiveis)

    def test_reset_hierarquico(self):
        from .acesso import pode_resetar_senha

        self.assertTrue(pode_resetar_senha(self.admin, self.user_pdv))
        self.assertTrue(pode_resetar_senha(self.admin, self.spec))
        self.assertTrue(pode_resetar_senha(self.ger, self.spec))
        self.assertTrue(pode_resetar_senha(self.ger, self.user_pdv))
        self.assertFalse(pode_resetar_senha(self.ger, self.admin))
        self.assertFalse(pode_resetar_senha(self.spec, self.ger))
        self.assertTrue(pode_resetar_senha(self.spec, self.user_pdv))
        self.assertFalse(pode_resetar_senha(self.spec, self.user_outro))

    def test_especialista_reseta_pdv_e_inativa(self):
        self.client.force_login(self.spec)
        r = self.client.post(reverse("acesso_resetar", args=[self.user_pdv.pk]))
        self.assertEqual(r.status_code, 302)
        self.user_pdv.refresh_from_db()
        self.assertTrue(self.ContaAcesso.objects.get(user=self.user_pdv).must_change_password)
        negado = self.client.post(reverse("acesso_resetar", args=[self.user_outro.pk]))
        self.assertEqual(negado.status_code, 404)
        ina = self.client.post(reverse("parceiro_inativar", args=[self.pdv.pk]))
        self.assertEqual(ina.status_code, 302)
        self.assertIn("escopo=inativos", ina["Location"])
        self.pdv.refresh_from_db()
        self.user_pdv.refresh_from_db()
        self.assertFalse(self.pdv.ativo)
        self.assertFalse(self.user_pdv.is_active)

    def test_lockout_apos_falhas(self):
        from .seguranca import FALHAS_LIMITE

        for _ in range(FALHAS_LIMITE):
            self.client.post(
                reverse("login"),
                {"username": "9001", "password": "nao-e-essa"},
            )
        r = self.client.post(
            reverse("login"),
            {"username": "9001", "password": "token-legado"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuário ou senha inválidos")

    def test_especialista_ve_portal_com_cards(self):
        self.client.force_login(self.spec)
        r = self.client.get(reverse("portal_inicio"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Kit de marca")
        self.assertContains(r, "Central de processos")
        self.assertContains(r, "Consulta DFV")
        self.assertContains(r, "Viabilidade VTAL")
        self.assertContains(r, reverse("fila"))
        self.assertContains(r, reverse("ticket_criar"))
        self.assertContains(r, reverse("rota_portal"))
        self.assertContains(r, "Rota")
        self.assertContains(r, reverse("vertical_portal"))
        self.assertContains(r, "Projeto Vertical")
        self.assertNotContains(r, "Quem está operando")
        login = self.client.post(
            reverse("login"),
            {"username": "spec_nio", "password": "senha-spec-ok1"},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("/abrir/", login["Location"])
        self.assertNotIn("/fila/", login["Location"])

    def test_gerencia_acessa_fila_e_acessos(self):
        self.client.force_login(self.ger)
        self.assertEqual(self.client.get(reverse("fila")).status_code, 200)
        self.assertEqual(self.client.get(reverse("acessos")).status_code, 200)
        self.assertEqual(self.client.get(reverse("mascaras")).status_code, 404)
        self.assertEqual(self.client.get(reverse("especialistas")).status_code, 404)

    def test_contato_escolhe_uma_vez_e_abre_formulario(self):
        from .models import ContatoParceiro

        ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Backoffice Loja", cargo="Backoffice"
        )
        self.client.force_login(self.user_pdv)
        picker = self.client.get(reverse("abrir_demanda_form"))
        self.assertEqual(picker.status_code, 302)
        self.assertIn("/abrir/contato/", picker["Location"])
        self.assertIn("next=formulario", picker["Location"])
        escolha = self.client.post(
            reverse("portal_contato") + "?next=formulario",
            {"contato": str(self.contato.pk), "next": "formulario"},
        )
        self.assertEqual(escolha.status_code, 302)
        self.assertIn("/abrir/formulario/", escolha["Location"])
        form = self.client.get(reverse("abrir_demanda_form"))
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, "Nova demanda")
        self.assertContains(form, "Empresário Loja")
        self.assertNotContains(form, "Quem está operando")
        lista = self.client.get(reverse("minhas_demandas"))
        self.assertEqual(lista.status_code, 200)
        de_novo = self.client.get(reverse("abrir_demanda"))
        self.assertEqual(de_novo.status_code, 302)
        self.assertIn("/abrir/formulario/", de_novo["Location"])
        picker_de_novo = self.client.get(reverse("portal_contato"))
        self.assertEqual(picker_de_novo.status_code, 302)
        self.assertIn("/abrir/inicio/", picker_de_novo["Location"])

    def test_command_migra_token(self):
        from django.core.management import call_command

        pdv = Parceiro.objects.create(
            codigo_pdv="9099", nome="Migrar", token_acesso="segredo-tok"
        )
        call_command("migrar_acessos_parceiro")
        pdv.refresh_from_db()
        self.assertIsNotNone(pdv.usuario_id)
        self.assertTrue(pdv.usuario.check_password("segredo-tok"))
        self.assertFalse(
            self.ContaAcesso.objects.get(user=pdv.usuario).must_change_password
        )




