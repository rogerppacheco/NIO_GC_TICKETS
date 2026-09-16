from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .acesso import (
    eh_admin,
    eh_gerencia,
    parceiro_de,
    parceiros_visiveis,
    pode_resetar_senha,
    tem_acesso_interno,
    usuarios_gerenciaveis,
)
from .forms import TrocaSenhaForm
from .models import RegistroAcesso
from .seguranca import (
    aplicar_senha,
    garantir_conta_parceiro,
    gerar_senha_temporaria,
    invalidar_sessoes,
    ip_de,
    registrar_evento,
)


@login_required
def senha_trocar(request: HttpRequest) -> HttpResponse:
    from .seguranca import deve_trocar_senha

    obrigatorio = deve_trocar_senha(request.user)
    form = TrocaSenhaForm(user=request.user, exigir_atual=not obrigatorio)
    if request.method == "POST":
        form = TrocaSenhaForm(request.POST, user=request.user, exigir_atual=not obrigatorio)
        if form.is_valid():
            aplicar_senha(request.user, form.cleaned_data["senha_nova"], must_change=False)
            update_session_auth_hash(request, request.user)
            invalidar_sessoes(request.user, manter_key=request.session.session_key)
            registrar_evento(
                RegistroAcesso.Tipo.TROCA_OBRIGATORIA if obrigatorio else RegistroAcesso.Tipo.TROCA,
                ator=request.user,
                alvo=request.user,
                ip=ip_de(request),
            )
            messages.success(request, "Senha atualizada.")
            from .acesso import destino_pos_login

            return redirect(destino_pos_login(request.user))
    return render(
        request,
        "tickets/senha_trocar.html",
        {"form": form, "obrigatorio": obrigatorio},
    )


@login_required
def acessos_lista(request: HttpRequest) -> HttpResponse:
    if not tem_acesso_interno(request.user):
        raise Http404("Página não encontrada.")
    usuarios = []
    for u in usuarios_gerenciaveis(request.user):
        try:
            u.conta = u.conta_acesso
        except ObjectDoesNotExist:
            u.conta = None
        try:
            u.pdv = u.parceiro_conta
        except ObjectDoesNotExist:
            u.pdv = None
        usuarios.append(u)
    sem_login = parceiros_visiveis(request.user).filter(ativo=True, usuario__isnull=True)
    return render(
        request,
        "tickets/acessos.html",
        {
            "usuarios": usuarios,
            "sem_login": sem_login,
            "pode_ver_auditoria": eh_admin(request.user) or eh_gerencia(request.user),
        },
    )


@login_required
@require_POST
def acesso_resetar(request: HttpRequest, pk: int) -> HttpResponse:
    alvo = get_object_or_404(usuarios_gerenciaveis(request.user), pk=pk)
    if not pode_resetar_senha(request.user, alvo):
        raise Http404("Página não encontrada.")
    senha = gerar_senha_temporaria()
    aplicar_senha(alvo, senha, must_change=True)
    invalidar_sessoes(alvo)
    registrar_evento(
        RegistroAcesso.Tipo.RESET,
        ator=request.user,
        alvo=alvo,
        ip=ip_de(request),
        detalhe="senha temporária",
    )
    messages.success(
        request,
        f"Senha temporária de {alvo.get_username()}: {senha}. "
        "A pessoa precisará trocar no próximo login. Anote agora — não mostramos de novo.",
    )
    return redirect("acessos")


@login_required
@require_POST
def acesso_gerar_parceiro(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    senha = gerar_senha_temporaria()
    try:
        user, senha_clara, _criado = garantir_conta_parceiro(
            parceiro, senha=senha, must_change=True
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("parceiro_editar", pk=parceiro.pk)
    invalidar_sessoes(user)
    registrar_evento(
        RegistroAcesso.Tipo.RESET,
        ator=request.user,
        alvo=user,
        ip=ip_de(request),
        detalhe=f"PDV {parceiro.codigo_pdv}",
    )
    messages.success(
        request,
        f"Login do PDV {parceiro.codigo_pdv} (usuário = código). "
        f"Senha temporária: {senha_clara}. O parceiro troca no primeiro acesso.",
    )
    return redirect("parceiro_editar", pk=parceiro.pk)


@login_required
def acessos_auditoria(request: HttpRequest) -> HttpResponse:
    if not (eh_admin(request.user) or eh_gerencia(request.user)):
        raise Http404("Página não encontrada.")
    qs = RegistroAcesso.objects.select_related("ator", "alvo")[:200]
    if eh_gerencia(request.user) and not eh_admin(request.user):
        ids = [u.pk for u in usuarios_gerenciaveis(request.user)]
        qs = RegistroAcesso.objects.select_related("ator", "alvo").filter(
            alvo_id__in=ids
        )[:200]
    return render(request, "tickets/acessos_auditoria.html", {"registros": qs})


@login_required
@require_POST
def logout_todas_sessoes(request: HttpRequest) -> HttpResponse:
    invalidar_sessoes(request.user, manter_key=request.session.session_key)
    messages.success(request, "As outras sessões foram encerradas.")
    if parceiro_de(request.user):
        return redirect("meu_perfil")
    return redirect("meu_perfil")
