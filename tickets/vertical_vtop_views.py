# -*- coding: utf-8 -*-
"""API da automação SmartRiser (V.top) acionada pelo Projeto Vertical."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from tickets.acesso import eh_admin, eh_especialista, eh_gerencia
from tickets.models import SolicitacaoVertical
from tickets.vertical_services import qs_solicitacoes, resolver_parceiro_informado
from tickets.vertical_vtop_service import (
    get_vtop_service,
    montar_payload_vertical,
    payload_para_bloco,
)


def pode_usar_smartriser(user) -> bool:
    return eh_admin(user) or eh_gerencia(user) or eh_especialista(user)


def _body(request: HttpRequest) -> Dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _negado() -> JsonResponse:
    return JsonResponse({"ok": False, "error": "Acesso negado."}, status=403)


def _carregar(request: HttpRequest, pk: int) -> Optional[SolicitacaoVertical]:
    """Só acionamentos visíveis ao usuário (especialista: carteira dele)."""
    return qs_solicitacoes(request.user).filter(pk=pk).first()


def _payload_com_overrides(item: SolicitacaoVertical, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = montar_payload_vertical(item)
    for chave in ("cod_survey", "estacao", "celula", "cdoi_codigo", "complemento"):
        if chave in data and data.get(chave) is not None:
            payload[chave] = str(data.get(chave)).strip()
    return payload


@login_required
@require_GET
def vtop_status(request: HttpRequest, pk: int | None = None) -> JsonResponse:
    if not pode_usar_smartriser(request.user):
        return _negado()
    return JsonResponse({"ok": True, "state": get_vtop_service().get_state()})


@login_required
@require_POST
def vtop_iniciar(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Inicia a automação para a solicitação (1 bloco = 1 obra).

    Body JSON: bloco, somente_ate ("login"), vtop_usuario / vtop_senha (só memória
    desta execução), obra_id + forcar_obra_id, permitir_criar, forcar_login, overrides.
    """
    if not pode_usar_smartriser(request.user):
        return _negado()
    item = _carregar(request, pk)
    if not item:
        return JsonResponse({"ok": False, "error": "Solicitação não encontrada."}, status=404)

    data = _body(request)
    if str(data.get("parceiro_id") or "").strip():
        pdv, erro_pdv = resolver_parceiro_informado(request.user, data.get("parceiro_id"))
        if erro_pdv:
            return JsonResponse(
                {"ok": False, "error": erro_pdv, "faltando": ["codigo_sap"]},
                status=400,
            )
        if item.parceiro_id != pdv.id:
            item.parceiro = pdv
            item.save(update_fields=["parceiro", "atualizado_em"])
    payload = _payload_com_overrides(item, data)
    somente_ate = (data.get("somente_ate") or "").strip().lower() or None

    bloco = (data.get("bloco") or data.get("nome_bloco") or "").strip()
    if bloco:
        try:
            payload = payload_para_bloco(payload, bloco)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    elif somente_ate and somente_ate != "login" and not payload.get("complemento"):
        return JsonResponse(
            {
                "ok": False,
                "error": "Informe o bloco (ex.: BLOCO 05). Cada bloco vira uma obra separada.",
                "blocos": [b.get("nome") for b in (payload.get("blocos") or [])],
            },
            status=400,
        )

    if data.get("obra_id"):
        payload["obra_id"] = str(data.get("obra_id")).strip()
    if data.get("forcar_obra_id"):
        payload["forcar_obra_id"] = True
    if "permitir_criar" in data:
        payload["permitir_criar"] = bool(data.get("permitir_criar"))
    usuario = (data.get("vtop_usuario") or "").strip()
    senha = data.get("vtop_senha") or ""
    if usuario:
        payload["vtop_usuario"] = usuario
    if senha:
        payload["vtop_senha"] = str(senha)

    faltando = []
    if somente_ate != "login":
        if not payload.get("codigo_sap"):
            return JsonResponse(
                {
                    "ok": False,
                    "error": (
                        "Acionamento sem PDV vinculado: não há código SAP para o Cadastro "
                        "do SmartRiser."
                    ),
                    "faltando": ["codigo_sap"],
                },
                status=400,
            )
        if not payload.get("nome_condominio"):
            faltando.append("nome_condominio")
        if not payload.get("logradouro"):
            faltando.append("logradouro")
        if not payload.get("uf"):
            faltando.append("uf")
        if bloco and not payload.get("complemento"):
            faltando.append("bloco")
    if faltando:
        return JsonResponse(
            {"ok": False, "error": "Dados incompletos na solicitação.", "faltando": faltando},
            status=400,
        )

    result = get_vtop_service().iniciar(
        cdoi_id=pk,
        payload=payload,
        forcar_login=bool(data.get("forcar_login")),
        pausar_apos=data.get("pausar_apos") or None,
        somente_ate=somente_ate,
    )
    if isinstance(result.get("state"), dict):
        result["state"].get("extras", {}).pop("vtop_senha", None)
    return JsonResponse(result, status=200 if result.get("ok") else 409)


@login_required
@require_POST
def vtop_senha_pronta(request: HttpRequest, pk: int) -> JsonResponse:
    if not pode_usar_smartriser(request.user):
        return _negado()
    if not _carregar(request, pk):
        return JsonResponse({"ok": False, "error": "Solicitação não encontrada."}, status=404)
    result = get_vtop_service().signal_senha_pronta()
    return JsonResponse(result, status=200 if result.get("ok") else 409)


@login_required
@require_POST
def vtop_fechar(request: HttpRequest, pk: int | None = None) -> JsonResponse:
    if not pode_usar_smartriser(request.user):
        return _negado()
    manter = _body(request).get("manter_sessao", True)
    if isinstance(manter, str):
        manter = manter.lower() not in ("false", "0", "no")
    return JsonResponse(get_vtop_service().fechar_navegador(manter_sessao=bool(manter)))


@login_required
@require_POST
def vtop_invalidar_sessao(request: HttpRequest) -> JsonResponse:
    if not pode_usar_smartriser(request.user):
        return _negado()
    return JsonResponse(get_vtop_service().invalidar_sessao())


@login_required
@require_GET
def vtop_payload(request: HttpRequest, pk: int) -> JsonResponse:
    """Mapeamento Solicitação → V.top sem abrir o browser (validar dados)."""
    if not pode_usar_smartriser(request.user):
        return _negado()
    item = _carregar(request, pk)
    if not item:
        return JsonResponse({"ok": False, "error": "Solicitação não encontrada."}, status=404)
    payload = montar_payload_vertical(item)
    for k in ("link_carta", "link_fachada"):
        if payload.get(k):
            payload[k + "_presente"] = True
            payload[k] = (payload[k][:80] + "…") if len(payload[k]) > 80 else payload[k]
    return JsonResponse({"ok": True, "payload": payload})
