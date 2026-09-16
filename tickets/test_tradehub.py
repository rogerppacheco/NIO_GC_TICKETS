from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tickets.models import ContatoParceiro, Parceiro, PerfilStaff

STORAGES_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STORAGES_TESTE)
class TradeHubPagesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.pdv = Parceiro.objects.create(codigo_pdv="TH1", nome="PDV Trade")
        user = User.objects.create_user(
            username=self.pdv.codigo_pdv, password="senha-pdv-ok1", first_name="Loja"
        )
        self.pdv.usuario = user
        self.pdv.save(update_fields=["usuario"])
        ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Empresário TH", cargo="Empresário"
        )
        self.client.force_login(user)
        session = self.client.session
        session["contato_id"] = self.pdv.contatos.first().id
        session.save()

    def test_anonimo_vai_para_login(self):
        self.client.logout()
        resp = self.client.get(reverse("tradehub"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_home_lista_categorias_e_faq(self):
        resp = self.client.get(reverse("tradehub"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kit de marca")
        self.assertNotContains(resp, "Trade Hub")
        self.assertContains(resp, "Manuais")
        self.assertContains(resp, "Enxoval Merchan")
        self.assertContains(resp, "Para o PDV")
        self.assertContains(resp, "Antes de baixar")
        self.assertContains(resp, "Baixar estes arquivos tem custo?")
        self.assertNotContains(resp, "Uso interno")
        self.assertNotContains(resp, "Tire as suas dúvidas")

    def test_secao_manuais_mostra_destaques(self):
        resp = self.client.get(reverse("tradehub_secao", args=["manuais"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manual de Boas Vindas")
        self.assertContains(resp, "Manual Toolkit")

    def test_pasta_aninhada(self):
        resp = self.client.get(reverse("tradehub_pasta", args=["manuais", "manuais_toolkit"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Toolkit")

    def test_categoria_inexistente(self):
        resp = self.client.get(reverse("tradehub_secao", args=["nao-existe"]))
        self.assertEqual(resp.status_code, 404)

    def test_arquivo_ausente(self):
        resp = self.client.get(reverse("tradehub_arquivo", args=["materiais/nao-existe.pdf"]))
        self.assertEqual(resp.status_code, 404)

    def test_nao_escapa_da_pasta_tradehub(self):
        resp = self.client.get("/tradehub/arquivo/../../config/settings.py")
        self.assertIn(resp.status_code, {404, 400, 302})

    def test_portal_tem_card(self):
        resp = self.client.get(reverse("portal_parceiro"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("tradehub"))
        self.assertContains(resp, "Kit de marca")
        self.assertContains(resp, "page-portal")
        self.assertContains(resp, "portal-cards")

    def test_extras_restritas_nao_aparecem_para_pdv(self):
        resp = self.client.get(reverse("tradehub"))
        self.assertNotContains(resp, "Prospecção")
        self.assertNotContains(resp, "PAP Alto Valor")

    def test_pdv_nao_abre_secoes_restritas(self):
        for slug in ("prospeccao", "pap_alto_valor"):
            resp = self.client.get(reverse("tradehub_secao", args=[slug]))
            self.assertEqual(resp.status_code, 404, slug)

    def test_pdv_nao_baixa_arquivo_restrito(self):
        resp = self.client.get(
            reverse("tradehub_arquivo", args=["materiais/prospeccao/qualquer.pdf"])
        )
        self.assertEqual(resp.status_code, 404)


@override_settings(STORAGES=STORAGES_TESTE)
class TradeHubEquipeTests(TestCase):
    def _login_staff(self, papel):
        User = get_user_model()
        user = User.objects.create_user(
            username=f"th-{papel.lower()}", password="senha-staff-ok1", first_name="Equipe"
        )
        PerfilStaff.objects.create(user=user, papel=papel)
        self.client.force_login(user)
        return user

    def test_especialista_ve_cards_restritos(self):
        self._login_staff(PerfilStaff.Papel.ESPECIALISTA)
        resp = self.client.get(reverse("tradehub"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kit de marca")
        self.assertContains(resp, "Prospecção")
        self.assertContains(resp, "PAP Alto Valor")
        self.assertContains(resp, "Uso interno")

    def test_gerencia_ve_cards_restritos(self):
        self._login_staff(PerfilStaff.Papel.GERENCIA)
        resp = self.client.get(reverse("tradehub"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Prospecção")
        self.assertContains(resp, "PAP Alto Valor")

    def test_gestor_nao_ve_cards_restritos(self):
        self._login_staff(PerfilStaff.Papel.GESTOR)
        resp = self.client.get(reverse("tradehub"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Prospecção")
        self.assertNotContains(resp, "PAP Alto Valor")
        self.assertEqual(
            self.client.get(reverse("tradehub_secao", args=["prospeccao"])).status_code,
            404,
        )

    def test_especialista_abre_secao_restrita(self):
        self._login_staff(PerfilStaff.Papel.ESPECIALISTA)
        resp = self.client.get(reverse("tradehub_secao", args=["prospeccao"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Prospecção")
