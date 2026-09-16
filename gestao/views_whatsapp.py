from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from tickets.acesso import eh_gestor, equipe_required

from .messaging.evolution_connection import EvolutionConnectionError, instancia_global
from .messaging.instancia import (
    gravar_status,
    modo_envio_whatsapp,
    salvar_modo_envio,
    servico_painel,
)
from .messaging.syncwa import syncwa_configurado


def _svc(request: HttpRequest):
    return servico_painel(request.user)


@equipe_required
def whatsapp_view(request: HttpRequest) -> HttpResponse:
    if (
        request.method == "POST"
        and request.POST.get("action") == "modo_envio"
    ):
        if not eh_gestor(request.user):
            raise Http404("Página não encontrada.")
        modo = salvar_modo_envio(request.POST.get("modo_envio") or "")
        if modo == "pessoal":
            messages.success(
                request,
                "Envios da equipe passam a sair do WhatsApp de cada especialista/gerência.",
            )
        else:
            messages.success(
                request,
                "Envios voltam a sair do chip da gestão (nio_gc_tickets).",
            )
        return redirect("gestao_whatsapp")
    svc = _svc(request)
    central = eh_gestor(request.user)
    return render(
        request,
        "gestao/whatsapp.html",
        {
            "syncwa_ok": syncwa_configurado(),
            "instance_name": svc.instance_name,
            "instance_global": instancia_global(),
            "evolution_ok": bool(svc.base_url and svc.api_key),
            "n8n_ok": bool((getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()),
            "instancia_central": central,
            "modo_envio": modo_envio_whatsapp(),
        },
    )


@equipe_required
@require_GET
def whatsapp_status_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse(
            {
                "connected": False,
                "state": "unconfigured",
                "instanceName": _svc(request).instance_name,
                "evolutionConfigured": False,
                "message": "EVOLUTION_API_URL / EVOLUTION_API_KEY ausentes no Railway.",
            },
            status=503,
        )
    try:
        status = _svc(request).get_status()
        gravar_status(request.user, status)
        return JsonResponse(status)
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc), "connected": False, "state": "error"}, status=503)


@equipe_required
@require_GET
def whatsapp_qrcode_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse({"detail": "Evolution não configurada no servidor."}, status=503)
    try:
        data = _svc(request).get_qrcode()
        return JsonResponse(data)
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)


@equipe_required
@require_POST
def whatsapp_disconnect_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse({"detail": "Evolution não configurada no servidor."}, status=503)
    try:
        data = _svc(request).disconnect()
        gravar_status(request.user, data.get("status") or {})
        return JsonResponse(data)
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
