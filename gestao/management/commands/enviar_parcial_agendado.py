from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestao.messaging.envio import (
    enviar_parcial_carteira,
    enviar_parcial_gerencia,
    enviar_parcial_grupos,
)
from gestao.models import Destinatario, LoteImportacao
from gestao.pipelines.parcial_vendas import HORARIOS_PARCIAL, turno_parcial
from tickets.acesso import parceiros_gestao
from tickets.models import Parceiro, PerfilStaff


class Command(BaseCommand):
    help = (
        "Envia parcial de vendas nos turnos 12h, 15h e 18h usando a última base importada "
        "de cada gestor. Agende no cron/Task Scheduler."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--modo",
            choices=("gerencia", "carteira", "grupos", "todos"),
            default="todos",
            help="Tipo de envio (default: todos).",
        )
        parser.add_argument(
            "--turno",
            type=int,
            choices=HORARIOS_PARCIAL,
            help="Força o turno (12, 15 ou 18). Default: turno atual.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria enviado sem disparar WhatsApp.",
        )

    def handle(self, *args, **options):
        hora = options.get("turno")
        if hora is None:
            hora, rotulo = turno_parcial()
        else:
            from gestao.pipelines.parcial_vendas import ROTULOS_TURNO

            rotulo = ROTULOS_TURNO[hora]
        if timezone.localtime().hour != hora and not options.get("turno"):
            self.stdout.write(
                self.style.WARNING(
                    f"Fora do turno {rotulo} (hora local {timezone.localtime():%H:%M}). "
                    "Use --turno para forçar."
                )
            )
            return

        gestores = PerfilStaff.objects.filter(papel=PerfilStaff.Papel.GESTOR).select_related("user")
        for perfil in gestores:
            user = perfil.user
            lote = (
                LoteImportacao.objects.filter(
                    tipo=LoteImportacao.Tipo.PARCIAL,
                    ok=True,
                    criado_por=user,
                    criado_em__date=timezone.localdate(),
                )
                .order_by("-criado_em")
                .first()
            )
            if not lote or not lote.resumo:
                self.stdout.write(f"— {user.username}: sem base importada hoje.")
                continue
            dados = lote.resumo
            if dados.get("turno") != hora:
                self.stdout.write(
                    f"— {user.username}: base do turno {dados.get('rotulo_turno')} "
                    f"(esperado {rotulo})."
                )
                continue
            visiveis = list(parceiros_gestao(user, "todos"))
            modo = options["modo"]
            if options["dry_run"]:
                self.stdout.write(
                    f"DRY {user.username}: {dados.get('qtd_pdvs')} PDV(s) · modo={modo}"
                )
                continue
            if modo in ("gerencia", "todos"):
                dest = (
                    Destinatario.objects.filter(
                        ativo=True,
                        ranking_consolidado=True,
                        envio_resultados=True,
                        tipo=Destinatario.TipoDestino.GRUPO,
                    )
                    .order_by("prioridade")
                    .first()
                )
                if dest:
                    res = enviar_parcial_gerencia(
                        dados,
                        user,
                        destinatario_id=dest.pk,
                        parceiros=visiveis,
                    )
                    self.stdout.write(f"Gerência {user.username}: {res.enviados} ok / {res.erros} erro")
            if modo in ("carteira", "todos"):
                res = enviar_parcial_carteira(visiveis, user, dados)
                self.stdout.write(f"Carteira {user.username}: {res.enviados} ok / {res.erros} erro")
            if modo in ("grupos", "todos"):
                res = enviar_parcial_grupos(visiveis, user, dados)
                self.stdout.write(f"Grupos {user.username}: {res.enviados} ok / {res.erros} erro")
