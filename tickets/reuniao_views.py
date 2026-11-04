from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from gestao.messaging.syncwa import syncwa_configurado

from .acesso import especialista_required
from .models import ConviteReuniao
from .reuniao import (
    ConviteReuniaoForm,
    enviar_convite,
    formatar_telefone,
    telefone_do_especialista,
    texto_erro_para_usuario,
)


@especialista_required
@require_http_methods(["GET", "POST"])
def reunioes(request: HttpRequest) -> HttpResponse:
    jid = telefone_do_especialista(request.user)
    whatsapp_ok = syncwa_configurado()
    form = ConviteReuniaoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if not jid:
            messages.error(
                request,
                "Cadastre o WhatsApp no seu perfil para receber o link.",
            )
        else:
            convite = enviar_convite(
                user=request.user,
                assunto=form.cleaned_data["assunto"],
                inicio=form.inicio(),
                link=form.cleaned_data["link"],
            )
            if convite.status == ConviteReuniao.Status.ENVIADO:
                messages.success(request, "Link enviado para o seu WhatsApp.")
                return redirect("reunioes")
            messages.error(request, texto_erro_para_usuario(convite.erro))

    historico = ConviteReuniao.objects.filter(especialista=request.user)[:12]
    return render(
        request,
        "tickets/reunioes.html",
        {
            "form": form,
            "historico": historico,
            "telefone": formatar_telefone(jid),
            "tem_telefone": bool(jid),
            "whatsapp_ok": whatsapp_ok,
            "pode_enviar": bool(jid) and whatsapp_ok,
        },
    )
