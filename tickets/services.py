from __future__ import annotations

import re
from typing import Any

from django.utils.formats import date_format

from .models import Mascara, Ticket


def _fmt_date(value) -> str:
    if not value:
        return ""
    try:
        return date_format(value, "SHORT_DATE_FORMAT")
    except Exception:
        return str(value)


def ticket_context(ticket: Ticket) -> dict[str, Any]:
    return {
        "protocolo": ticket.protocolo,
        "parceiro": ticket.parceiro.nome,
        "pdv": ticket.parceiro.codigo_pdv,
        "tipo": ticket.get_tipo_display(),
        "pedido": ticket.pedido,
        "pedidos": "\n".join(
            [p for p in [ticket.pedido, *ticket.pedidos_extras.splitlines()] if p.strip()]
        ),
        "documento": ticket.documento_cliente,
        "endereco": ticket.endereco_completo or ticket.montar_endereco(),
        "cep": ticket.cep,
        "logradouro": ticket.logradouro,
        "fachada": ticket.numero_fachada,
        "numero": ticket.numero_fachada,
        "complemento": ticket.complemento,
        "bairro": ticket.bairro,
        "cidade": ticket.cidade,
        "uf": (ticket.uf or "").upper(),
        "data": _fmt_date(ticket.data_desejada),
        "turno": ticket.get_turno_display() if ticket.turno else "",
        "data_2": _fmt_date(ticket.data_alternativa),
        "turno_2": ticket.get_turno_alternativo_display() if ticket.turno_alternativo else "",
        "nome_cliente": ticket.nome_cliente,
        "data_instalacao": _fmt_date(ticket.data_instalacao),
        "descricao": ticket.descricao,
        "observacoes": ticket.observacoes,
        "solicitante": ticket.solicitante_nome or (ticket.contato.nome if ticket.contato_id else ""),
        "contato": ticket.solicitante_contato or (ticket.contato.telefone if ticket.contato_id else ""),
        "contato_nome": ticket.contato.nome if ticket.contato_id else "",
        "tt": ticket.tt,
        "tt_vendedor": ticket.tt_vendedor,
        "tt_backoffice": ticket.tt_backoffice,
        "os": ticket.pedido,
        "status": ticket.get_status_display(),
        "resposta": ticket.resposta_publica,
        "resultado": ticket.resultado_status,
        "senha": (ticket.retorno_dados or {}).get("senha_resetada", ""),
        "endereco_consultado": (ticket.retorno_dados or {}).get("endereco_consultado", ""),
        "status_agendamento": (ticket.retorno_dados or {}).get("status_agendamento", ""),
        "etapa_erro": ticket.observacoes or ticket.descricao,
        "detalhe_cenario": ticket.descricao,
        "login_bo": ticket.tt_backoffice,
        "login_vendedor": ticket.tt_vendedor or ticket.solicitante_nome,
        "nome_gc": _nome_atendente(ticket),
        "numero_registro": ticket.protocolo,
    }


def _nome_atendente(ticket: Ticket) -> str:
    user = ticket.atendente
    if not user:
        return ""
    full = (user.get_full_name() or "").strip()
    return full or user.get_username()


_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_mascara(mascara: Mascara, ticket: Ticket) -> str:
    ctx = ticket_context(ticket)

    def repl(match: re.Match) -> str:
        key = match.group(1)
        return str(ctx.get(key, ""))

    return _VAR.sub(repl, mascara.template)


def notificar_mascaras_por_email(ticket: Ticket) -> int:
    """Envia máscaras marcadas para o especialista do PDV (e e-mail do parceiro, se houver)."""
    from gestao.messaging.email_smtp import enviar_email_com_anexos, smtp_configurado

    if not smtp_configurado():
        return 0
    destinos: list[str] = []
    spec = ticket.parceiro.especialista
    if spec and (spec.email or "").strip():
        destinos.append(spec.email.strip())
    if (ticket.parceiro.email or "").strip():
        destinos.append(ticket.parceiro.email.strip())
    vistos: list[str] = []
    for mail in destinos:
        if mail.lower() not in {v.lower() for v in vistos}:
            vistos.append(mail)
    if not vistos:
        return 0
    enviados = 0
    for mascara in Mascara.objects.filter(ativo=True, enviar_email=True):
        if not mascara.aplica_para(ticket.tipo):
            continue
        corpo = render_mascara(mascara, ticket)
        ok, _erro = enviar_email_com_anexos(
            vistos,
            assunto=f"[NIO GC] {mascara.nome} · {ticket.protocolo} · {ticket.parceiro.nome}",
            corpo_texto=corpo,
        )
        if ok:
            enviados += 1
    return enviados


def enviar_mascara_whatsapp(
    ticket: Ticket,
    mascara: Mascara,
    destino_jid: str | None = None,
    destino_nome: str | None = None,
    user=None,
) -> tuple[bool, str]:
    """Envia máscara renderizada via WhatsApp.
    - Se destino_jid for omitido e o parceiro tiver especialista (não-admin), envia para o WhatsApp do especialista.
    - Se for admin, exige que destino_jid seja fornecido (grupo ou pessoa escolhida).
    """
    from django.utils import timezone
    from gestao.messaging.envio import whatsapp_do_usuario
    from gestao.messaging.syncwa import enviar_texto, syncwa_configurado
    from gestao.models import EnvioWhatsApp
    from .models import Encaminhamento, Mensagem, StatusTicket

    spec = ticket.parceiro.especialista if ticket.parceiro else None
    eh_admin_spec = not spec or spec.username.lower() == "admin"

    jid = (destino_jid or "").strip()
    nome = (destino_nome or "").strip()

    if not jid:
        # Verifica se o especialista tem destino configurado em seu perfil
        if spec:
            perfil = getattr(spec, "perfil_staff", None)
            if perfil:
                info_dest = perfil.obter_destino_mascara()
                if info_dest.get("configurado"):
                    if not eh_admin_spec or perfil.tipo_destino_mascara != perfil.TipoDestinoMascara.PROPRIO:
                        jid = info_dest["jid"]
                        nome = info_dest["nome"]

        if not jid:
            if not eh_admin_spec and spec:
                jid = whatsapp_do_usuario(spec)
                nome_esp = (spec.get_full_name() or spec.username).strip()
                nome = f"Especialista {nome_esp}"
                if not jid:
                    return (
                        False,
                        f"O especialista {nome_esp} responsável pelo parceiro não possui WhatsApp ou destino cadastrado no perfil.",
                    )
            else:
                return (
                    False,
                    "O parceiro é atendido pelo admin. Por favor selecione um grupo ou contato de destino para enviar.",
                )

    if not syncwa_configurado():
        return False, "SyncWA não está configurado no sistema."

    conteudo = render_mascara(mascara, ticket)
    if not conteudo.strip():
        return False, "O conteúdo da máscara gerada está vazio."

    resp = enviar_texto(jid, conteudo)
    if not resp.ok:
        return False, f"Falha ao enviar via WhatsApp para {nome or jid}: {resp.error}"

    # 1. Registra o encaminhamento oficial
    Encaminhamento.objects.create(
        ticket=ticket,
        mascara=mascara,
        destino=f"WhatsApp {nome} ({jid})",
        conteudo=conteudo,
        criado_por=user if (user and getattr(user, "is_authenticated", False)) else None,
    )

    # 2. Registra no histórico do ticket
    autor_label = (
        (user.get_full_name() or user.username).strip()
        if (user and getattr(user, "is_authenticated", False))
        else "Sistema"
    )
    Mensagem.objects.create(
        ticket=ticket,
        autor=user if (user and getattr(user, "is_authenticated", False)) else None,
        autor_nome=autor_label,
        corpo=f"📱 Máscara '{mascara.nome}' enviada via WhatsApp para {nome} ({jid}).",
    )

    # 3. Registra log de envio
    try:
        EnvioWhatsApp.objects.create(
            tipo=EnvioWhatsApp.Tipo.MASCARA,
            status=EnvioWhatsApp.Status.ENVIADO,
            parceiro=ticket.parceiro,
            destino_jid=jid,
            destino_nome=nome,
            mensagem=conteudo,
            syncwa_message_id=getattr(resp, "message_id", "") or "",
            criado_por=user if (user and getattr(user, "is_authenticated", False)) else None,
        )
    except Exception:
        pass

    # 4. Atualiza status do ticket
    ticket.status = StatusTicket.ENCAMINHADO
    ticket.destino_encaminhamento = f"WhatsApp {nome}"
    if not ticket.primeiro_atendimento_em:
        ticket.primeiro_atendimento_em = timezone.now()
    if user and getattr(user, "is_authenticated", False) and not ticket.atendente:
        ticket.atendente = user
    ticket.save(
        update_fields=[
            "status",
            "destino_encaminhamento",
            "primeiro_atendimento_em",
            "atendente",
            "atualizado_em",
        ]
    )

    return True, f"Máscara '{mascara.nome}' enviada com sucesso para {nome} ({jid})!"


def notificar_mascaras_por_whatsapp(ticket: Ticket) -> int:
    """Envia máscaras marcadas com enviar_whatsapp=True para o destino configurado do especialista (quando não for admin)."""
    if not ticket.parceiro:
        return 0
    spec = ticket.parceiro.especialista
    if not spec or spec.username.lower() == "admin":
        return 0
    from gestao.messaging.envio import whatsapp_do_usuario

    perfil = getattr(spec, "perfil_staff", None)
    info_dest = perfil.obter_destino_mascara() if perfil else {}
    dest_jid = info_dest.get("jid") or whatsapp_do_usuario(spec)
    dest_nome = info_dest.get("nome") or f"Especialista {(spec.get_full_name() or spec.username).strip()}"
    if not dest_jid:
        return 0

    enviados = 0
    for mascara in Mascara.objects.filter(ativo=True, enviar_whatsapp=True):
        if not mascara.aplica_para(ticket.tipo):
            continue
        ok, _ = enviar_mascara_whatsapp(
            ticket,
            mascara,
            destino_jid=dest_jid,
            destino_nome=dest_nome,
        )
        if ok:
            enviados += 1
    return enviados
