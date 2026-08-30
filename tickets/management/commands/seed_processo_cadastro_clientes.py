"""Seed do processo exemplo: cadastro de clientes Nova Fibra."""

from __future__ import annotations

import shutil
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from tickets.models import ProcessoAnexo, ProcessoRepositorio

PLANILHA_PADRAO = Path(
    r"C:\Users\rogge\Downloads\Documentos\Excel"
    r"\Formulario-Padrao-Cadastro-Cliente-Nova-Fibra-PF0610.xlsx"
)


class Command(BaseCommand):
    help = "Cria/atualiza o processo «Cadastro de clientes Nova Fibra»."

    def handle(self, *args, **options):
        processo, created = ProcessoRepositorio.objects.update_or_create(
            slug="cadastro-clientes-nova-fibra",
            defaults={
                "titulo": "Cadastro de clientes Nova Fibra",
                "categoria": ProcessoRepositorio.Categoria.CADASTRO,
                "resumo": (
                    "Quando o PAP exibe erro ao consultar crédito, cadastre o cliente "
                    "via planilha padrão e e-mail."
                ),
                "finalidade": (
                    "Cadastrar o cliente quando o sistema não encontra o cadastro e "
                    "bloqueia a consulta de crédito no PAP (tela de erro ao consultar crédito)."
                ),
                "quando_usar": (
                    "Ao tentar vender ou consultar crédito, o PAP mostra erro indicando "
                    "que o cliente não está cadastrado na base Nova Fibra."
                ),
                "encaminhamento": (
                    "Preencher a planilha padrão, anexar no e-mail e enviar para a fila "
                    "de cadastro Nova Fibra."
                ),
                "canal": ProcessoRepositorio.Canal.EMAIL,
                "email_destino": "cadastrodeclientesnovafibra@niointernet.com.br",
                "email_cc_especialista": True,
                "email_cc_extra": "rogerio.pacheco@niointernet.com.br",
                "requer_planilha": True,
                "instrucoes_planilha": (
                    "Preencha todos os campos obrigatórios da planilha PF0610 e anexe "
                    "no e-mail (não envie link)."
                ),
                "passos": (
                    "1) Baixe o formulário padrão abaixo.\n"
                    "2) Preencha com os dados do cliente (CPF, endereço, contato).\n"
                    "3) Anexe a planilha preenchida em um e-mail.\n"
                    "4) Envie para cadastrodeclientesnovafibra@niointernet.com.br.\n"
                    "5) Copie o e-mail do especialista NIO do seu PDV (CC automático no portal).\n"
                    "6) Aguarde retorno da fila de cadastro antes de tentar novamente no PAP."
                ),
                "tags": "cadastro, cliente, crédito, pap, nova fibra, planilha",
                "publico": True,
                "ordem": 10,
                "ativo": True,
            },
        )
        acao = "Criado" if created else "Atualizado"
        self.stdout.write(self.style.SUCCESS(f"{acao}: {processo.titulo}"))

        if PLANILHA_PADRAO.is_file():
            anexo, _ = ProcessoAnexo.objects.get_or_create(
                processo=processo,
                titulo="Formulário padrão cadastro PF0610",
                defaults={"tipo": ProcessoAnexo.Tipo.PLANILHA, "ordem": 1},
            )
            if not anexo.arquivo:
                with PLANILHA_PADRAO.open("rb") as fh:
                    anexo.arquivo.save(PLANILHA_PADRAO.name, File(fh), save=True)
                self.stdout.write("Planilha anexada ao processo.")
        else:
            self.stdout.write(
                self.style.WARNING(f"Planilha não encontrada: {PLANILHA_PADRAO}")
            )
