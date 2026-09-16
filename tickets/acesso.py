from __future__ import annotations

from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect

from .models import Parceiro, PerfilStaff, Ticket


def perfil_de(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.perfil_staff
    except (ObjectDoesNotExist, AttributeError):
        return None


def parceiro_de(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.parceiro_conta
    except (ObjectDoesNotExist, AttributeError):
        return None


def tem_acesso_interno(user) -> bool:
    return perfil_de(user) is not None


def eh_admin(user) -> bool:
    perfil = perfil_de(user)
    return bool(perfil and perfil.papel == PerfilStaff.Papel.GESTOR)


def eh_gestor(user) -> bool:
    """Alias histórico: Admin (não inclui Gerência)."""
    return eh_admin(user)


def eh_gerencia(user) -> bool:
    perfil = perfil_de(user)
    return bool(perfil and perfil.papel == PerfilStaff.Papel.GERENCIA)


def eh_especialista(user) -> bool:
    perfil = perfil_de(user)
    return bool(perfil and perfil.papel == PerfilStaff.Papel.ESPECIALISTA)


def eh_parceiro(user) -> bool:
    pdv = parceiro_de(user)
    return bool(pdv and pdv.ativo)


def qs_equipe():
    """Quem pode ser vinculado a um PDV: gestores, gerência e especialistas deste app."""
    User = get_user_model()
    return (
        User.objects.filter(is_active=True, perfil_staff__isnull=False)
        .select_related("perfil_staff")
        .order_by("first_name", "username")
    )


def qs_especialistas():
    return qs_equipe().filter(perfil_staff__papel=PerfilStaff.Papel.ESPECIALISTA)


def ids_parceiros_da_gerencia(gerencia: str):
    from gestao.models import VendaOSAB

    texto = (gerencia or "").strip()
    if not texto:
        return Parceiro.objects.none()
    ids_osab = (
        VendaOSAB.objects.filter(gerencia__iexact=texto)
        .exclude(parceiro_id=None)
        .values("parceiro_id")
    )
    return Parceiro.objects.filter(
        Q(especialista__perfil_staff__gerencia__iexact=texto) | Q(id__in=ids_osab)
    )


def tickets_visiveis(user):
    qs = Ticket.objects.select_related(
        "parceiro",
        "atendente",
        "parceiro__especialista",
        "parceiro__especialista__perfil_staff",
    )
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if eh_admin(user):
        return qs
    if eh_gerencia(user):
        gerencia = gerencia_de(user)
        if not gerencia:
            return qs.none()
        return qs.filter(parceiro__in=ids_parceiros_da_gerencia(gerencia))
    pdv = parceiro_de(user)
    if pdv:
        return qs.filter(parceiro=pdv)
    return qs.filter(parceiro__especialista=user)


def parceiros_visiveis(user):
    qs = Parceiro.objects.all()
    if eh_admin(user):
        return qs
    if eh_gerencia(user):
        gerencia = gerencia_de(user)
        if not gerencia:
            return qs.none()
        return qs.filter(pk__in=ids_parceiros_da_gerencia(gerencia).values("id"))
    pdv = parceiro_de(user)
    if pdv:
        return qs.filter(pk=pdv.pk)
    return qs.filter(especialista=user)


def escopo_gestao(request) -> str:
    src = request.POST if getattr(request, "method", "") == "POST" else getattr(request, "GET", {})
    valor = (src.get("escopo") or "meus").strip().lower()
    return valor if valor in {"meus", "outros", "todos"} else "meus"


GERENCIA_SESSAO = "gestao_gerencia"
GERENCIA_TODAS = "__todas__"


def listar_gerencias() -> list[str]:
    """Gerências conhecidas (perfil da equipe + coluna GERENCIA da OSAB)."""
    vistos: dict[str, str] = {}

    def _add(valor: str) -> None:
        texto = (valor or "").strip()
        if texto:
            vistos.setdefault(texto.casefold(), texto)

    for g in PerfilStaff.objects.exclude(gerencia="").values_list("gerencia", flat=True):
        _add(g)
    from gestao.models import VendaOSAB

    for g in (
        VendaOSAB.objects.exclude(gerencia="").values_list("gerencia", flat=True).distinct()
    ):
        _add(g)
    return sorted(vistos.values(), key=str.casefold)


def aplicar_gerencia_sessao(request) -> None:
    """Admin pode recortar as bases da Gestão sem mudar o cadastro do perfil."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False) or not eh_admin(user):
        return
    if GERENCIA_SESSAO not in request.session:
        return
    bruto = request.session.get(GERENCIA_SESSAO)
    if bruto == GERENCIA_TODAS:
        user._gerencia_cache = ""
        return
    user._gerencia_cache = (bruto or "").strip()


def gerencia_seletor_valor(request) -> str:
    if getattr(request, "session", None) and request.session.get(GERENCIA_SESSAO) == GERENCIA_TODAS:
        return GERENCIA_TODAS
    user = getattr(request, "user", None)
    return gerencia_de(user) or GERENCIA_TODAS


def gerencia_de(user) -> str:
    """Gerência do perfil ou, no especialista, a mais frequente na OSAB dos PDVs dele."""
    cached = getattr(user, "_gerencia_cache", None)
    if cached is not None:
        return cached
    perfil = perfil_de(user)
    valor = (perfil.gerencia or "").strip() if perfil else ""
    if not valor and user and not eh_admin(user) and not eh_gerencia(user):
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
    return eh_admin(user) and not gerencia_de(user)


def pode_importar_bases(user) -> bool:
    """Admin, gerência e especialista importam OSAB e as demais bases da Gestão."""
    return tem_acesso_interno(user)


def parceiros_gestao(user, escopo: str = "meus"):
    """Abas de Gestão: meus PDVs vs PDVs de outros da mesma gerência."""
    qs = Parceiro.objects.filter(ativo=True).select_related(
        "especialista", "especialista__perfil_staff"
    )
    gerencia = gerencia_de(user)
    if gerencia:
        qs = qs.filter(pk__in=ids_parceiros_da_gerencia(gerencia).values("id"))
    elif not eh_admin(user):
        if escopo in {"outros", "todos"}:
            return qs.none()
        return qs.filter(especialista=user).order_by("nome")
    if escopo == "todos":
        return qs.order_by("nome")
    if escopo == "outros":
        return qs.exclude(especialista=user).order_by("nome")
    return qs.filter(especialista=user).order_by("nome")


def parceiros_gestao_ambos(user):
    """Meus + outros da mesma gerência (cadastros que não usam aba)."""
    return (
        parceiros_gestao(user, "meus") | parceiros_gestao(user, "outros")
    ).distinct().order_by("nome")


def parceiros_para_destinatarios(user):
    """Admin cadastra destinatários em qualquer gerência; os demais seguem o recorte da Gestão."""
    if eh_admin(user):
        return Parceiro.objects.filter(ativo=True).select_related(
            "especialista", "especialista__perfil_staff"
        ).order_by("nome")
    return parceiros_gestao_ambos(user)


def parceiros_para_cadastro(user, escopo: str = "meus"):
    """Aba Parceiros: admin vê todas as gerências; especialista/gerência seguem o recorte da Gestão."""
    if eh_admin(user):
        qs = Parceiro.objects.filter(ativo=True).select_related(
            "especialista", "especialista__perfil_staff"
        )
        if escopo == "outros":
            return qs.exclude(especialista=user).order_by("nome")
        return qs.filter(especialista=user).order_by("nome")
    return parceiros_gestao(user, escopo)


def pode_ver_ticket(user, ticket: Ticket) -> bool:
    return tickets_visiveis(user).filter(pk=ticket.pk).exists()


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
        if not eh_admin(request.user):
            raise Http404("Página não encontrada.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def equipe_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not tem_acesso_interno(request.user):
            return redirect("portal_parceiro")
        return view_func(request, *args, **kwargs)

    return _wrapped


def destino_pos_login(user) -> str:
    from django.urls import reverse

    if eh_parceiro(user) or parceiro_de(user):
        return reverse("portal_parceiro")
    if tem_acesso_interno(user):
        return reverse("portal_inicio")
    return reverse("fila")


def pode_resetar_senha(ator, alvo) -> bool:
    if not ator or not alvo or ator == alvo:
        return False
    if eh_admin(ator):
        return True
    if eh_admin(alvo):
        return False
    if eh_gerencia(ator):
        gerencia = gerencia_de(ator)
        if not gerencia:
            return False
        if eh_especialista(alvo):
            return gerencia_de(alvo).casefold() == gerencia.casefold()
        pdv = parceiro_de(alvo)
        return bool(pdv and ids_parceiros_da_gerencia(gerencia).filter(pk=pdv.pk).exists())
    if eh_especialista(ator):
        pdv = parceiro_de(alvo)
        return bool(pdv and pdv.especialista_id == ator.id)
    return False


def usuarios_gerenciaveis(ator):
    User = get_user_model()
    qs = User.objects.select_related("perfil_staff", "parceiro_conta", "conta_acesso").order_by(
        "first_name", "username"
    )
    if eh_admin(ator):
        return qs.filter(Q(perfil_staff__isnull=False) | Q(parceiro_conta__isnull=False))
    if eh_gerencia(ator):
        gerencia = gerencia_de(ator)
        if not gerencia:
            return qs.none()
        ids_pdv = ids_parceiros_da_gerencia(gerencia).values("usuario_id")
        return qs.filter(
            Q(perfil_staff__gerencia__iexact=gerencia, perfil_staff__papel=PerfilStaff.Papel.ESPECIALISTA)
            | Q(id__in=ids_pdv)
        ).exclude(perfil_staff__papel=PerfilStaff.Papel.GESTOR)
    if eh_especialista(ator):
        return qs.filter(parceiro_conta__especialista=ator)
    return qs.none()
