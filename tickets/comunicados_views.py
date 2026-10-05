from __future__ import annotations

import mimetypes
from pathlib import PurePath

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .acesso import destino_pos_login, equipe_required
from .comunicados import (
    confirmar_comunicado,
    contar_nao_lidos,
    deve_confirmar_comunicado,
    enviar_comunicado_whatsapp,
    notificar_demanda_comunicado,
    pode_baixar_anexo,
    proximo_pendente,
    qs_comunicados_com_leitura,
    qs_comunicados_visiveis,
)
from .comunicados_forms import ComunicadoForm
from .models import Comunicado, ComunicadoAnexo


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
            "anexos": list(pendente.anexos.all()),
        },
    )


@login_required
@require_GET
def comunicados_lista(request: HttpRequest) -> HttpResponse:
    if deve_confirmar_comunicado(request.user):
        return redirect("comunicado_pendente")
    filtro = (request.GET.get("filtro") or "todos").strip()
    qs = (
        qs_comunicados_com_leitura(request.user)
        .annotate(qtd_anexos=Count("anexos"))
        .order_by("lido", "-publicado_em", "-id")
    )
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
        {
            "comunicado": comunicado,
            "leitura": leitura,
            "anexos": list(comunicado.anexos.all()),
        },
    )


@equipe_required
@require_GET
def comunicados_gerir(request: HttpRequest) -> HttpResponse:
    qs = Comunicado.objects.annotate(
        qtd_leituras=Count("leituras"),
        qtd_anexos=Count("anexos"),
    ).order_by("-publicado_em", "-criado_em")
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
    destinos = _destinos_whatsapp(request.user)
    grupos, grupos_erro = _grupos_whatsapp(request)
    if request.method == "POST":
        form = ComunicadoForm(
            request.POST,
            request.FILES,
            instance=comunicado,
            destinos=destinos,
            grupos_ao_vivo=grupos,
        )
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.criado_por_id is None:
                obj.criado_por = request.user
            obj.save()
            for arquivo in form.cleaned_data.get("anexos") or []:
                ComunicadoAnexo.objects.create(
                    comunicado=obj,
                    arquivo=arquivo,
                    nome_original=(arquivo.name or "")[:255],
                    enviado_por=request.user,
                )
            _remover_anexos(obj, request.POST.getlist("remover_anexo"))
            messages.success(request, "Comunicado salvo.")
            if form.cleaned_data.get("enviar_whatsapp"):
                ok, aviso = enviar_comunicado_whatsapp(
                    obj,
                    jid=form.cleaned_data.get("whatsapp_jid") or "",
                    nome=form.cleaned_data.get("whatsapp_nome") or "",
                    user=request.user,
                    request=request,
                )
                if ok:
                    messages.success(request, aviso)
                else:
                    messages.error(
                        request,
                        f"O comunicado foi salvo, mas o WhatsApp não saiu: {aviso}",
                    )
            return redirect("comunicados_gerir")
    else:
        form = ComunicadoForm(
            instance=comunicado,
            destinos=destinos,
            grupos_ao_vivo=grupos,
        )
    return render(
        request,
        "tickets/comunicados/gerir_form.html",
        {
            "form": form,
            "comunicado": comunicado,
            "anexos": list(comunicado.anexos.all()) if comunicado else [],
            "grupos_erro": grupos_erro,
            "grupos_qtd": len(grupos),
            "titulo_pagina": "Editar comunicado" if comunicado else "Novo comunicado",
        },
    )


@login_required
@require_GET
def comunicado_anexo_baixar(request: HttpRequest, pk: int) -> FileResponse:
    anexo = get_object_or_404(ComunicadoAnexo.objects.select_related("comunicado"), pk=pk)
    if not pode_baixar_anexo(request.user, anexo.comunicado):
        raise Http404("Anexo não encontrado.")
    if not anexo.arquivo:
        raise Http404("Arquivo indisponível.")
    nome = PurePath(anexo.nome_exibicao).name or "arquivo"
    ctype = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    inline = request.GET.get("ver") == "1" and anexo.eh_imagem
    try:
        handle = anexo.arquivo.open("rb")
    except Exception as exc:
        raise Http404("Arquivo indisponível.") from exc
    return FileResponse(
        handle,
        as_attachment=not inline,
        filename=nome,
        content_type=ctype,
    )


def _destinos_whatsapp(user):
    from gestao.destinatarios_especialista import qs_destinatarios_da_lista

    return list(
        qs_destinatarios_da_lista(user).filter(ativo=True).order_by("tipo", "nome")
    )


def _grupos_whatsapp(request: HttpRequest) -> tuple[list, str]:
    destino = ""
    if request.method == "POST":
        destino = (request.POST.get("whatsapp_destino") or "").strip()
    if request.GET.get("grupos") != "1" and not destino.startswith("live:"):
        return [], ""
    from gestao.messaging.instancia import instancia_para_envio
    from gestao.messaging.syncwa import SyncWAError, listar_grupos, syncwa_configurado

    if not syncwa_configurado():
        return [], "WhatsApp não está configurado. Não dá para listar os grupos."
    try:
        instancia = instancia_para_envio(request.user)
    except SyncWAError as exc:
        return [], str(exc)
    resposta = listar_grupos(instance=instancia)
    if not resposta.get("ok"):
        return [], resposta.get("error") or "Não foi possível listar os grupos."
    grupos = sorted(
        resposta.get("groups") or [],
        key=lambda item: str(item.get("name") or "").casefold(),
    )
    return grupos, ""


def _remover_anexos(comunicado: Comunicado, brutos: list[str]) -> None:
    ids: list[int] = []
    for bruto in brutos:
        try:
            ids.append(int(bruto))
        except (TypeError, ValueError):
            continue
    if not ids:
        return
    for anexo in comunicado.anexos.filter(pk__in=ids):
        anexo.delete()
