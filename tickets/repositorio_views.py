from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .acesso import eh_gestor, tem_acesso_interno
from .models import ProcessoAnexo, ProcessoLink, ProcessoRepositorio
from .repositorio_forms import ProcessoAnexoForm, ProcessoLinkForm, ProcessoRepositorioForm
from .views import _portal_sessao


def _qs_publicos(request: HttpRequest):
    qs = ProcessoRepositorio.objects.filter(ativo=True, publico=True)
    parceiro, _contato = _portal_sessao(request)
    if parceiro:
        return qs
    return qs


def _pode_gerir(user) -> bool:
    return tem_acesso_interno(user)


@require_GET
def repositorio_lista(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    categoria = (request.GET.get("categoria") or "").strip()
    qs = _qs_publicos(request)
    if q:
        qs = qs.filter(
            Q(titulo__icontains=q)
            | Q(resumo__icontains=q)
            | Q(tags__icontains=q)
            | Q(finalidade__icontains=q)
        )
    if categoria:
        qs = qs.filter(categoria=categoria)
    return render(
        request,
        "tickets/repositorio/lista.html",
        {
            "processos": qs,
            "q": q,
            "categoria": categoria,
            "categorias": ProcessoRepositorio.Categoria.choices,
            "pode_gerir": _pode_gerir(request.user),
        },
    )


@require_GET
def repositorio_detalhe(request: HttpRequest, slug: str) -> HttpResponse:
    parceiro, contato = _portal_sessao(request)
    processo = get_object_or_404(ProcessoRepositorio, slug=slug, ativo=True, publico=True)
    email_especialista = ""
    if parceiro and parceiro.especialista:
        email_especialista = parceiro.especialista.email or ""

    mailto_dest = processo.email_destino
    mailto_cc = []
    if processo.email_cc_especialista and email_especialista:
        mailto_cc.append(email_especialista)
    if processo.email_cc_extra:
        mailto_cc.extend(
            e.strip() for e in processo.email_cc_extra.replace(";", ",").split(",") if e.strip()
        )

    passos = [p.strip() for p in (processo.passos or "").splitlines() if p.strip()]

    return render(
        request,
        "tickets/repositorio/detalhe.html",
        {
            "processo": processo,
            "passos": passos,
            "parceiro": parceiro,
            "contato": contato,
            "email_especialista": email_especialista,
            "mailto_dest": mailto_dest,
            "mailto_cc": mailto_cc,
            "pode_gerir": _pode_gerir(request.user),
        },
    )


@login_required
@require_GET
def repositorio_gerir_lista(request: HttpRequest) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    return render(
        request,
        "tickets/repositorio/gerir_lista.html",
        {
            "processos": ProcessoRepositorio.objects.all(),
            "eh_gestor": eh_gestor(request.user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def repositorio_gerir_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    processo = get_object_or_404(ProcessoRepositorio, pk=pk) if pk else None
    if request.method == "POST":
        form = ProcessoRepositorioForm(request.POST, instance=processo)
        if form.is_valid():
            obj = form.save(commit=False)
            if not processo:
                obj.criado_por = request.user
            obj.save()
            messages.success(request, f"Processo «{obj.titulo}» salvo.")
            return redirect("repositorio_gerir_editar", pk=obj.pk)
    else:
        form = ProcessoRepositorioForm(instance=processo)
    return render(
        request,
        "tickets/repositorio/gerir_form.html",
        {
            "form": form,
            "processo": processo,
            "titulo_pagina": "Editar processo" if processo else "Novo processo",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def repositorio_anexo_form(
    request: HttpRequest, processo_pk: int, pk: int | None = None
) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    processo = get_object_or_404(ProcessoRepositorio, pk=processo_pk)
    anexo = get_object_or_404(ProcessoAnexo, pk=pk, processo=processo) if pk else None
    if request.method == "POST":
        form = ProcessoAnexoForm(request.POST, request.FILES, instance=anexo)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.processo = processo
            obj.save()
            messages.success(request, "Anexo salvo.")
            return redirect("repositorio_gerir_editar", pk=processo.pk)
    else:
        form = ProcessoAnexoForm(instance=anexo)
    return render(
        request,
        "tickets/repositorio/anexo_form.html",
        {"form": form, "processo": processo, "anexo": anexo},
    )


@login_required
@require_http_methods(["POST"])
def repositorio_anexo_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    anexo = get_object_or_404(ProcessoAnexo, pk=pk)
    processo_pk = anexo.processo_id
    anexo.delete()
    messages.success(request, "Anexo removido.")
    return redirect("repositorio_gerir_editar", pk=processo_pk)


@login_required
@require_http_methods(["GET", "POST"])
def repositorio_link_form(
    request: HttpRequest, processo_pk: int, pk: int | None = None
) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    processo = get_object_or_404(ProcessoRepositorio, pk=processo_pk)
    link = get_object_or_404(ProcessoLink, pk=pk, processo=processo) if pk else None
    if request.method == "POST":
        form = ProcessoLinkForm(request.POST, instance=link)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.processo = processo
            obj.save()
            messages.success(request, "Link salvo.")
            return redirect("repositorio_gerir_editar", pk=processo.pk)
    else:
        form = ProcessoLinkForm(instance=link)
    return render(
        request,
        "tickets/repositorio/link_form.html",
        {"form": form, "processo": processo, "link": link},
    )


@login_required
@require_http_methods(["POST"])
def repositorio_link_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    if not _pode_gerir(request.user):
        raise Http404
    link = get_object_or_404(ProcessoLink, pk=pk)
    processo_pk = link.processo_id
    link.delete()
    messages.success(request, "Link removido.")
    return redirect("repositorio_gerir_editar", pk=processo_pk)
