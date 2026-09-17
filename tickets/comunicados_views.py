from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .acesso import destino_pos_login, equipe_required
from .comunicados import (
    confirmar_comunicado,
    contar_nao_lidos,
    deve_confirmar_comunicado,
    notificar_demanda_comunicado,
    proximo_pendente,
    qs_comunicados_com_leitura,
    qs_comunicados_visiveis,
)
from .comunicados_forms import ComunicadoForm
from .models import Comunicado


@login_required
@require_http_methods(["GET", "POST"])
def comunicado_pendente(request: HttpRequest) -> HttpResponse:
    pendente = proximo_pendente(request.user)
    if request.method == "POST":
        if not pendente:
            return redirect(destino_pos_login(request.user))
        pk_enviado = request.POST.get("comunicado_id")
        acao = (request.POST.get("acao") or "").strip()
        if str(pendente.pk) != str(pk_enviado) or acao not in {"entendi", "nao_entendi"}:
            messages.error(request, "Confirme o comunicado exibido para continuar.")
            return redirect("comunicado_pendente")
        with transaction.atomic():
            leitura = confirmar_comunicado(
                request.user,
                pendente,
                entendeu=acao == "entendi",
                request=request,
            )
        if leitura.ticket_id:
            notificar_demanda_comunicado(leitura.ticket, ator=request.user)
            messages.success(
                request,
                (
                    f"Demanda {leitura.ticket.protocolo} aberta para o especialista "
                    f"esclarecer o comunicado."
                ),
            )
        elif acao == "nao_entendi":
            messages.info(
                request,
                "Registramos que você não entendeu este comunicado.",
            )
        else:
            messages.success(request, "Comunicado confirmado.")
        if deve_confirmar_comunicado(request.user):
            return redirect("comunicado_pendente")
        return redirect(destino_pos_login(request.user))

    if not pendente:
        return redirect(destino_pos_login(request.user))
    restantes = contar_nao_lidos(request.user)
    return render(
        request,
        "tickets/comunicados/pendente.html",
        {
            "comunicado": pendente,
            "restantes": restantes,
        },
    )


@login_required
@require_GET
def comunicados_lista(request: HttpRequest) -> HttpResponse:
    if deve_confirmar_comunicado(request.user):
        return redirect("comunicado_pendente")
    filtro = (request.GET.get("filtro") or "todos").strip()
    qs = qs_comunicados_com_leitura(request.user).order_by("lido", "-publicado_em", "-id")
    if filtro == "nao_lidos":
        qs = qs.filter(lido=False)
    elif filtro == "lidos":
        qs = qs.filter(lido=True)
    else:
        filtro = "todos"
    return render(
        request,
        "tickets/comunicados/lista.html",
        {
            "comunicados": qs,
            "filtro": filtro,
            "nao_lidos": contar_nao_lidos(request.user),
        },
    )


@login_required
@require_GET
def comunicado_detalhe(request: HttpRequest, pk: int) -> HttpResponse:
    if deve_confirmar_comunicado(request.user):
        return redirect("comunicado_pendente")
    comunicado = get_object_or_404(qs_comunicados_visiveis(request.user), pk=pk)
    leitura = comunicado.leituras.filter(usuario=request.user).first()
    return render(
        request,
        "tickets/comunicados/detalhe.html",
        {"comunicado": comunicado, "leitura": leitura},
    )


@equipe_required
@require_GET
def comunicados_gerir(request: HttpRequest) -> HttpResponse:
    qs = Comunicado.objects.annotate(qtd_leituras=Count("leituras")).order_by(
        "-publicado_em", "-criado_em"
    )
    return render(
        request,
        "tickets/comunicados/gerir_lista.html",
        {"comunicados": qs},
    )


@equipe_required
@require_http_methods(["GET", "POST"])
def comunicado_gerir_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    comunicado = None
    if pk is not None:
        comunicado = get_object_or_404(Comunicado, pk=pk)
    if request.method == "POST":
        form = ComunicadoForm(request.POST, instance=comunicado)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.criado_por_id is None:
                obj.criado_por = request.user
            obj.save()
            messages.success(request, "Comunicado salvo.")
            return redirect("comunicados_gerir")
    else:
        form = ComunicadoForm(instance=comunicado)
    return render(
        request,
        "tickets/comunicados/gerir_form.html",
        {
            "form": form,
            "comunicado": comunicado,
            "titulo_pagina": "Editar comunicado" if comunicado else "Novo comunicado",
        },
    )
