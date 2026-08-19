from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from .models import Parceiro, PerfilStaff, Ticket


def eh_gestor(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    perfil = getattr(user, "perfil_staff", None)
    if perfil is None:
        return True
    return perfil.papel == PerfilStaff.Papel.GESTOR


def tickets_visiveis(user):
    qs = Ticket.objects.select_related("parceiro", "atendente", "parceiro__especialista")
    if eh_gestor(user):
        return qs
    return qs.filter(parceiro__especialista=user)


def parceiros_visiveis(user):
    qs = Parceiro.objects.all()
    if eh_gestor(user):
        return qs
    return qs.filter(especialista=user)


def pode_ver_ticket(user, ticket: Ticket) -> bool:
    if eh_gestor(user):
        return True
    return ticket.parceiro.especialista_id == user.id


def ticket_para_usuario(user, protocolo: str) -> Ticket:
    ticket = get_object_or_404(
        Ticket.objects.select_related("parceiro", "atendente", "contato", "parceiro__especialista"),
        protocolo=protocolo.upper(),
    )
    if not pode_ver_ticket(user, ticket):
        raise Http404("Ticket não encontrado.")
    return ticket


def gestor_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not eh_gestor(request.user):
            raise Http404("Página não encontrada.")
        return view_func(request, *args, **kwargs)

    return _wrapped
