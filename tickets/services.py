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
