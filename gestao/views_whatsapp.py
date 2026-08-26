from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from tickets.acesso import gestor_required

from .messaging.evolution_connection import EvolutionConnectionError, EvolutionConnectionService
from .messaging.syncwa import syncwa_configurado


def _svc() -> EvolutionConnectionService:
    return EvolutionConnectionService()


@gestor_required
def whatsapp_view(request: HttpRequest) -> HttpResponse:
    svc = _svc()
    return render(
        request,
        "gestao/whatsapp.html",
        {
            "syncwa_ok": syncwa_configurado(),
            "instance_name": svc.instance_name,
            "evolution_ok": bool(svc.base_url and svc.api_key),
            "n8n_ok": bool((getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()),
        },
    )


@gestor_required
@require_GET
def whatsapp_status_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse(
            {
                "connected": False,
                "state": "unconfigured",
                "instanceName": _svc().instance_name,
                "evolutionConfigured": False,
                "message": "EVOLUTION_API_URL / EVOLUTION_API_KEY ausentes no Railway.",
            },
            status=503,
        )
    try:
        return JsonResponse(_svc().get_status())
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc), "connected": False, "state": "error"}, status=503)


@gestor_required
@require_GET
def whatsapp_qrcode_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse({"detail": "Evolution não configurada no servidor."}, status=503)
    try:
        return JsonResponse(_svc().get_qrcode())
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)


@gestor_required
@require_POST
def whatsapp_disconnect_api(request: HttpRequest) -> JsonResponse:
    if not syncwa_configurado():
        return JsonResponse({"detail": "Evolution não configurada no servidor."}, status=503)
    try:
        return JsonResponse(_svc().disconnect())
    except EvolutionConnectionError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
