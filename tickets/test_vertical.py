# -*- coding: utf-8 -*-
"""Testes do card Projeto Vertical."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tickets.models import ContatoParceiro, Parceiro, PerfilStaff, SolicitacaoVertical

STORAGES_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _arquivo(nome: str, conteudo: bytes = b"x") -> SimpleUploadedFile:
    return SimpleUploadedFile(nome, conteudo, content_type="application/octet-stream")


@override_settings(STORAGES=STORAGES_TESTE)
class VerticalPortalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_user("vert-admin", password="senha-ok-1234", first_name="Admin")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.spec = User.objects.create_user("vert-spec", password="senha-ok-1234", first_name="Spec")
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        self.pdv = Parceiro.objects.create(codigo_pdv="VERT1", nome="PDV Vertical")
        self.contato = ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Contato Vertical", cargo="Empresário"
        )
        self.pdv_user = User.objects.create_user(
            username=self.pdv.codigo_pdv, password="senha-pdv-ok1", first_name="Pdv"
        )
        self.pdv.usuario = self.pdv_user
        self.pdv.save(update_fields=["usuario"])

    def _login_pdv(self):
        self.client.force_login(self.pdv_user)
        session = self.client.session
        session["contato_id"] = self.contato.id
        session.save()

    def test_card_no_portal_equipe(self):
        self.client.force_login(self.spec)
        r = self.client.get(reverse("portal_inicio"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Projeto Vertical")
        self.assertContains(r, reverse("vertical_portal"))

    def test_card_no_portal_pdv(self):
        self._login_pdv()
        r = self.client.get(reverse("portal_parceiro"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Projeto Vertical")

    def test_pagina_equipe(self):
        self.client.force_login(self.spec)
        r = self.client.get(reverse("vertical_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Projeto Vertical")
        self.assertContains(r, "Nova solicitação")
        self.assertContains(r, "CNPJ por cidade")
        self.assertContains(r, ">Acionamentos<")
        self.assertNotContains(r, "Meus acionamentos")
        self.assertContains(r, 'data-acionado-por="Spec"')
        self.assertContains(r, 'id="inp_acionado_por"')
        self.assertNotContains(r, 'name="criado_por_id"')
        self.assertNotContains(r, "Configuração de resumo")

    def test_pagina_gestor_tem_config(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("vertical_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Configuração de resumo")

    def test_pdv_sem_contato_redireciona(self):
        self.client.force_login(self.pdv_user)
        r = self.client.get(reverse("vertical_portal"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=vertical", r["Location"])

    def test_pagina_pdv_acionado_pelo_contato(self):
        self._login_pdv()
        r = self.client.get(reverse("vertical_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-acionado-por="Contato Vertical"')
        self.assertContains(r, 'value="Contato Vertical"')
        self.assertContains(r, "Meus acionamentos")
        self.assertNotContains(r, 'name="criado_por_id"')

    def test_criar_e_dashboard(self):
        self.client.force_login(self.spec)
        r = self.client.post(
            reverse("vertical_api_solicitacoes"),
            {
                "nome_condominio": "Ed. Horizonte",
                "nome_sindico": "Maria",
                "contato": "31999998888",
                "cep": "30130100",
                "logradouro": "Rua A",
                "numero": "100",
                "bairro": "Centro",
                "cidade": "Belo Horizonte",
                "uf": "MG",
                "infraestrutura": "AEREA",
                "dados_blocos_json": '[{"nome":"A","andares":10,"aptos":4,"total":40}]',
                "arquivo_carta": _arquivo("carta.pdf"),
                "arquivo_fachada": _arquivo("fachada.jpg"),
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertTrue(body["ok"])
        item = SolicitacaoVertical.objects.get()
        self.assertEqual(item.nome_condominio, "Ed. Horizonte")
        self.assertEqual(item.total_hps, 40)
        self.assertEqual(item.pre_venda_minima, 4)
        self.assertEqual(item.blocos.count(), 1)
        self.assertIsNone(item.contato_id)
        self.assertEqual(item.criado_por_id, self.spec.id)
        self.assertIn("Projeto Vertical", body["data"]["resumo"])
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(lista["data"][0]["criado_por_nome"], "Spec")

        dash = self.client.get(reverse("vertical_api_dashboard")).json()
        self.assertEqual(dash["data"]["total_acionamentos"], 1)
        self.assertEqual(dash["data"]["total_hps"], 40)
        self.assertEqual(dash["data"]["total_prevenda"], 4)
        self.assertEqual(dash["data"]["vendas_realizadas"], 0)

    def test_especialista_nao_ve_de_outro(self):
        outro = get_user_model().objects.create_user("vert-spec2", password="senha-ok-1234")
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.ESPECIALISTA)
        SolicitacaoVertical.objects.create(
            nome_condominio="Outro Cond",
            nome_sindico="Joao",
            contato_sindico="31988887777",
            cep="30000000",
            numero="1",
            criado_por=outro,
        )
        self.client.force_login(self.spec)
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(lista["data"], [])
        dash = self.client.get(reverse("vertical_api_dashboard")).json()
        self.assertEqual(dash["data"]["total_acionamentos"], 0)

    def test_gestor_ve_todos_e_edita_status(self):
        item = SolicitacaoVertical.objects.create(
            nome_condominio="Cond Spec",
            nome_sindico="Ana",
            contato_sindico="31977776666",
            cep="30140071",
            numero="50",
            criado_por=self.spec,
        )
        self.client.force_login(self.gestor)
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(len(lista["data"]), 1)
        self.assertTrue(lista["data"][0]["can_edit"])
        r = self.client.patch(
            reverse("vertical_api_solicitacao", args=[item.id]),
            data='{"status":"EM_PROJETO","observacao":"ok"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        item.refresh_from_db()
        self.assertEqual(item.status, SolicitacaoVertical.Status.EM_PROJETO)
        self.assertEqual(item.observacao, "ok")

    def test_especialista_nao_altera_status_nem_exclui(self):
        item = SolicitacaoVertical.objects.create(
            nome_condominio="Meu Cond",
            nome_sindico="Ana",
            contato_sindico="31977776666",
            cep="30140071",
            numero="50",
            criado_por=self.spec,
        )
        self.client.force_login(self.spec)
        r = self.client.patch(
            reverse("vertical_api_solicitacao", args=[item.id]),
            data='{"status":"CONCLUIDA"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)
        r = self.client.delete(reverse("vertical_api_solicitacao", args=[item.id]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(SolicitacaoVertical.objects.filter(pk=item.id).exists())

    def test_config_so_gestao(self):
        self.client.force_login(self.spec)
        self.assertEqual(self.client.get(reverse("vertical_api_config")).status_code, 403)
        self.client.force_login(self.gestor)
        r = self.client.post(
            reverse("vertical_api_config"),
            {"destinatarios": "31999990000", "ativo": "1"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["destinatarios"], "31999990000")

    def test_criar_exige_anexos(self):
        self.client.force_login(self.spec)
        r = self.client.post(
            reverse("vertical_api_solicitacoes"),
            {
                "nome_condominio": "Sem arquivo",
                "nome_sindico": "Maria",
                "contato": "31999998888",
                "numero": "1",
            },
        )
        self.assertEqual(r.status_code, 422)

    def test_pdv_cria_grava_contato_logado(self):
        self._login_pdv()
        r = self.client.post(
            reverse("vertical_api_solicitacoes"),
            {
                "nome_condominio": "Ed. PDV",
                "nome_sindico": "Maria",
                "contato": "31999998888",
                "cep": "30130100",
                "logradouro": "Rua A",
                "numero": "100",
                "arquivo_carta": _arquivo("carta.pdf"),
                "arquivo_fachada": _arquivo("fachada.jpg"),
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        item = SolicitacaoVertical.objects.get()
        self.assertEqual(item.contato_id, self.contato.id)
        self.assertEqual(item.criado_por_id, self.pdv_user.id)
        self.assertEqual(item.parceiro_id, self.pdv.id)
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(lista["data"][0]["criado_por_nome"], "Contato Vertical")

    def test_especialista_ve_pedido_do_parceiro(self):
        self.pdv.especialista = self.spec
        self.pdv.save(update_fields=["especialista"])
        outro = get_user_model().objects.create_user("vert-spec2", password="senha-ok-1234")
        PerfilStaff.objects.create(user=outro, papel=PerfilStaff.Papel.ESPECIALISTA)
        self._login_pdv()
        r = self.client.post(
            reverse("vertical_api_solicitacoes"),
            {
                "nome_condominio": "Ed. Carteira Ricardo",
                "nome_sindico": "Maria",
                "contato": "31999998888",
                "cep": "30130100",
                "logradouro": "Rua A",
                "numero": "100",
                "arquivo_carta": _arquivo("carta.pdf"),
                "arquivo_fachada": _arquivo("fachada.jpg"),
            },
        )
        self.assertEqual(r.status_code, 201, r.content)

        self.client.force_login(self.spec)
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(len(lista["data"]), 1)
        self.assertEqual(lista["data"][0]["nome"], "Ed. Carteira Ricardo")
        self.assertEqual(lista["data"][0]["parceiro_nome"], "PDV Vertical")
        dash = self.client.get(reverse("vertical_api_dashboard")).json()
        self.assertEqual(dash["data"]["total_acionamentos"], 1)

        self.client.force_login(outro)
        lista_outro = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(lista_outro["data"], [])
        dash_outro = self.client.get(reverse("vertical_api_dashboard")).json()
        self.assertEqual(dash_outro["data"]["total_acionamentos"], 0)

        self.client.force_login(self.gestor)
        lista_gestor = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(len(lista_gestor["data"]), 1)

    def test_especialista_ve_pedido_via_contato_sem_parceiro_fk(self):
        self.pdv.especialista = self.spec
        self.pdv.save(update_fields=["especialista"])
        SolicitacaoVertical.objects.create(
            nome_condominio="Cond sem FK parceiro",
            nome_sindico="Joao",
            contato_sindico="31988887777",
            cep="30000000",
            numero="1",
            criado_por=self.pdv_user,
            contato=self.contato,
            parceiro=None,
        )
        self.client.force_login(self.spec)
        lista = self.client.get(reverse("vertical_api_solicitacoes")).json()
        self.assertEqual(len(lista["data"]), 1)
        self.assertEqual(lista["data"][0]["nome"], "Cond sem FK parceiro")

    @patch("tickets.vertical_services.urllib.request.urlopen")
    def test_viacep(self, urlopen):
        class Fake:
            def read(self):
                return b'{"logradouro":"Rua da Bahia","bairro":"Centro","localidade":"Belo Horizonte","uf":"MG","cep":"30160-011"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        urlopen.return_value = Fake()
        self.client.force_login(self.spec)
        r = self.client.get(reverse("vertical_api_viacep", args=["30160011"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["cidade"], "Belo Horizonte")
        self.assertEqual(r.json()["data"]["uf"], "MG")


class VerticalServicesTests(TestCase):
    def test_parse_blocos_e_prevenda(self):
        from tickets.vertical_services import parse_blocos

        blocos = parse_blocos('[{"nome":"Torre","andares":5,"aptos":2}]')
        self.assertEqual(blocos[0]["total"], 10)
        self.assertEqual(len(parse_blocos("")), 0)

    def test_nome_acionado_prefere_contato(self):
        from tickets.vertical_services import nome_acionado

        User = get_user_model()
        user = User.objects.create_user("vert-nome", password="senha-ok-1234", first_name="Usuario")
        pdv = Parceiro.objects.create(codigo_pdv="VERTN", nome="PDV Nome")
        contato = ContatoParceiro.objects.create(parceiro=pdv, nome="Contato da Sessao")
        item = SolicitacaoVertical.objects.create(
            nome_condominio="Cond",
            nome_sindico="Ana",
            contato_sindico="31977776666",
            cep="30140071",
            numero="50",
            criado_por=user,
            contato=contato,
        )
        self.assertEqual(nome_acionado(item), "Contato da Sessao")
        item.contato = None
        self.assertEqual(nome_acionado(item), "Usuario")
