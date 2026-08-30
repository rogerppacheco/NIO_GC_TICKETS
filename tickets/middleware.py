from __future__ import annotations

from django.contrib.auth import logout
from django.shortcuts import redirect

from .acesso import aplicar_gerencia_sessao, tem_acesso_interno

LIVRE_PREFIXOS = (
    "/login/",
    "/logout/",
    "/abrir/",
    "/consulta/",
    "/repositorio/",
    "/consultas/dfv/",
    "/consultas/cdoe/",
    "/consultas/viabilidade/",
    "/static/",
    "/media/",
)


class AcessoInternoMiddleware:
    """Só quem tem PerfilStaff neste app entra na área interna.

    O auth_user é compartilhado com outros sistemas no mesmo Postgres;
    sem este filtro, logins de VTAL/outros apps apareciam como equipe.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        path = request.path
        if user and user.is_authenticated and not path.startswith(LIVRE_PREFIXOS):
            if not tem_acesso_interno(user):
                logout(request)
                return redirect("login")
            aplicar_gerencia_sessao(request)
        return self.get_response(request)
