"""
Sugere e preenche razão social dos parceiros a partir do Sysmap, destinatários e aliases.

Uso:
  python manage.py preencher_razao_social
  python manage.py preencher_razao_social --aplicar
  python manage.py preencher_razao_social --sysmap "C:\\path\\Relatório.xls" --aplicar
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from gestao.models import Destinatario
from gestao.parceiros import RAZAO_ALIASES_PDV, normalizar_pdv, normalizar_razao, resolver_parceiro_id
from gestao.pipelines.comissionamento import extrair_razoes_sociais
from gestao.terceiros import (
    _consolidar,
    _flatten_columns,
    _mapear_colunas,
    _parece_cabecalho,
)
from gestao.excel import ler_planilha
from tickets.models import Parceiro

# Nome comercial → razão Sym quando o match automático não alcança.
RAZOES_MANUAIS_CONHECIDAS = {
    "K&K": "KEK TELECOM INTERMEDIACAO LTDA",
}


def _razoes_sysmap(caminho: Path) -> list[str]:
    df = ler_planilha(caminho, str(caminho))
    df = _flatten_columns(df)
    if len(df) > 0 and _parece_cabecalho(df.iloc[0]):
        df = df.iloc[1:].reset_index(drop=True)
    mapa = _mapear_colunas(df)
    df, _ = _consolidar(df, mapa)
    col = mapa["razao_social"]
    contagem = Counter(str(v).strip() for v in df[col] if str(v).strip())
    return [razao for razao, _ in contagem.most_common()]


def _alias_razao_para_pdv() -> dict[str, str]:
    """nome_pdv_norm → razao_norm (alias conhecido)."""
    invertido: dict[str, str] = {}
    for razao_alias, pdv_nome in RAZAO_ALIASES_PDV.items():
        invertido[normalizar_pdv(pdv_nome)] = razao_alias
    return invertido


class Command(BaseCommand):
    help = "Sugere/preenche razão social dos parceiros (Sysmap, destinatários, aliases)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sysmap",
            type=str,
            default="",
            help="Caminho do Relatório Executivo de Terceiros (.xls/.xlsx).",
        )
        parser.add_argument(
            "--aplicar",
            action="store_true",
            help="Grava no banco (sem isso, só mostra o relatório).",
        )

    def handle(self, *args, **options):
        caminho = (options["sysmap"] or "").strip()
        aplicar = options["aplicar"]
        razoes_sysmap: list[str] = []
        if caminho:
            path = Path(caminho)
            if not path.exists():
                self.stderr.write(self.style.ERROR(f"Arquivo não encontrado: {caminho}"))
                return
            razoes_sysmap = _razoes_sysmap(path)
            self.stdout.write(f"Sysmap: {len(razoes_sysmap)} razões distintas em {path.name}")

        parceiros = list(Parceiro.objects.order_by("nome"))
        indice = [(p.id, p.nome, normalizar_pdv(p.nome), normalizar_razao(p.razao_social)) for p in parceiros]
        alias_pdv = _alias_razao_para_pdv()

        destino_por_razao: dict[int, list[tuple[str, str]]] = defaultdict(list)

        # Destinatários (legado comissionamento)
        for dest in Destinatario.objects.exclude(razoes_sociais_comissionamento="").select_related(
            "parceiro"
        ):
            for razao in extrair_razoes_sociais(dest.razoes_sociais_comissionamento):
                destino_por_razao[dest.parceiro_id].append(("destinatario", razao))

        # Sysmap: razão → parceiro via resolver
        for razao in razoes_sysmap:
            pid = resolver_parceiro_id(razao, indice)
            if pid:
                destino_por_razao[pid].append(("sysmap_resolver", razao))

        # Sysmap: match único por nome PDV contido na razão
        for p in parceiros:
            pn = normalizar_pdv(p.nome)
            if len(pn) < 4:
                continue
            candidatas = [
                r
                for r in razoes_sysmap
                if pn in normalizar_razao(r) or normalizar_razao(r).startswith(pn + " ")
            ]
            if len(candidatas) == 1:
                destino_por_razao[p.id].append(("sysmap_nome", candidatas[0]))

        preenchidos = []
        pendentes = []
        ambiguos = []
        ja_ok = []

        with transaction.atomic():
            for p in parceiros:
                if (p.razao_social or "").strip():
                    ja_ok.append(p)
                    continue

                pn = normalizar_pdv(p.nome)
                sugestoes: list[tuple[str, str]] = []

                razao_manual = RAZOES_MANUAIS_CONHECIDAS.get(p.nome.strip())
                if razao_manual:
                    sugestoes.append(("conhecida", razao_manual))

                if pn in alias_pdv:
                    sugestoes.append(("alias", alias_pdv[pn] + " LTDA"))

                sugestoes.extend(destino_por_razao.get(p.id, []))

                # Dedupe por razão normalizada, mantendo fonte
                vistos: set[str] = set()
                unicas: list[tuple[str, str]] = []
                for fonte, razao in sugestoes:
                    chave = normalizar_razao(razao)
                    if not chave or chave in vistos:
                        continue
                    vistos.add(chave)
                    unicas.append((fonte, razao))

                if len(unicas) == 1:
                    fonte, razao = unicas[0]
                    if aplicar:
                        p.razao_social = razao[:200]
                        p.save(update_fields=["razao_social", "atualizado_em"])
                    preenchidos.append((p, fonte, razao))
                elif len(unicas) > 1:
                    ambiguos.append((p, unicas))
                else:
                    pendentes.append(p)

            if not aplicar:
                transaction.set_rollback(True)

        self.stdout.write("")
        if ja_ok:
            self.stdout.write(self.style.SUCCESS(f"Já cadastrados ({len(ja_ok)}):"))
            for p in ja_ok:
                self.stdout.write(f"  OK {p.nome} -> {p.razao_social}")

        if preenchidos:
            tag = "Preenchidos" if aplicar else "Seriam preenchidos (use --aplicar)"
            self.stdout.write(self.style.SUCCESS(f"\n{tag} ({len(preenchidos)}):"))
            for p, fonte, razao in preenchidos:
                self.stdout.write(f"  + {p.nome} -> {razao}  [{fonte}]")

        if ambiguos:
            self.stdout.write(self.style.WARNING(f"\nAmbíguos — preencher manualmente ({len(ambiguos)}):"))
            for p, opcoes in ambiguos:
                self.stdout.write(f"  ? {p.nome}")
                for fonte, razao in opcoes:
                    self.stdout.write(f"      - {razao}  [{fonte}]")

        if pendentes:
            self.stdout.write(self.style.ERROR(f"\nSem sugestão — você precisa preencher ({len(pendentes)}):"))
            for p in pendentes:
                self.stdout.write(f"  - {p.nome} (codigo {p.codigo_pdv})")

        if not aplicar and (preenchidos or ambiguos or pendentes):
            self.stdout.write("\nDry-run. Para gravar: python manage.py preencher_razao_social --aplicar ...")
