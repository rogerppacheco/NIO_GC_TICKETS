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


def enviar_comunicado_whatsapp(
    comunicado: Comunicado, *, jid: str, nome: str, user, request=None
) -> tuple[bool, str]:
    """Envia o texto e os anexos do comunicado para um número ou grupo."""
    from django.urls import reverse

    from gestao.messaging.instancia import instancia_para_envio
    from gestao.messaging.syncwa import (
        SyncWAError,
        enviar_documento,
        enviar_texto,
        syncwa_configurado,
    )
    from gestao.models import EnvioWhatsApp

    destino = (jid or "").strip()
    rotulo = (nome or destino or "WhatsApp").strip()
    if not destino:
        return False, "Escolha o WhatsApp ou o grupo."
    if not syncwa_configurado():
        return False, "WhatsApp não está configurado."
    try:
        instancia = instancia_para_envio(user)
    except SyncWAError as exc:
        return False, str(exc)

    texto = f"*{comunicado.titulo}*\n\n{comunicado.corpo}".strip()
    if request is not None:
        link = request.build_absolute_uri(
            reverse("comunicado_detalhe", args=[comunicado.pk])
        )
        texto = f"{texto}\n\nAbra no portal: {link}"

    resposta = enviar_texto(destino, texto, instance=instancia)
    if not resposta.ok:
        _registrar_envio_comunicado(
            EnvioWhatsApp,
            jid=destino,
            nome=rotulo,
            mensagem=texto,
            user=user,
            ok=False,
            erro=resposta.error or "Falha no envio.",
            message_id=resposta.message_log_id,
        )
        return False, resposta.error or f"Não foi possível enviar para {rotulo}."

    falhas: list[str] = []
    for anexo in comunicado.anexos.all():
        try:
            with anexo.arquivo.open("rb") as handle:
                conteudo = handle.read()
        except Exception:
            falhas.append(anexo.nome_exibicao)
            continue
        if not conteudo:
            falhas.append(anexo.nome_exibicao)
            continue
        arquivo = enviar_documento(
            destino,
            conteudo=conteudo,
            file_name=anexo.nome_exibicao,
            caption=anexo.nome_exibicao,
            instance=instancia,
        )
        if not arquivo.ok:
            falhas.append(anexo.nome_exibicao)

    detalhe = ""
    if falhas:
        detalhe = " Não enviei estes arquivos: " + ", ".join(falhas) + "."
    _registrar_envio_comunicado(
        EnvioWhatsApp,
        jid=destino,
        nome=rotulo,
        mensagem=texto,
        user=user,
        ok=True,
        erro=detalhe.strip(),
        message_id=resposta.message_log_id,
    )
    return True, f"Enviado para {rotulo}.{detalhe}"


def _registrar_envio_comunicado(
    envio_model,
    *,
    jid: str,
    nome: str,
    mensagem: str,
    user,
    ok: bool,
    erro: str,
    message_id: str,
) -> None:
    try:
        envio_model.objects.create(
            tipo=envio_model.Tipo.COMUNICADO,
            status=envio_model.Status.ENVIADO if ok else envio_model.Status.ERRO,
            destino_jid=(jid or "")[:80],
            destino_nome=(nome or "")[:150],
            mensagem=mensagem,
            erro=(erro or "")[:2000],
            syncwa_message_id=(message_id or "")[:80],
            criado_por=user if getattr(user, "is_authenticated", False) else None,
        )
    except Exception:
        pass


def pode_baixar_anexo(user, comunicado: Comunicado) -> bool:
    from .acesso import tem_acesso_interno

    if not user or not getattr(user, "is_authenticated", False):
        return False
    if tem_acesso_interno(user):
        return True
    return qs_comunicados_visiveis(user).filter(pk=comunicado.pk).exists()


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
