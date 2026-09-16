from __future__ import annotations

from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .acesso import aplicar_gerencia_sessao, eh_parceiro, parceiro_de, tem_acesso_interno
from .seguranca import deve_trocar_senha, sessao_ociosa, tocar_atividade

LIVRE_PREFIXOS = (
    "/login/",
    "/logout/",
    "/senha/",
    "/static/",
    "/media/",
)

PORTAL_PREFIXOS = (
    "/abrir/",
    "/consulta/",
    "/consultas/",
    "/repositorio/",
    "/tradehub/",
    "/senha/",
    "/perfil/",
)


def _livre(path: str) -> bool:
    return any(path.startswith(p) for p in LIVRE_PREFIXOS)


def _portal(path: str) -> bool:
    return any(path.startswith(p) for p in PORTAL_PREFIXOS)


class AcessoInternoMiddleware:
    """Login obrigatório. Equipe na área interna; PDV só no portal.

    O auth_user é do schema deste app; sem PerfilStaff a pessoa não entra na fila.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        path = request.path
        autenticado = bool(user and user.is_authenticated)

        if not autenticado:
            if _livre(path) or path in {"/", ""}:
                return self.get_response(request)
            login_url = reverse("login")
            if path != login_url:
                return redirect(f"{login_url}?next={path}")
            return self.get_response(request)

        if sessao_ociosa(request):
            logout(request)
            return redirect("login")
        tocar_atividade(request)

        if deve_trocar_senha(user) and not _livre(path):
            return redirect("senha_trocar")

        if tem_acesso_interno(user):
            aplicar_gerencia_sessao(request)
            return self.get_response(request)

        if eh_parceiro(user) or parceiro_de(user):
            pdv = parceiro_de(user)
            if pdv and not pdv.ativo:
                logout(request)
                return redirect("login")
            if _portal(path) or _livre(path):
                return self.get_response(request)
            return redirect("portal_parceiro")

        logout(request)
        return redirect("login")
