from __future__ import annotations

from contextvars import ContextVar

_request_ctx: ContextVar = ContextVar("gestao_http_request", default=None)


def set_request(request):
    return _request_ctx.set(request)


def reset_request(token) -> None:
    _request_ctx.reset(token)


def get_request():
    return _request_ctx.get()
