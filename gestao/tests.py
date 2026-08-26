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
            "gestao_whatsapp",
            "gestao_envios",
        ):
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 200, nome)


class SyncWAClientTests(TestCase):
    def test_normalizar_numero_br(self):
        from gestao.messaging.syncwa import normalizar_destino, numero_para_evolution

        self.assertEqual(normalizar_destino("31999999999"), "5531999999999@s.whatsapp.net")
        self.assertEqual(normalizar_destino("5531999999999"), "5531999999999@s.whatsapp.net")
        self.assertEqual(normalizar_destino("120363@g.us"), "120363@g.us")
        self.assertEqual(numero_para_evolution("5531999999999@s.whatsapp.net"), "5531999999999")
        self.assertEqual(numero_para_evolution("120363418335765186@g.us"), "120363418335765186@g.us")

    @override_settings(
        EVOLUTION_API_URL="https://evo.test",
        EVOLUTION_API_KEY="evo.key",
        EVOLUTION_INSTANCE_NAME="nio_gc_tickets",
        N8N_OUTBOUND_WEBHOOK_URL="",
        SYNCWA_MODO_TESTE=False,
    )
    def test_enviar_texto_registra_ok(self):
        from unittest.mock import MagicMock, patch

        from gestao.messaging.syncwa import enviar_texto

        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"key": {"id": "ml-1"}}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake) as post:
            result = enviar_texto("5531999999999", "oi")
        self.assertTrue(result.ok)
        self.assertEqual(result.message_log_id, "ml-1")
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["number"], "5531999999999")
        self.assertEqual(kwargs["headers"]["apikey"], "evo.key")
        self.assertIn("/message/sendText/nio_gc_tickets", post.call_args.args[0])

    @override_settings(
        EVOLUTION_API_URL="https://evo.test",
        EVOLUTION_API_KEY="evo.key",
        EVOLUTION_INSTANCE_NAME="nio_gc_tickets",
        N8N_OUTBOUND_WEBHOOK_URL="",
        SYNCWA_MODO_TESTE=True,
        SYNCWA_TEST_JID="5531888888888",
    )
    def test_modo_teste_redireciona(self):
        from unittest.mock import MagicMock, patch

        from gestao.messaging.syncwa import enviar_texto

        fake = MagicMock()
        fake.status_code = 200
        fake.json.return_value = {"key": {"id": "ml-2"}}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake) as post:
            result = enviar_texto("120363xxx@g.us", "teste")
        self.assertTrue(result.ok)
        self.assertEqual(post.call_args.kwargs["json"]["number"], "5531888888888")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
    EVOLUTION_API_URL="https://evo.test",
    EVOLUTION_API_KEY="evo.key",
    EVOLUTION_INSTANCE_NAME="nio_gc_tickets",
    N8N_OUTBOUND_WEBHOOK_URL="",
)
class WhatsAppPareamentoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser("gwa", "gwa@x.com", "x")
        PerfilStaff.objects.create(user=self.gestor, papel=PerfilStaff.Papel.GESTOR)
        self.client.force_login(self.gestor)

    def test_pagina_gestor(self):
        r = self.client.get(reverse("gestao_whatsapp"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gerar QR Code")
        self.assertContains(r, "nio_gc_tickets")

    def test_especialista_nao_acessa(self):
        User = get_user_model()
        spec = User.objects.create_user("specwa", "sw@x.com", "x", is_staff=True)
        PerfilStaff.objects.create(user=spec, papel=PerfilStaff.Papel.ESPECIALISTA)
        self.client.force_login(spec)
        r = self.client.get(reverse("gestao_whatsapp"))
        self.assertEqual(r.status_code, 404)

    @override_settings(EVOLUTION_API_URL="", EVOLUTION_API_KEY="")
    def test_status_sem_config(self):
        r = self.client.get(reverse("gestao_whatsapp_status"))
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["state"], "unconfigured")

    def test_status_conectado(self):
        from unittest.mock import patch

        with patch(
            "gestao.views_whatsapp.EvolutionConnectionService.get_status",
            return_value={
                "instanceName": "nio_gc_tickets",
                "state": "open",
                "connected": True,
                "n8nConfigured": False,
                "evolutionConfigured": True,
            },
        ):
            r = self.client.get(reverse("gestao_whatsapp_status"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["connected"])
        self.assertEqual(r.json()["state"], "open")

    def test_qrcode(self):
        from unittest.mock import patch

        with patch(
            "gestao.views_whatsapp.EvolutionConnectionService.get_qrcode",
            return_value={
                "instanceName": "nio_gc_tickets",
                "base64": "data:image/png;base64,AAA",
                "count": 1,
            },
        ):
            r = self.client.get(reverse("gestao_whatsapp_qrcode"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["base64"].startswith("data:image/png;base64,"))

    def test_desconectar(self):
        from unittest.mock import patch

        with patch(
            "gestao.views_whatsapp.EvolutionConnectionService.disconnect",
            return_value={
                "success": True,
                "instanceName": "nio_gc_tickets",
                "message": "Instância desconectada com sucesso.",
                "status": {"state": "close", "connected": False},
            },
        ):
            r = self.client.post(reverse("gestao_whatsapp_disconnect"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
    EVOLUTION_API_URL="https://evo.test",
    EVOLUTION_API_KEY="evo.key",
    EVOLUTION_INSTANCE_NAME="nio_gc_tickets",
    N8N_OUTBOUND_WEBHOOK_URL="",
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
        fake.json.return_value = {"key": {"id": "ml-9"}}
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
        fake.json.return_value = {"key": {"id": "ml-t"}}
        with patch("gestao.messaging.syncwa.requests.post", return_value=fake):
            with override_settings(SYNCWA_TEST_JID="5531777777777"):
                r = self.client.post(reverse("gestao_envios"), {"action": "teste"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(EnvioWhatsApp.objects.filter(tipo=EnvioWhatsApp.Tipo.TESTE).exists())


class ComissionamentoTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="31", nome="INOVA MG")
        from gestao.models import Destinatario

        Destinatario.objects.create(
            parceiro=self.pdv,
            nome="Grupo Comis",
            jid="120363abc@g.us",
            tipo=Destinatario.TipoDestino.GRUPO,
            envio_comissionamento=True,
            razoes_sociais_comissionamento="LUISA SERVICOS DE TELEFONIA MOVEL LTDA",
        )

    def _ciclo_xlsx(self):
        wb = Workbook()
        ws_p = wb.active
        ws_p.title = "PEDIDO"
        ws_p.append(
            [
                "DOCUMENTO DE COMPRAS",
                "ITEM",
                "VALOR",
                "FORNECEDOR",
                "RAZAO SOCIAL",
                "CNPJ",
                "CANAL",
                "CENTRO",
                "CICLO",
            ]
        )
        ws_p.append(
            [
                "450001",
                "10",
                "100,50",
                "HANA1",
                "LUISA SERVICOS DE TELEFONIA MOVEL LTDA",
                "123",
                "VAREJO",
                "MG",
                "202608",
            ]
        )
        ws_p.append(
            [
                "450002",
                "20",
                "50,00",
                "HANA2",
                "OUTRA EMPRESA LTDA",
                "999",
                "VAREJO",
                "MG",
                "202608",
            ]
        )
        ws_l = wb.create_sheet("LINHA_A_LINHA")
        ws_l.append(["RAZAO SOCIAL", "SUB_EVENTO", "COMISSAO"])
        ws_l.append(["LUISA SERVICOS DE TELEFONIA MOVEL LTDA", "ATIVACAO", "100,50"])
        ws_l.append(["OUTRA EMPRESA LTDA", "ATIVACAO", "50,00"])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "ciclo.xlsx"
        return buf

    def test_processar_filtra_por_razao(self):
        from gestao.models import LoteImportacao, RelatorioComissionamento
        from gestao.pipelines.comissionamento import processar_comissionamento

        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.COMISSIONAMENTO,
            arquivo_nome="ciclo.xlsx",
            ok=True,
        )
        resumo = processar_comissionamento(self._ciclo_xlsx(), "ciclo.xlsx", lote)
        self.assertEqual(resumo["pdvs"], 1)
        rel = RelatorioComissionamento.objects.get()
        self.assertEqual(rel.parceiro_id, self.pdv.id)
        self.assertEqual(rel.qtd_pedido, 1)
        self.assertEqual(rel.qtd_linha, 1)
        self.assertTrue(rel.arquivo)
        self.assertIn("Comissionamento", rel.mensagem)

    def test_exige_razoes_configuradas(self):
        from gestao.models import Destinatario, LoteImportacao
        from gestao.pipelines.comissionamento import processar_comissionamento

        Destinatario.objects.all().delete()
        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.COMISSIONAMENTO,
            arquivo_nome="ciclo.xlsx",
            ok=True,
        )
        with self.assertRaises(ValueError):
            processar_comissionamento(self._ciclo_xlsx(), "ciclo.xlsx", lote)


class TarefasTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="31", nome="INOVA MG")

    def _xlsx_abertas(self, data_agendamento):
        from datetime import date as d

        if isinstance(data_agendamento, d):
            data_agendamento = data_agendamento.isoformat()
        wb = Workbook()
        ws = wb.active
        ws.append(
            [
                "sg_uf",
                "nm_municipio",
                "INDICADOR",
                "nm_pdv_rel",
                "DT_AGENDAMENTO",
                "nr_ordem",
            ]
        )
        ws.append(["MG", "BH", "TAREFAS ABERTAS", "INOVA MG", data_agendamento, "1"])
        ws.append(["MG", "Uberlândia", "TAREFAS ABERTAS", "INOVA MG", data_agendamento, "2"])
        ws.append(["SP", "SP", "TAREFAS ABERTAS", "OUTRO", data_agendamento, "3"])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "tarefas.xlsx"
        return buf

    def test_abertas_por_pdv(self):
        from gestao.models import LoteImportacao, RelatorioTarefa
        from gestao.periodo import hoje
        from gestao.pipelines.tarefas import processar_tarefas

        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.TAREFAS, arquivo_nome="t.xlsx", ok=True
        )
        resumo = processar_tarefas(self._xlsx_abertas(hoje()), "t.xlsx", lote)
        self.assertEqual(resumo["modo"], "abertas")
        self.assertEqual(resumo["relatorios"], 1)
        rel = RelatorioTarefa.objects.get()
        self.assertEqual(rel.parceiro_id, self.pdv.id)
        self.assertEqual(rel.total, 2)
        self.assertIn("Resumo de Tarefas", rel.mensagem)

    def test_fechadas_consolidado(self):
        from gestao.models import LoteImportacao, RelatorioTarefa
        from gestao.periodo import hoje
        from gestao.pipelines.tarefas import processar_tarefas

        wb = Workbook()
        ws = wb.active
        ws.append(["sg_uf", "nm_municipio", "INDICADOR", "dt_fim_execucao_real"])
        ws.append(["MG", "BH", "TAREFAS FECHADAS", hoje().isoformat()])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "fechadas.xlsx"
        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.TAREFAS, arquivo_nome="f.xlsx", ok=True
        )
        resumo = processar_tarefas(buf, "f.xlsx", lote)
        self.assertEqual(resumo["modo"], "fechadas")
        rel = RelatorioTarefa.objects.get()
        self.assertIsNone(rel.parceiro_id)
        self.assertEqual(rel.total, 1)


class VendaIndevidaTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="31", nome="INOVA MG")

    def _xlsx_vi(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "BASE_VI"
        ws.append(["ANOMES_ABERTURA", "MOTIVO_CRV", "SUBMOTIVO_CRV", "REDE", "NUMERO_PEDIDO"])
        ws.append(["202601", "INDEVIDA", "DOC", "INOVA MG", "P1"])
        ws.append(["202602", "ERRADA", "END", "INOVA MG", "P2"])
        ws.append(["202601", "INDEVIDA", "DOC", "OUTRO PDV X", "P3"])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "vi.xlsx"
        return buf

    def test_processar_vi(self):
        from gestao.models import LoteImportacao, RelatorioVendaIndevida
        from gestao.pipelines.venda_indevida import processar_venda_indevida

        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.VENDA_INDEVIDA, arquivo_nome="vi.xlsx", ok=True
        )
        resumo = processar_venda_indevida(self._xlsx_vi(), "vi.xlsx", lote)
        self.assertEqual(resumo["total_linhas"], 3)
        self.assertEqual(resumo["pdvs"], 2)
        self.assertTrue(RelatorioVendaIndevida.objects.filter(consolidado=True).exists())
        por_pdv = RelatorioVendaIndevida.objects.filter(parceiro=self.pdv, consolidado=False)
        self.assertEqual(por_pdv.count(), 1)
        self.assertEqual(por_pdv.get().total, 2)
        self.assertIn("VENDA INDEVIDA", por_pdv.get().mensagem)


class RecompraTests(TestCase):
    def setUp(self):
        self.pdv = Parceiro.objects.create(codigo_pdv="31", nome="INOVA MG")

    def _xlsx_recompra(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "BASE"
        ws.append(["ds_anomes", "resultado", "REDE", "nr_ordem"])
        ws.append(["202601", "RECOMPRA", "INOVA MG", "1"])
        ws.append(["202602", "SEM RECOMPRA", "INOVA MG", "2"])
        ws.append(["202601", "RECOMPRA", "OUTRO PDV", "3"])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "recompra.xlsx"
        return buf

    def test_processar_recompra(self):
        from gestao.models import LoteImportacao, RelatorioRecompra
        from gestao.pipelines.recompra import processar_recompra

        lote = LoteImportacao.objects.create(
            tipo=LoteImportacao.Tipo.RECOMPRA, arquivo_nome="r.xlsx", ok=True
        )
        resumo = processar_recompra(self._xlsx_recompra(), "r.xlsx", lote)
        self.assertEqual(resumo["total_linhas"], 3)
        self.assertEqual(resumo["pdvs"], 2)
        self.assertTrue(RelatorioRecompra.objects.filter(consolidado=True).exists())
        por_pdv = RelatorioRecompra.objects.filter(parceiro=self.pdv, consolidado=False)
        self.assertEqual(por_pdv.count(), 1)
        self.assertEqual(por_pdv.get().total, 2)
        self.assertIn("RECOMPRA", por_pdv.get().mensagem)
