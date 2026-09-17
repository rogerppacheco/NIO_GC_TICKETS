from __future__ import annotations

from django.db.models import Exists, OuterRef, QuerySet
from django.db.utils import OperationalError, ProgrammingError

from .models import (
    Comunicado,
    ComunicadoLeitura,
    ContatoParceiro,
    Mensagem,
    Prioridade,
    Ticket,
    TipoDemanda,
)


def publicos_do_usuario(user) -> list[str]:
    from .acesso import parceiro_de, tem_acesso_interno

    pubs: list[str] = []
    if parceiro_de(user):
        pubs.extend([Comunicado.Publico.PARCEIROS, Comunicado.Publico.TODOS])
    if tem_acesso_interno(user):
        pubs.extend([Comunicado.Publico.EQUIPE, Comunicado.Publico.TODOS])
    vistos: set[str] = set()
    saida: list[str] = []
    for item in pubs:
        if item not in vistos:
            vistos.add(item)
            saida.append(item)
    return saida


def qs_comunicados_visiveis(user) -> QuerySet:
    pubs = publicos_do_usuario(user)
    if not pubs:
        return Comunicado.objects.none()
    return Comunicado.objects.filter(
        ativo=True,
        publico__in=pubs,
        publicado_em__isnull=False,
    )


def qs_comunicados_com_leitura(user) -> QuerySet:
    sub = ComunicadoLeitura.objects.filter(
        comunicado_id=OuterRef("pk"), usuario=user
    )
    return qs_comunicados_visiveis(user).annotate(lido=Exists(sub))


def qs_pendentes(user) -> QuerySet:
    return qs_comunicados_com_leitura(user).filter(lido=False).order_by(
        "publicado_em", "id"
    )


def proximo_pendente(user):
    return qs_pendentes(user).first()


def deve_confirmar_comunicado(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", True):
        return False
    try:
        return qs_pendentes(user).exists()
    except (ProgrammingError, OperationalError):
        return False


def contar_nao_lidos(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    try:
        return qs_pendentes(user).count()
    except (ProgrammingError, OperationalError):
        return 0


def abrir_demanda_duvida(user, comunicado: Comunicado, request=None) -> Ticket | None:
    from .acesso import parceiro_de

    pdv = parceiro_de(user)
    if not pdv:
        return None
    contato = None
    if request is not None:
        cid = request.session.get("contato_id")
        if cid:
            contato = ContatoParceiro.objects.filter(
                pk=cid, parceiro=pdv, ativo=True
            ).first()
    nome = (
        (contato.nome if contato else "")
        or (user.get_full_name() or user.get_username() or "")
    ).strip()
    texto = (
        f"Não entendi o comunicado/aviso [{comunicado.titulo}].\n\n"
        f"{comunicado.corpo}"
    )
    ticket = Ticket.objects.create(
        parceiro=pdv,
        contato=contato,
        tipo=TipoDemanda.OUTROS,
        descricao=texto,
        solicitante_nome=nome[:120],
        prioridade=Prioridade.NORMAL,
    )
    Mensagem.objects.create(
        ticket=ticket,
        autor=user,
        autor_nome=nome[:120],
        corpo=texto,
    )
    return ticket


def notificar_demanda_comunicado(ticket: Ticket, ator=None) -> None:
    from .services import (
        notificar_demanda_com_anexo,
        notificar_mascaras_por_email,
        notificar_mascaras_por_whatsapp,
    )

    try:
        notificar_mascaras_por_email(ticket)
        notificar_mascaras_por_whatsapp(ticket)
        notificar_demanda_com_anexo(ticket, ator=ator)
    except Exception:
        pass


def confirmar_comunicado(
    user, comunicado: Comunicado, *, entendeu: bool, request=None
) -> ComunicadoLeitura:
    leitura, created = ComunicadoLeitura.objects.get_or_create(
        comunicado=comunicado,
        usuario=user,
        defaults={"entendeu": entendeu},
    )
    if not created:
        return leitura
    if not entendeu:
        ticket = abrir_demanda_duvida(user, comunicado, request)
        if ticket:
            leitura.ticket = ticket
            leitura.save(update_fields=["ticket"])
    return leitura
