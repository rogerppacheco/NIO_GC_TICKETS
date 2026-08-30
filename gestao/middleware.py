from __future__ import annotations

from .messaging.request_ctx import reset_request, set_request


class RequestContextMiddleware:
    """Permite ao syncwa ler sessão/usuário durante envios WhatsApp."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_request(token)
