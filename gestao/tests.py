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
        ):
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 200, nome)
