from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestao.messaging.syncwa import SyncWAError, SyncWAResult

from tickets.models import ConviteReuniao, Parceiro, PerfilStaff
from tickets.reuniao import mensagem_convite, normalizar_link

STORAGES_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STORAGES_TESTE)
class ReuniaoAcessoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec = User.objects.create_user(
            username="spec-reuniao", password="senha-spec-ok1", first_name="Marina"
        )
        PerfilStaff.objects.create(
            user=self.spec,
            papel=PerfilStaff.Papel.ESPECIALISTA,
            whatsapp="31988887777",
        )
        self.ger = User.objects.create_user(
            username="ger-reuniao", password="senha-ger-ok1", first_name="Gerencia"
        )
        PerfilStaff.objects.create(user=self.ger, papel=PerfilStaff.Papel.GERENCIA)
        self.gestor = User.objects.create_user(
            username="adm-reuniao", password="senha-adm-ok1", first_name="Admin"
        )
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="REU1", nome="PDV Reuniao")
        self.parceiro = User.objects.create_user(
            username=self.pdv.codigo_pdv, password="senha-pdv-ok1", first_name="Loja"
        )
        self.pdv.usuario = self.parceiro
        self.pdv.save(update_fields=["usuario"])

    def test_anonimo_vai_para_login(self):
        resp = self.client.get(reverse("reunioes"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_somente_especialista_abre_e_ve_o_modulo(self):
        self.client.force_login(self.spec)
        pagina = self.client.get(reverse("reunioes"))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Enviar para o meu WhatsApp")
        self.assertContains(pagina, "+55 (31) 98888-7777")
        portal = self.client.get(reverse("portal_inicio"))
        self.assertContains(portal, reverse("reunioes"))
        self.assertContains(portal, "Reuniões")

    def test_outros_perfis_nao_veem_nem_abrem(self):
        for user in (self.ger, self.gestor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("reunioes")).status_code, 404)
            portal = self.client.get(reverse("portal_inicio"))
            self.assertNotContains(portal, reverse("reunioes"))
        self.client.force_login(self.parceiro)
        resp = self.client.get(reverse("reunioes"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("portal_parceiro"), resp["Location"])


@override_settings(STORAGES=STORAGES_TESTE)
class ReuniaoEnvioTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.spec = User.objects.create_user(
            username="spec-envio", password="senha-spec-ok1", first_name="Marina", last_name="Costa"
        )
        PerfilStaff.objects.create(
            user=self.spec,
            papel=PerfilStaff.Papel.ESPECIALISTA,
            whatsapp="31988887777",
        )
        self.client.force_login(self.spec)
        self.payload = {
            "assunto": "Alinhamento semanal",
            "data": "2026-11-05",
            "hora": "14:30",
            "link": "meet.google.com/abc-defg-hij",
        }

    def test_envia_para_o_whatsapp_do_proprio_especialista(self):
        fake = SyncWAResult(ok=True, message_log_id="msg-1")
        with (
            patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True),
            patch("gestao.messaging.instancia.instancia_para_envio", return_value="inst-teste"),
            patch("gestao.messaging.syncwa.enviar_texto", return_value=fake) as envio,
        ):
            resp = self.client.post(reverse("reunioes"), self.payload)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("reunioes"))
        envio.assert_called_once()
        jid, texto = envio.call_args.args
        self.assertEqual(jid, "5531988887777")
        self.assertEqual(envio.call_args.kwargs["instance"], "inst-teste")
        self.assertIn("*Reunião: Alinhamento semanal*", texto)
        self.assertIn("quinta-feira, 05/11/2026", texto)
        self.assertIn("14:30", texto)
        self.assertIn("https://meet.google.com/abc-defg-hij", texto)
        convite = ConviteReuniao.objects.get()
        self.assertEqual(convite.especialista, self.spec)
        self.assertEqual(convite.status, ConviteReuniao.Status.ENVIADO)
        self.assertEqual(convite.link, "https://meet.google.com/abc-defg-hij")
        self.assertEqual(convite.destino_jid, "5531988887777")
        self.assertEqual(convite.syncwa_message_id, "msg-1")

    def test_sem_telefone_nao_dispara_envio(self):
        self.spec.perfil_staff.whatsapp = ""
        self.spec.perfil_staff.save(update_fields=["whatsapp"])
        with patch("gestao.messaging.syncwa.enviar_texto") as envio:
            resp = self.client.post(reverse("reunioes"), self.payload)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cadastre o WhatsApp")
        envio.assert_not_called()
        self.assertEqual(ConviteReuniao.objects.count(), 0)

    def test_link_invalido_e_assunto_curto(self):
        resp = self.client.post(
            reverse("reunioes"),
            {**self.payload, "assunto": "ok", "link": "javascript:alert(1)"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pelo menos 3 caracteres")
        self.assertContains(resp, "link http ou https")
        self.assertEqual(ConviteReuniao.objects.count(), 0)

    def test_falha_de_envio_fica_no_historico_sem_detalhe_tecnico(self):
        fake = SyncWAResult(ok=False, error="HTTP 500: token secreto")
        with (
            patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True),
            patch("gestao.messaging.instancia.instancia_para_envio", return_value="inst-teste"),
            patch("gestao.messaging.syncwa.enviar_texto", return_value=fake),
        ):
            resp = self.client.post(reverse("reunioes"), self.payload)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Não foi possível enviar agora")
        self.assertNotContains(resp, "token secreto")
        convite = ConviteReuniao.objects.get()
        self.assertEqual(convite.status, ConviteReuniao.Status.ERRO)
        self.assertIn("HTTP 500", convite.erro)

    def test_whatsapp_desconectado_mostra_o_pedido_de_conexao(self):
        with (
            patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True),
            patch(
                "gestao.messaging.instancia.instancia_para_envio",
                side_effect=SyncWAError("Conecte seu WhatsApp em Comunicação → WhatsApp."),
            ),
        ):
            resp = self.client.post(reverse("reunioes"), self.payload)
        self.assertContains(resp, "Conecte seu WhatsApp")

    def test_historico_nao_mostra_convite_de_outro_especialista(self):
        User = get_user_model()
        outro = User.objects.create_user(username="outro-spec", password="senha-spec-ok1")
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.ESPECIALISTA)
        inicio = timezone.make_aware(datetime(2026, 11, 5, 9, 0), timezone.get_current_timezone())
        ConviteReuniao.objects.create(
            especialista=outro,
            assunto="Reunião secreta do outro",
            inicio=inicio,
            link="https://meet.google.com/outro",
            destino_jid="5531999990000",
            mensagem="privada",
            status=ConviteReuniao.Status.ENVIADO,
        )
        ConviteReuniao.objects.create(
            especialista=self.spec,
            assunto="Meu alinhamento",
            inicio=inicio,
            link="https://meet.google.com/meu",
            destino_jid="5531988887777",
            mensagem="minha",
            status=ConviteReuniao.Status.ENVIADO,
        )
        with patch("gestao.messaging.syncwa.syncwa_configurado", return_value=True):
            resp = self.client.get(reverse("reunioes"))
        self.assertContains(resp, "Meu alinhamento")
        self.assertNotContains(resp, "Reunião secreta do outro")

    def test_mensagem_e_link(self):
        inicio = timezone.make_aware(datetime(2026, 11, 5, 14, 30), timezone.get_current_timezone())
        texto = mensagem_convite("Alinhamento semanal", inicio, "https://meet.google.com/abc")
        self.assertIn("quinta-feira, 05/11/2026", texto)
        self.assertTrue(texto.strip().endswith("https://meet.google.com/abc"))
        self.assertEqual(
            normalizar_link("meet.google.com/abc-defg-hij"),
            "https://meet.google.com/abc-defg-hij",
        )
        self.assertEqual(normalizar_link("javascript:alert(1)"), "javascript:alert(1)")
