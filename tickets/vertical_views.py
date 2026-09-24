# -*- coding: utf-8 -*-
"""Views do card Projeto Vertical."""
from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from tickets.acesso import tem_acesso_interno
from tickets.models import SolicitacaoVertical
from tickets.vertical_services import (
    dashboard,
    enviar_whatsapp_criacao,
    gravar_blocos,
    consultar_nominatim,
    consultar_viacep,
    ler_config_resumo,
    nome_usuario,
    payload_criar,
    parceiro_do_pedido,
    pode_gestao_vertical,
    qs_solicitacoes,
    salvar_config_resumo,
    serializar_solicitacao,
    _int,
    _texto,
)
from tickets.views import _portal_sessao


def _json_error(code: str, message: str, status: int = 400, fields: dict | None = None) -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": {"code": code, "message": message, "fields": fields or {}}},
        status=status,
    )


def _json_ok(data: Any, status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data}, status=status)


def _parse_json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dados_request(request: HttpRequest) -> dict[str, Any]:
    if request.content_type and "application/json" in request.content_type:
        return _parse_json(request)
    src = request.POST if request.method != "GET" else request.GET
    return {k: src.get(k) for k in src.keys()}


@login_required
def vertical_portal(request: HttpRequest) -> HttpResponse:
    if tem_acesso_interno(request.user):
        return render(
            request,
            "tickets/vertical_portal.html",
            {
                "visao_equipe": True,
                "can_config": pode_gestao_vertical(request.user),
                "parceiro": None,
                "contato": None,
                "acionado_por_nome": nome_usuario(request.user),
            },
        )
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return redirect(f"{reverse('portal_contato')}?next=vertical")
    return render(
        request,
        "tickets/vertical_portal.html",
        {
            "visao_equipe": False,
            "can_config": False,
            "parceiro": parceiro,
            "contato": contato,
            "acionado_por_nome": contato.nome,
        },
    )


@login_required
@require_GET
def vertical_api_dashboard(request: HttpRequest) -> JsonResponse:
    dados = dashboard(qs_solicitacoes(request.user))
    dados["success"] = True
    return _json_ok(dados)


@login_required
@require_http_methods(["GET", "POST"])
def vertical_api_solicitacoes(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        gestao = pode_gestao_vertical(request.user)
        itens = [
            serializar_solicitacao(item, request, can_edit=gestao)
            for item in qs_solicitacoes(request.user).order_by("-data_criacao")[:400]
        ]
        return _json_ok(itens)

    dados = _dados_request(request)
    payload = payload_criar(dados)
    if not payload["nome_condominio"]:
        return _json_error(
            "validation_error",
            "Nome do condomínio é obrigatório.",
            status=422,
            fields={"nome_condominio": "Obrigatório."},
        )
    if not payload["nome_sindico"]:
        return _json_error(
            "validation_error",
            "Nome do síndico é obrigatório.",
            status=422,
            fields={"nome_sindico": "Obrigatório."},
        )
    if len(payload["contato_sindico"]) < 10:
        return _json_error(
            "validation_error",
            "Contato WhatsApp inválido.",
            status=422,
            fields={"contato": "Informe DDD + número."},
        )
    if not request.FILES.get("arquivo_carta") or not request.FILES.get("arquivo_fachada"):
        return _json_error(
            "validation_error",
            "Envie a carta do síndico e a foto da fachada.",
            status=422,
            fields={"arquivo_carta": "Obrigatório.", "arquivo_fachada": "Obrigatório."},
        )

    cfg = ler_config_resumo()
    contato = None
    if not tem_acesso_interno(request.user):
        _parceiro, contato = _portal_sessao(request)

    blocos = payload.pop("_blocos")
    item = SolicitacaoVertical.objects.create(
        **payload,
        arquivo_carta=request.FILES["arquivo_carta"],
        arquivo_fachada=request.FILES["arquivo_fachada"],
        destinatarios_resumo=cfg["destinatarios"] if cfg["ativo"] else "",
        criado_por=request.user,
        contato=contato,
        parceiro=parceiro_do_pedido(request),
        status=SolicitacaoVertical.Status.SEM_TRATAMENTO,
    )
    if blocos:
        gravar_blocos(item, blocos)
        item.refresh_from_db()
        
    parceiro_obj = parceiro_do_pedido(request)
    protocolo_str = ""
    if parceiro_obj:
        from tickets.models import Ticket, TipoDemanda
        t = Ticket.objects.create(
            parceiro=parceiro_obj,
            contato=contato,
            tipo=TipoDemanda.OUTROS,
            solicitante_nome=item.nome_sindico,
            solicitante_contato=item.contato_sindico,
            cep=item.cep,
            logradouro=item.logradouro,
            numero_fachada=item.numero,
            bairro=item.bairro,
            cidade=item.cidade,
            uf=item.uf,
            descricao=f"Novo Projeto Vertical Acionado: {item.nome_condominio}\nID Vertical: {item.id}\nHPs: {item.total_hps}",
            observacoes=item.observacao,
        )
        protocolo_str = f" Protocolo gerado: {t.protocolo}."

    from tickets.vertical_services import enviar_whatsapp_criacao, enviar_email_criacao_vertical
    resumo = enviar_whatsapp_criacao(item)
    enviar_email_criacao_vertical(item)
    
    return _json_ok(
        {
            "id": item.id,
            "mensagem": f"Solicitação enviada! ID: {item.id}.{protocolo_str}",
            "resumo": resumo,
        },
        status=201,
    )


@login_required
@require_http_methods(["GET", "PATCH", "POST", "DELETE"])
def vertical_api_solicitacao(request: HttpRequest, pk: int) -> JsonResponse:
    qs = qs_solicitacoes(request.user)
    item = get_object_or_404(qs, pk=pk)
    gestao = pode_gestao_vertical(request.user)

    if request.method == "GET":
        return _json_ok(serializar_solicitacao(item, request, can_edit=gestao, detalhe=True))

    if request.method == "DELETE":
        if not gestao:
            return _json_error("forbidden", "Acesso negado.", status=403)
        item.delete()
        return _json_ok({"mensagem": "Solicitação excluída."})

    dados = _dados_request(request)
    if not gestao:
        # Dono pode atualizar cadastro, não o status.
        if dados.get("status") and dados.get("status") != item.status:
            return _json_error("forbidden", "Apenas gestão altera o status.", status=403)

    if request.FILES.get("arquivo_carta"):
        item.arquivo_carta = request.FILES["arquivo_carta"]
    if request.FILES.get("arquivo_fachada"):
        item.arquivo_fachada = request.FILES["arquivo_fachada"]

    payload = payload_criar(dados)
    if payload["nome_condominio"]:
        item.nome_condominio = payload["nome_condominio"]
    if payload["nome_sindico"]:
        item.nome_sindico = payload["nome_sindico"]
    if payload["contato_sindico"]:
        item.contato_sindico = payload["contato_sindico"]
    for campo in ("cep", "logradouro", "numero", "bairro", "cidade", "uf", "latitude", "longitude"):
        if dados.get(campo) is not None:
            setattr(item, campo, payload[campo])
    if dados.get("infraestrutura") or dados.get("infraestrutura_tipo"):
        item.infraestrutura_tipo = payload["infraestrutura_tipo"]
    if "possui_shaft" in dados or "possui_shaft_dg" in dados:
        item.possui_shaft_dg = payload["possui_shaft_dg"]
    if gestao and dados.get("status"):
        status = _texto(dados.get("status"), 50)
        if status in SolicitacaoVertical.Status.values:
            item.status = status
    if "observacao" in dados:
        item.observacao = _texto(dados.get("observacao"), 4000)
    item.save()
    blocos = payload.get("_blocos") or []
    if dados.get("dados_blocos_json") or dados.get("input_blocos_json"):
        gravar_blocos(item, blocos)
        item.refresh_from_db()
    return _json_ok(
        {
            "id": item.id,
            "mensagem": "Solicitação atualizada.",
            "item": serializar_solicitacao(item, request, can_edit=gestao, detalhe=True),
        }
    )

@login_required
@require_http_methods(["POST"])
def vertical_api_solicitacao_resend(request: HttpRequest, pk: int) -> JsonResponse:
    from tickets.vertical_services import enviar_whatsapp_criacao, enviar_email_criacao_vertical
    qs = qs_solicitacoes(request.user)
    item = get_object_or_404(qs, pk=pk)
    
    enviar_whatsapp_criacao(item)
    enviar_email_criacao_vertical(item)
    return _json_ok({"mensagem": "Resumo reenviado por WhatsApp e E-mail."})


@login_required
@require_GET
def vertical_api_viacep(request: HttpRequest, cep: str) -> JsonResponse:
    resultado = consultar_viacep(cep)
    if not resultado.get("ok"):
        status = 404 if resultado.get("code") == "not_found" else 400
        if resultado.get("code") == "unavailable":
            status = 502
        return _json_error(resultado.get("code") or "error", resultado.get("message") or "Falha no CEP.", status=status)
    return _json_ok(resultado["data"])


@login_required
@require_GET
def vertical_api_nominatim(request: HttpRequest) -> JsonResponse:
    q = (request.GET.get("q") or "").strip()
    postal = (request.GET.get("postalcode") or "").strip()
    if not q and not postal:
        return _json_error("validation_error", "Parâmetro ausente.", status=400)
    return _json_ok(consultar_nominatim(q, postal))


@login_required
@require_http_methods(["GET", "POST"])
def vertical_api_config(request: HttpRequest) -> JsonResponse:
    if not pode_gestao_vertical(request.user):
        return _json_error("forbidden", "Acesso negado.", status=403)
    if request.method == "GET":
        return _json_ok(ler_config_resumo())
    dados = _dados_request(request)
    ativo = str(dados.get("ativo", "1")).lower() not in {"0", "false", "off", "nao", "não"}
    return _json_ok(salvar_config_resumo(_texto(dados.get("destinatarios"), 500), ativo))


@login_required
@require_GET
def vertical_api_usuarios(request: HttpRequest) -> JsonResponse:
    if not pode_gestao_vertical(request.user):
        return _json_error("forbidden", "Acesso negado.", status=403)
    User = get_user_model()
    lista = []
    for user in User.objects.filter(is_active=True).order_by("first_name", "username")[:400]:
        lista.append({"id": user.id, "nome": nome_usuario(user)})
    return _json_ok(lista)
