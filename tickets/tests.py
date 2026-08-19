from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from .acesso import eh_gestor, tickets_visiveis
from .demanda_campos import montar_abas_tratamento
from .forms import MultipleFileField, TicketCreateForm, TicketTreatForm
from .models import Parceiro, PerfilStaff, Ticket, TipoDemanda, formatar_duracao


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


class TratamentoModalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("gestor", "g@x.com", "x")
        self.pdv = Parceiro.objects.create(codigo_pdv="100", nome="PDV")
        self.ticket = Ticket.objects.create(
            parceiro=self.pdv, tipo=TipoDemanda.RESET_SENHA, tt="TT99"
        )

    def test_primeira_aba_e_campo_da_resposta(self):
        form = TicketTreatForm(instance=self.ticket)
        abas = montar_abas_tratamento(form)
        self.assertTrue(abas[0]["principal"])
        self.assertEqual(abas[0]["id"], "senha_resetada")

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
        self.ticket.resposta_iniciada_em = timezone.now() - timedelta(seconds=12)
        self.ticket.save(update_fields=["resposta_iniciada_em"])

        r = self.client.post(
            reverse("ticket_responder", args=[self.ticket.protocolo]),
            {
                "action": "tratar",
                "tipo": TipoDemanda.RESET_SENHA,
                "status": self.ticket.status,
                "prioridade": self.ticket.prioridade,
                "senha_resetada": "Nio@123",
                "resultado_status": "SENHA RESETADA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.tempo_retorno_segundos)
        self.assertGreaterEqual(self.ticket.tempo_retorno_segundos, 12)
        self.assertIn("Nio@123", self.ticket.resposta_publica)
