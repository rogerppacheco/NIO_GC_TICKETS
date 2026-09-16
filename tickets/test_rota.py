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
from tickets.rota_services import classificar_alerta, meta_semana_parceiro, salvar_checkin


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
        )
        self.assertEqual(checkin.tipo_rota, "DIGITAL")
        self.assertEqual(checkin.qtd_vendedores, 3)


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
        self.assertContains(r, "Rota do dia")
        self.assertContains(r, "rota-app")
        self.assertContains(r, "rota_card.js")


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
