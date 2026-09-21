from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from tickets.models import Parceiro, RegistroAcesso
from tickets.seguranca import (
    garantir_conta_parceiro,
    gerar_senha_temporaria,
    invalidar_sessoes,
    registrar_evento,
)


class Command(BaseCommand):
    help = (
        "Gera senha temporária em lote para os PDVs de um especialista. "
        "Imprime código, nome e senha uma vez (não gravamos em claro)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--especialista",
            required=True,
            help="Nome, usuário ou trecho (ex.: Caio).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só lista os PDVs, sem gravar.",
        )
        parser.add_argument(
            "--reset-existentes",
            action="store_true",
            help="Também reseta PDVs que já têm login.",
        )
        parser.add_argument(
            "--incluir-inativos",
            action="store_true",
            help="Inclui PDVs inativos.",
        )

    def handle(self, *args, **opts):
        termo = (opts["especialista"] or "").strip()
        if not termo:
            raise CommandError("Informe --especialista.")
        User = get_user_model()
        specs = (
            User.objects.filter(perfil_staff__isnull=False)
            .filter(
                Q(first_name__icontains=termo)
                | Q(last_name__icontains=termo)
                | Q(username__icontains=termo)
            )
            .distinct()
        )
        if specs.count() != 1:
            nomes = ", ".join(
                f"{u.get_full_name() or u.username} ({u.username})" for u in specs[:8]
            ) or "ninguém"
            raise CommandError(
                f"Especialista “{termo}” não é único ({specs.count()}): {nomes}."
            )
        spec = specs.get()
        qs = Parceiro.objects.filter(especialista=spec).order_by("codigo_pdv")
        if not opts["incluir_inativos"]:
            qs = qs.filter(ativo=True)

        self.stdout.write(
            f"Especialista: {spec.get_full_name() or spec.username} ({spec.username}). "
            f"PDVs no recorte: {qs.count()}."
        )
        geradas = []
        pulados = 0
        erros = 0
        for parceiro in qs:
            ja_tem = bool(parceiro.usuario_id)
            if ja_tem and not opts["reset_existentes"]:
                pulados += 1
                self.stdout.write(
                    f"  pulado (já tem login): {parceiro.codigo_pdv} — {parceiro.nome}"
                )
                continue
            acao = "reset" if ja_tem else "nova"
            if opts["dry_run"]:
                geradas.append((parceiro.codigo_pdv, parceiro.nome, "(dry-run)", acao))
                continue
            senha = gerar_senha_temporaria()
            try:
                with transaction.atomic():
                    user, senha_clara, _criado = garantir_conta_parceiro(
                        parceiro, senha=senha, must_change=True
                    )
                invalidar_sessoes(user)
                registrar_evento(
                    RegistroAcesso.Tipo.RESET,
                    ator=None,
                    alvo=user,
                    detalhe=f"lote {acao} PDV {parceiro.codigo_pdv} · {spec.username}",
                )
                geradas.append(
                    (
                        parceiro.codigo_pdv,
                        parceiro.nome,
                        senha_clara or senha,
                        acao,
                    )
                )
            except ValueError as exc:
                erros += 1
                self.stderr.write(self.style.ERROR(f"  {parceiro.codigo_pdv}: {exc}"))

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: nada foi gravado."))
        self.stdout.write(
            f"Geradas: {len(geradas)}. Pulados: {pulados}. Erros: {erros}."
        )
        if geradas:
            self.stdout.write(
                self.style.WARNING(
                    "Senhas temporárias (anote agora; troca obrigatória no primeiro acesso):"
                )
            )
            self.stdout.write("codigo\tnome\tacão\tsenha")
            for codigo, nome, senha, acao in geradas:
                self.stdout.write(f"{codigo}\t{nome}\t{acao}\t{senha}")
