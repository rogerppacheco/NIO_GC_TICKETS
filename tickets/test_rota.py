# -*- coding: utf-8 -*-
"""Testes do card Rota."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestao.models import ConfiguracaoOSAB
from tickets.consultas.dfv_powerbi_service import consultar_agregado_por_bairro
from tickets.models import (
    CheckinRotaDiaria,
    ContatoParceiro,
    Parceiro,
    ParceiroPraca,
    PlanejamentoSemanalRota,
)
from tickets.rota_services import classificar_alerta, meta_semana_parceiro, parse_hora, salvar_checkin


class RotaServicesTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="ROTA1", nome="PDV Rota")
        self.contato = ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Empresário Rota", cargo="Empresário"
        )
        ConfiguracaoOSAB.objects.create(
            parceiro=self.pdv,
            ano=timezone.localdate().year,
            mes=timezone.localdate().month,
            meta_vl=200,
            plano_dia=8,
        )

    def test_meta_semana_derivada_meta_vl(self):
        meta = meta_semana_parceiro(self.pdv)
        self.assertEqual(meta["valor"], 50)
        self.assertEqual(meta["fonte"], "derivada_meta_vl")

    def test_parse_hora(self):
        self.assertEqual(parse_hora("08:00").hour, 8)
        self.assertEqual(parse_hora("18:30:00").minute, 30)
        self.assertIsNone(parse_hora(""))
        with self.assertRaises(ValueError):
            parse_hora("25:00")

    def test_arranjo_rotas_mesma_ou_distinta(self):
        from tickets.rota_services import aplicar_arranjo_rotas, flags_arranjo, validar_locais

        equipes = [
            {"ordem": 1, "atuacao": "PAP", "pessoas": 2, "uf": "MG", "cidade": "BH", "bairro": "CENTRO"},
            {"ordem": 2, "atuacao": "PAP", "pessoas": 1, "uf": "MG", "cidade": "BH", "bairro": "SAVASSI"},
        ]
        mesma, dividir = flags_arranjo(equipes, mesma_rota=False, dividir_bairros=True)
        self.assertFalse(mesma)
        self.assertFalse(dividir)
        uma, uma_dividir = flags_arranjo(
            [equipes[0]], mesma_rota=False, dividir_bairros=True
        )
        self.assertTrue(uma)
        self.assertTrue(uma_dividir)
        fields = validar_locais(equipes, mesma_rota=False, dividir_bairros=False)
        self.assertEqual(fields, {})
        juntas = aplicar_arranjo_rotas(
            [dict(e) for e in equipes],
            mesma_rota=True,
            dividir_bairros=False,
            uf="MT",
            cidade="CUIABA",
            bairro="CENTRO NORTE",
        )
        self.assertEqual(juntas[0]["bairro"], "CENTRO NORTE")
        self.assertEqual(juntas[1]["bairro"], "CENTRO NORTE")

    def test_listar_ufs_sempre_as_27(self):
        from tickets.rota_services import UFS_BRASIL, listar_ufs

        ParceiroPraca.objects.create(
            parceiro=self.pdv, uf="MG", cidade="BELO HORIZONTE", bairro="CENTRO"
        )
        ufs = [i["uf"] for i in listar_ufs(self.pdv)]
        self.assertEqual(ufs, list(UFS_BRASIL))
        self.assertEqual(len(ufs), 27)

    def test_classificar_alerta(self):
        status, desvio, _msg = classificar_alerta(50, 50)
        self.assertEqual(status, PlanejamentoSemanalRota.StatusAlerta.OK)
        status, desvio, _msg = classificar_alerta(40, 50)
        self.assertEqual(status, PlanejamentoSemanalRota.StatusAlerta.ABAIXO)
        status, desvio, _msg = classificar_alerta(30, 50)
        self.assertEqual(status, PlanejamentoSemanalRota.StatusAlerta.CRITICO)

    def test_salvar_checkin_digital(self):
        checkin = salvar_checkin(
            parceiro=self.pdv,
            contato=self.contato,
            tipo_rota="DIGITAL",
            qtd_vendedores=3,
            vendas_planejadas_semana=45 if timezone.localdate().weekday() == 0 else None,
            horario_inicio="08:00",
            horario_fim="18:00",
        )
        self.assertEqual(checkin.tipo_rota, "DIGITAL")
        self.assertEqual(checkin.qtd_vendedores, 3)
        self.assertEqual(checkin.qtd_equipes, 1)
        self.assertEqual(checkin.equipes[0]["atuacao"], "DIGITAL")
        self.assertEqual(checkin.horario_inicio.hour, 8)
        self.assertEqual(checkin.horario_fim.hour, 18)


class RotaApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.pdv = Parceiro.objects.create(codigo_pdv="ROTA2", nome="PDV Rota API")
        self.contato = ContatoParceiro.objects.create(
            parceiro=self.pdv, nome="Contato API", cargo="Empresário"
        )
        ParceiroPraca.objects.create(
            parceiro=self.pdv, uf="MG", cidade="BELO HORIZONTE", bairro="CENTRO"
        )
        ConfiguracaoOSAB.objects.create(
            parceiro=self.pdv,
            ano=timezone.localdate().year,
            mes=timezone.localdate().month,
            meta_vl=100,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username=self.pdv.codigo_pdv, password="senha-pdv-ok1", first_name="Rota"
        )
        self.pdv.usuario = self.user
        self.pdv.save(update_fields=["usuario"])
        self.client.force_login(self.user)
        session = self.client.session
        session["contato_id"] = self.contato.id
        session.save()

    def test_hoje_requer_sessao(self):
        c = Client()
        r = c.get(reverse("rota_api_hoje"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_hoje_ok(self):
        r = self.client.get(reverse("rota_api_hoje"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["defaults"]["uf"], "MG")
        self.assertEqual(body["data"]["meta_semana"]["valor"], 25)
        self.assertEqual(len(body["data"]["semana"]["dias"]), 7)

    def test_ufs_e_cidades(self):
        # Duplicata com casing diferente não deve repetir UF na API
        ParceiroPraca.objects.create(
            parceiro=self.pdv, uf="mg", cidade="Contagem", bairro="Centro"
        )
        r = self.client.get(reverse("rota_api_ufs"))
        self.assertEqual(r.status_code, 200)
        ufs = [i["uf"] for i in r.json()["data"]["items"]]
        self.assertEqual(ufs.count("MG"), 1)
        self.assertEqual(len(ufs), len(set(ufs)))
        from tickets.rota_services import UFS_BRASIL

        self.assertEqual(ufs, list(UFS_BRASIL))
        self.assertIn("SP", ufs)
        self.assertIn("RJ", ufs)
        self.assertIn("AC", ufs)

        r = self.client.get(reverse("rota_api_cidades"), {"uf": "MG"})
        self.assertEqual(r.status_code, 200)
        cidades = [i["cidade"] for i in r.json()["data"]["items"]]
        self.assertTrue(any(c.upper() == "BELO HORIZONTE" for c in cidades))
        self.assertEqual(len(cidades), len({c.casefold() for c in cidades}))

    def test_bairros_da_praca(self):
        r = self.client.get(
            reverse("rota_api_bairros"),
            {"uf": "MG", "cidade": "BELO HORIZONTE"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()["data"]
        self.assertEqual(body["fonte"], "parceiro_praca")
        self.assertEqual(body["items"][0]["bairro"], "CENTRO")

    @patch("tickets.rota_views.consultar_agregado_por_bairro")
    def test_checkin_presencial(self, mock_dfv):
        mock_dfv.return_value = {
            "local": {"uf": "MG", "cidade": "BELO HORIZONTE", "bairro": "CENTRO"},
            "indicadores": {
                "hp_livre": 10,
                "hps": 20,
                "hcs": 5,
                "pct_hc": 25.0,
                "fachadas_viaveis": 8,
                "fachadas_total": 10,
            },
            "credito": {"faixa_predominante": "Entre 50% e 70%", "distribuicao": []},
            "perfil": {"classificacao_predominante": "MEDIO", "celulas": [], "cdos_distintos": 1},
            "alertas": [{"codigo": "hp_novo", "severidade": "info", "titulo": "x", "detalhe": "y"}],
            "meta": {"fonte": "test", "incompleto": False},
        }
        payload = {
            "tipo_rota": "PRESENCIAL",
            "qtd_vendedores": 2,
            "uf": "MG",
            "cidade": "BELO HORIZONTE",
            "bairro": "CENTRO",
            "horario_inicio": "08:00",
            "horario_fim": "17:30",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 20

        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertIn(r.status_code, (200, 201))
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["dfv_snapshot"]["hp_livre"], 10)
        self.assertTrue(
            CheckinRotaDiaria.objects.filter(parceiro=self.pdv, data=timezone.localdate()).exists()
        )
        ck = CheckinRotaDiaria.objects.get(parceiro=self.pdv, data=timezone.localdate())
        self.assertEqual(ck.tipo_rota, "PAP")

    @patch("tickets.rota_views.consultar_agregado_por_bairro")
    def test_checkin_equipes_e_movimento(self, mock_dfv):
        mock_dfv.return_value = {
            "local": {"uf": "MG", "cidade": "BELO HORIZONTE", "bairro": "CENTRO"},
            "indicadores": {"hp_livre": 4, "hps": 8, "pct_hc": 10, "fachadas_viaveis": 2, "fachadas_total": 3},
            "credito": {"faixa_predominante": "Entre 50% e 70%"},
            "perfil": {},
            "alertas": [],
            "meta": {"fonte": "test", "incompleto": False},
        }
        payload = {
            "equipes": [
                {"atuacao": "PAP", "pessoas": 3},
                {"atuacao": "DIGITAL", "pessoas": 2},
            ],
            "qtd_contratacoes": 1,
            "qtd_desligamentos": 0,
            "planejamento_vb_dia": 10,
            "horario_inicio": "09:00",
            "horario_fim": "18:00",
            "uf": "MG",
            "cidade": "BELO HORIZONTE",
            "bairro": "CENTRO",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 20
        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertIn(r.status_code, (200, 201))
        body = r.json()["data"]
        self.assertEqual(body["qtd_equipes"], 2)
        self.assertEqual(body["total_campo"], 5)
        self.assertEqual(body["tipo_rota"], "MISTO")
        self.assertEqual(body["qtd_contratacoes"], 1)
        self.assertEqual(body["planejamento_vb_dia"], 10)
        self.assertEqual(body["horario_inicio"], "09:00")
        self.assertEqual(body["horario_fim"], "18:00")

    def test_checkin_exige_horario(self):
        payload = {
            "equipes": [{"atuacao": "DIGITAL", "pessoas": 2}],
            "horario_inicio": "18:00",
            "horario_fim": "08:00",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 20
        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 422)

    @patch("tickets.rota_views.consultar_agregado_por_bairro")
    def test_checkin_rotas_distintas_por_equipe(self, mock_dfv):
        mock_dfv.return_value = {
            "local": {"uf": "MG", "cidade": "BELO HORIZONTE", "bairro": "CENTRO"},
            "indicadores": {"hp_livre": 4, "hps": 8, "pct_hc": 10, "fachadas_viaveis": 2, "fachadas_total": 3},
            "credito": {},
            "perfil": {},
            "alertas": [],
            "meta": {},
        }
        payload = {
            "mesma_rota": False,
            "equipes": [
                {
                    "atuacao": "PAP",
                    "pessoas": 2,
                    "uf": "MG",
                    "cidade": "BELO HORIZONTE",
                    "bairro": "CENTRO",
                },
                {
                    "atuacao": "PAP",
                    "pessoas": 1,
                    "uf": "MG",
                    "cidade": "BELO HORIZONTE",
                    "bairro": "SAVASSI",
                },
            ],
            "planejamento_vb_dia": 8,
            "horario_inicio": "08:00",
            "horario_fim": "17:00",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 20
        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertIn(r.status_code, (200, 201), r.content)
        body = r.json()["data"]
        self.assertFalse(body["mesma_rota"])
        self.assertEqual(body["equipes"][0]["bairro"], "CENTRO")
        self.assertEqual(body["equipes"][1]["bairro"], "SAVASSI")
        self.assertEqual(body["local"]["bairro"], "CENTRO")

    @patch("tickets.rota_views.consultar_agregado_por_bairro")
    def test_checkin_equipe_divide_bairros(self, mock_dfv):
        mock_dfv.return_value = {
            "local": {"uf": "MG", "cidade": "BELO HORIZONTE", "bairro": "CENTRO"},
            "indicadores": {"hp_livre": 4, "hps": 8, "pct_hc": 10, "fachadas_viaveis": 2, "fachadas_total": 3},
            "credito": {},
            "perfil": {},
            "alertas": [],
            "meta": {},
        }
        payload = {
            "dividir_bairros": True,
            "uf": "MG",
            "cidade": "BELO HORIZONTE",
            "bairro": "CENTRO",
            "equipes": [
                {
                    "atuacao": "PAP",
                    "pessoas": 3,
                    "bairros": ["SAVASSI"],
                }
            ],
            "planejamento_vb_dia": 6,
            "horario_inicio": "08:00",
            "horario_fim": "17:00",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 20
        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertIn(r.status_code, (200, 201), r.content)
        body = r.json()["data"]
        self.assertTrue(body["dividir_bairros"])
        self.assertEqual(body["equipes"][0]["bairro"], "CENTRO")
        self.assertEqual(body["equipes"][0]["bairros"], ["SAVASSI"])

    def test_parceiro_nao_ve_agendas_da_equipe(self):
        r = self.client.get(reverse("rota_api_agendas"))
        self.assertEqual(r.status_code, 403)

    def test_portal_rota_render(self):
        with self.settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        ):
            r = self.client.get(reverse("rota_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rota da semana")
        self.assertContains(r, "rota-app")
        self.assertContains(r, "rota-week")
        self.assertContains(r, "rota_card.js")
        self.assertContains(r, "Quantas equipes vão a campo?")
        self.assertContains(r, "Onde vão atuar?")
        self.assertContains(r, "As equipes trabalham na mesma rota?")
        self.assertContains(r, "Essa equipe vai atuar em mais de um bairro?")


class DfvAgregadoBairroTests(TestCase):
    @patch("tickets.consultas.dfv_powerbi_service._consultar_bairro_com_fallback")
    def test_soma_hp_livre(self, mock_consulta):
        mock_consulta.return_value = (
            [
                {
                    "UF": "MG",
                    "MUNICIPIO": "BELO HORIZONTE",
                    "BAIRRO": "MARIA GORETTI",
                    "HP_LIVRE": 1,
                    "HP_TOT": 2,
                    "HC_TOT": 0,
                    "VIABILIDADE_ATUAL": "Viável",
                    "ds_faixa_aprovacao_credito_total": "Entre 50% e 70%",
                    "CLASSIFICACAO": "MEDIO",
                    "CODIGO_CDO": "CDOE-1",
                    "F_HP_NOVO": "1",
                },
                {
                    "UF": "MG",
                    "MUNICIPIO": "BELO HORIZONTE",
                    "BAIRRO": "MARIA GORETTI",
                    "HP_LIVRE": 6,
                    "HP_TOT": 6,
                    "HC_TOT": 0,
                    "VIABILIDADE_ATUAL": "Viável",
                    "ds_faixa_aprovacao_credito_total": "Entre 50% e 70%",
                    "CLASSIFICACAO": "MEDIO",
                    "CODIGO_CDO": "CDOE-1",
                    "F_HP_NOVO": "0",
                },
            ],
            ["HP_LIVRE", "HP_TOT"],
            False,
        )
        with override_settings(DFV_POWERBI_ENABLED=True):
            resumo = consultar_agregado_por_bairro("MG", "BELO HORIZONTE", "MARIA GORETTI")
        self.assertEqual(resumo["indicadores"]["hp_livre"], 7)
        self.assertEqual(resumo["indicadores"]["hps"], 8)
        self.assertEqual(resumo["credito"]["faixa_predominante"], "Entre 50% e 70%")
        self.assertEqual(resumo["perfil"]["classificacao_predominante"], "MEDIO")
        self.assertTrue(any(a["codigo"] == "hp_novo" for a in resumo["alertas"]))


STORAGES_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STORAGES_TESTE)
class RotaEquipeTests(TestCase):
    def setUp(self):
        from tickets.models import PerfilStaff

        User = get_user_model()
        self.spec = User.objects.create_user(
            username="spec-rota", password="senha-staff-ok1", first_name="Spec"
        )
        PerfilStaff.objects.create(user=self.spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        self.pdv = Parceiro.objects.create(
            codigo_pdv="ROTA3", nome="PDV Spec", especialista=self.spec
        )
        self.client.force_login(self.spec)

    def test_especialista_abre_rota_sem_contato(self):
        r = self.client.get(reverse("rota_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Agendas da semana")
        self.assertContains(r, "rota-week")

    def test_agendas_lista_pdv_da_carteira(self):
        r = self.client.get(reverse("rota_api_agendas"))
        self.assertEqual(r.status_code, 200)
        items = r.json()["data"]["items"]
        self.assertTrue(any(i["codigo_pdv"] == "ROTA3" for i in items))
        self.assertIn("totais", r.json()["data"])
        self.assertIn("especialistas", r.json()["data"])

    def test_checkin_pela_equipe(self):
        payload = {
            "pdv": self.pdv.id,
            "equipes": [{"atuacao": "DIGITAL", "pessoas": 4}],
            "planejamento_vb_dia": 10,
            "horario_inicio": "08:00",
            "horario_fim": "16:00",
        }
        if timezone.localdate().weekday() == 0:
            payload["vendas_planejadas_semana"] = 10
        r = self.client.post(
            reverse("rota_api_checkin"),
            data=payload,
            content_type="application/json",
        )
        self.assertIn(r.status_code, (200, 201))
        ck = CheckinRotaDiaria.objects.get(parceiro=self.pdv, data=timezone.localdate())
        self.assertEqual(ck.tipo_rota, "DIGITAL")
        self.assertEqual(ck.qtd_vendedores, 4)
        self.assertEqual(ck.planejamento_vb_dia, 10)
        self.assertEqual(ck.criado_por_user_id, self.spec.id)
        agendas = self.client.get(reverse("rota_api_agendas")).json()["data"]
        self.assertEqual(agendas["totais"]["dia"]["vb"], 10)
        self.assertEqual(agendas["especialistas"][0]["dia"]["vb"], 10)
