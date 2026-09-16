from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tickets.models import ContatoParceiro, Parceiro

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
        self.assertContains(resp, "Trade Hub")
        self.assertContains(resp, "Manuais")
        self.assertContains(resp, "Enxoval Merchan")
        self.assertContains(resp, "Há custos associados ao uso do portal de parceiros?")

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
        self.assertContains(resp, "Trade Hub")
        self.assertContains(resp, "page-portal")
        self.assertContains(resp, "portal-cards")

    def test_extras_aparecem_na_home(self):
        resp = self.client.get(reverse("tradehub"))
        self.assertContains(resp, "Prospecção")
        self.assertContains(resp, "PAP Alto Valor")
