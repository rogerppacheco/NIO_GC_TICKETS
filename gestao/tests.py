from datetime import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from tickets.models import Parceiro, PerfilStaff

from gestao.models import (
    CadastroTerceiro,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    RelatorioFPD,
    VendaOSAB,
)
from gestao.parceiros import resolver_parceiro_id
from gestao.periodo import periodo_ativo, salvar_periodo
from gestao.pipelines.churn import processar_churn
from gestao.pipelines.fpd import processar_fpd
from gestao.pipelines.osab import processar_osab
from gestao.terceiros import importar_sysmap
from gestao.models import LoteImportacao


def _xlsx(linhas, colunas):
    wb = Workbook()
    ws = wb.active
    ws.append(colunas)
    for linha in linhas:
        ws.append(linha)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "base.xlsx"
    return buf


class ParceiroMatchTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1068281", nome="INOVA MG")

    def test_alias_razao_social(self):
        self.assertEqual(
            resolver_parceiro_id("LUISA SERVICOS DE TELEFONIA MOVEL LTDA"),
            self.pdv.id,
        )

    def test_nome_exato(self):
        self.assertEqual(resolver_parceiro_id("INOVA MG"), self.pdv.id)


class SysmapImportTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1", nome="INOVA MG")

    def test_upsert_por_chave(self):
        arquivo = _xlsx(
            [
                [
                    "LUISA SERVICOS DE TELEFONIA MOVEL",
                    "ANA",
                    "123",
                    "a@x.com",
                    "TT1",
                    "CLT",
                    "VENDEDOR",
                    "Ativo",
                    "Ativo",
                    "Alocado",
                    "01/01/2025",
                    "",
                    "",
                ]
            ],
            [
                "Razão Social",
                "Terceiro",
                "CPF",
                "Email",
                "Chave de Acesso",
                "Vínculo",
                "Cargo/Função",
                "Situação Terceiro Empresa",
                "Situação Funcional",
                "Situação Terceiro Contrato",
                "Data Alocação",
                "Data Desalocação",
                "Data Inativação",
            ],
        )
        resumo = importar_sysmap(arquivo, "terceiros.xlsx")
        self.assertEqual(resumo["inseridos"], 1)
        t = CadastroTerceiro.objects.get(chave_acesso="TT1")
        self.assertTrue(t.ativo)
        self.assertEqual(t.parceiro_id, self.pdv.id)
        self.assertEqual(t.cargo_funcao, "VENDEDOR")


class OsabCapilaridadeTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1", nome="RECORD")
        CadastroTerceiro.objects.create(
            chave_acesso="TT99",
            nome_terceiro="JOAO",
            razao_social="RECORD",
            parceiro=self.pdv,
            cargo_funcao="VENDEDOR",
            situacao_empresa="Ativo",
            situacao_funcional="Ativo",
            situacao_contrato="Alocado",
            ativo=True,
        )

    def test_importa_venda_e_gera_capilaridade(self):
        hoje = timezone.localdate()
        abertura = datetime(hoje.year, hoje.month, 1, 10, 0)
        arquivo = _xlsx(
            [
                [
                    "P1",
                    abertura,
                    "TT99",
                    "JOAO",
                    "RECORD",
                    abertura,
                    abertura,
                    "Concluído",
                    "500 MEGA",
                ]
            ],
            [
                "PEDIDO",
                "DT_REF",
                "MATRICULA_VENDEDOR",
                "NOME_VENDEDOR",
                "DESCRICAO",
                "DATA_ABERTURA",
                "DATA_FECHAMENTO",
                "SITUACAO",
                "VELOCIDADE",
            ],
        )
        resumo = processar_osab(arquivo, "OSAB.xlsx", hoje.year, hoje.month)
        self.assertEqual(resumo["vendas"]["inseridos"], 1)
        self.assertEqual(VendaOSAB.objects.get(pedido="P1").parceiro_id, self.pdv.id)
        self.assertGreaterEqual(resumo["capilaridade"]["linhas"], 1)
        self.assertTrue(HistoricoOSAB.objects.filter(parceiro=self.pdv).exists())


class FpdChurnTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="1", nome="APOLO")
        GrossMensal.objects.create(
            parceiro=self.pdv,
            anomes=int(timezone.localdate().strftime("%Y%m")),
            gross=10,
        )

    def test_fpd(self):
        mes = timezone.localdate().strftime("%m/%Y")
        arquivo = _xlsx(
            [["APOLO", mes, "Aberta", "15 a 30 Dias", "FPD"]],
            ["APELIDO", "REF_VENCTO", "SITUACAO_FATURA_MENSAL", "FAIXA", "INDICADOR"],
        )
        lote = LoteImportacao.objects.create(tipo="fpd", arquivo_nome="f.xlsx", ok=True)
        resumo = processar_fpd(arquivo, "f.xlsx", lote)
        self.assertEqual(resumo["pdvs"], 1)
        rel = RelatorioFPD.objects.get(parceiro=self.pdv)
        self.assertEqual(rel.total_abertas, 1)
        self.assertIn("Relatório FPD", rel.mensagem)

    def test_churn(self):
        anomes = int(timezone.localdate().strftime("%Y%m"))
        arquivo = _xlsx(
            [["APOLO", anomes, "VOL", 0, "residencial", "preço"]],
            ["DESC_APELIDO", "ANOMES_GROSS", "TP_RETIRADA", "FLG_MEI", "NM_SEG", "DS_MOTIVO_RETIRADA"],
        )
        resumo = processar_churn(arquivo, "c.xlsx")
        self.assertEqual(resumo["pdvs"], 1)
        h = HistoricoChurn.objects.get(parceiro=self.pdv, anomes_gross=anomes)
        self.assertEqual(h.churn, 1)
        self.assertEqual(h.gross, 10)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class GestaoViewsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gestor", "g@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)

    def test_hub_exige_login(self):
        r = self.client.get(reverse("gestao_hub"))
        self.assertEqual(r.status_code, 302)

    def test_hub_gestor(self):
        self.client.force_login(self.gestor)
        r = self.client.get(reverse("gestao_hub"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gestão de bases")

    def test_salvar_periodo(self):
        self.client.force_login(self.gestor)
        r = self.client.post(reverse("gestao_hub"), {"action": "periodo", "ano": 2026, "mes": 8})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(periodo_ativo(), (2026, 8))

    def test_paginas_gestao(self):
        self.client.force_login(self.gestor)
        for nome in (
            "gestao_sysmap",
            "gestao_osab",
            "gestao_capilaridade",
            "gestao_fpd",
            "gestao_churn",
            "gestao_configs",
            "gestao_destinatarios",
            "gestao_envios",
        ):
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 200, nome)


class SyncWAClientTests(TestCase):
    def test_normalizar_numero_br(self):
        from gestao.messaging.syncwa import normalizar_destino

        self.assertEqual(normalizar_destino("31999999999"), "5531999999999@s.whatsapp.net")
        self.assertEqual(normalizar_destino("5531999999999"), "5531999999999@s.whatsapp.net")
        self.assertEqual(normalizar_destino("120363@g.us"), "120363@g.us")

    @override_settings(
        SYNCWA_BASE_URL="https://syncwa.test",
        SYNCWA_API_KEY="syncwa.key",
        SYNCWA_MODO_TESTE=False,
    )
    def test_enviar_texto_registra_ok(self):
        from unittest.mock import MagicMock, patch

        from gestao.messaging.syncwa import enviar_texto

        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"messageLogId": "ml-1", "status": "QUEUED"}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake) as post:
            result = enviar_texto("5531999999999", "oi")
        self.assertTrue(result.ok)
        self.assertEqual(result.message_log_id, "ml-1")
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["to"], "5531999999999@s.whatsapp.net")
        self.assertEqual(kwargs["headers"]["x-api-key"], "syncwa.key")

    @override_settings(
        SYNCWA_BASE_URL="https://syncwa.test",
        SYNCWA_API_KEY="syncwa.key",
        SYNCWA_MODO_TESTE=True,
        SYNCWA_TEST_JID="5531888888888",
    )
    def test_modo_teste_redireciona(self):
        from unittest.mock import MagicMock, patch

        from gestao.messaging.syncwa import enviar_texto

        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"messageLogId": "ml-2", "status": "QUEUED"}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake) as post:
            result = enviar_texto("120363xxx@g.us", "teste")
        self.assertTrue(result.ok)
        self.assertEqual(post.call_args.kwargs["json"]["to"], "5531888888888@s.whatsapp.net")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
    SYNCWA_BASE_URL="https://syncwa.test",
    SYNCWA_API_KEY="syncwa.key",
    SYNCWA_MODO_TESTE=False,
)
class DestinatarioEnvioTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("g2", "g2@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.pdv = Parceiro.objects.create(codigo_pdv="99", nome="INOVA TESTE")
        self.client.force_login(self.gestor)

    def test_cria_destinatario(self):
        from gestao.models import Destinatario

        r = self.client.post(
            reverse("gestao_destinatarios"),
            {
                "parceiro": self.pdv.id,
                "nome": "Grupo Inova",
                "jid": "120363abc@g.us",
                "tipo": Destinatario.TipoDestino.GRUPO,
                "prioridade": 10,
                "ativo": "on",
                "envio_capilaridade": "on",
                "envio_osab": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        dest = Destinatario.objects.get(nome="Grupo Inova")
        self.assertTrue(dest.envio_capilaridade)
        self.assertFalse(dest.envio_fpd)

    def test_enviar_capilaridade_registra_log(self):
        from unittest.mock import MagicMock, patch

        from gestao.models import Destinatario, EnvioWhatsApp

        Destinatario.objects.create(
            parceiro=self.pdv,
            nome="Contato",
            jid="5531999999999",
            envio_capilaridade=True,
        )
        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"messageLogId": "ml-9", "status": "QUEUED"}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake):
            r = self.client.post(
                reverse("gestao_capilaridade"),
                {"action": "enviar_pdv", "parceiro": self.pdv.id},
            )
        self.assertEqual(r.status_code, 302)
        log = EnvioWhatsApp.objects.get()
        self.assertEqual(log.status, EnvioWhatsApp.Status.ENVIADO)
        self.assertEqual(log.tipo, EnvioWhatsApp.Tipo.CAPILARIDADE)
        self.assertEqual(log.syncwa_message_id, "ml-9")

    def test_enviar_teste_via_envios(self):
        from unittest.mock import MagicMock, patch

        from gestao.models import EnvioWhatsApp

        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"messageLogId": "ml-t", "status": "QUEUED"}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake):
            with override_settings(SYNCWA_TEST_JID="5531777777777"):
                r = self.client.post(reverse("gestao_envios"), {"action": "teste"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(EnvioWhatsApp.objects.filter(tipo=EnvioWhatsApp.Tipo.TESTE).exists())
