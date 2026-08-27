from __future__ import annotations

from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from .models import Parceiro, PerfilStaff, Ticket


def perfil_de(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.perfil_staff
    except (ObjectDoesNotExist, AttributeError):
        return None


def tem_acesso_interno(user) -> bool:
    return perfil_de(user) is not None


def eh_gestor(user) -> bool:
    perfil = perfil_de(user)
    return bool(perfil and perfil.papel == PerfilStaff.Papel.GESTOR)


def qs_equipe():
    """Quem pode ser vinculado a um PDV: gestores e especialistas deste app."""
    User = get_user_model()
    return (
        User.objects.filter(is_active=True, perfil_staff__isnull=False)
        .select_related("perfil_staff")
        .order_by("first_name", "username")
    )


def qs_especialistas():
    return qs_equipe().filter(perfil_staff__papel=PerfilStaff.Papel.ESPECIALISTA)


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


def escopo_gestao(request) -> str:
    src = request.POST if getattr(request, "method", "") == "POST" else getattr(request, "GET", {})
    valor = (src.get("escopo") or "meus").strip().lower()
    return valor if valor in {"meus", "outros"} else "meus"


def gerencia_de(user) -> str:
    """Gerência do perfil ou, no especialista, a mais frequente na OSAB dos PDVs dele."""
    cached = getattr(user, "_gerencia_cache", None)
    if cached is not None:
        return cached
    perfil = perfil_de(user)
    valor = (perfil.gerencia or "").strip() if perfil else ""
    if not valor and user and not eh_gestor(user):
        from django.db.models import Count

        from gestao.models import VendaOSAB

        row = (
            VendaOSAB.objects.filter(parceiro__especialista=user)
            .exclude(gerencia="")
            .values("gerencia")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        valor = (row["gerencia"] if row else "") or ""
    if user is not None:
        user._gerencia_cache = valor
    return valor


def ve_relatorios_sem_pdv(user) -> bool:
    """Relatório consolidado (sem PDV) mistura gerências: só admin sem gerência vê."""
    return eh_gestor(user) and not gerencia_de(user)


def pode_importar_bases(user) -> bool:
    """Gestor e especialista importam OSAB e as demais bases da Gestão."""
    return tem_acesso_interno(user)


def parceiros_gestao(user, escopo: str = "meus"):
    """Abas de Gestão: meus PDVs vs PDVs de outros da mesma gerência."""
    from django.db.models import Q

    qs = Parceiro.objects.filter(ativo=True).select_related(
        "especialista", "especialista__perfil_staff"
    )
    gerencia = gerencia_de(user)
    if gerencia:
        from gestao.models import VendaOSAB

        ids_osab = (
            VendaOSAB.objects.filter(gerencia__iexact=gerencia)
            .exclude(parceiro_id=None)
            .values("parceiro_id")
        )
        qs = qs.filter(
            Q(especialista__perfil_staff__gerencia__iexact=gerencia) | Q(id__in=ids_osab)
        )
    elif not eh_gestor(user):
        if escopo == "outros":
            return qs.none()
        return qs.filter(especialista=user).order_by("nome")
    if escopo == "outros":
        return qs.exclude(especialista=user).order_by("nome")
    return qs.filter(especialista=user).order_by("nome")


def parceiros_gestao_ambos(user):
    """Meus + outros da mesma gerência (cadastros que não usam aba)."""
    return (
        parceiros_gestao(user, "meus") | parceiros_gestao(user, "outros")
    ).distinct().order_by("nome")


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
