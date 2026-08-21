from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .acesso import (
    eh_gestor,
    gestor_required,
    parceiros_visiveis,
    qs_equipe,
    ticket_para_usuario,
    tickets_visiveis,
)
from .demanda_campos import (
    LABELS_POR_TIPO,
    LABELS_SIMPLES,
    catalogo_campos_resposta,
    contexto_demanda_para_resposta,
    garantir_config_resposta_padrao,
    montar_abas_tratamento,
    schema_para_js,
    schema_tipo,
)
from .forms import (
    AnexoForm,
    ContatoParceiroForm,
    EspecialistaForm,
    FilaFiltroForm,
    LoginForm,
    MascaraForm,
    MensagemForm,
    ParceiroForm,
    StaffPerfilForm,
    TicketCreateForm,
    TicketPublicCreateForm,
    TicketTreatForm,
)
from .models import (
    Anexo,
    ConfigRespostaTipo,
    ContatoParceiro,
    Encaminhamento,
    Mascara,
    Mensagem,
    Parceiro,
    StatusTicket,
    Ticket,
    TipoDemanda,
)
from .services import render_mascara


class StaffLoginView(LoginView):
    template_name = "tickets/login.html"
    authentication_form = LoginForm


class StaffLogoutView(LogoutView):
    next_page = "login"


@login_required
def meu_perfil(request: HttpRequest) -> HttpResponse:
    form = StaffPerfilForm(instance=request.user)
    if request.method == "POST":
        form = StaffPerfilForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Perfil atualizado.")
            return redirect("meu_perfil")
    return render(
        request,
        "tickets/perfil.html",
        {"form": form},
    )


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("fila")
    return redirect("abrir_demanda")


@login_required
def fila(request: HttpRequest) -> HttpResponse:
    parceiros_qs = parceiros_visiveis(request.user).filter(ativo=True)
    especialistas_qs = qs_equipe()
    form = FilaFiltroForm(
        request.GET or None,
        parceiros_qs=parceiros_qs,
        especialistas_qs=especialistas_qs,
    )
    if not eh_gestor(request.user):
        form.fields.pop("especialista", None)

    qs = tickets_visiveis(request.user)

    if form.is_valid():
        q = form.cleaned_data.get("q") or ""
        if q:
            qs = qs.filter(
                Q(protocolo__icontains=q)
                | Q(pedido__icontains=q)
                | Q(documento_cliente__icontains=q)
                | Q(parceiro__nome__icontains=q)
                | Q(descricao__icontains=q)
            )
        if form.cleaned_data.get("status"):
            qs = qs.filter(status=form.cleaned_data["status"])
        if form.cleaned_data.get("tipo"):
            qs = qs.filter(tipo=form.cleaned_data["tipo"])
        if form.cleaned_data.get("parceiro"):
            qs = qs.filter(parceiro=form.cleaned_data["parceiro"])
        if eh_gestor(request.user) and form.cleaned_data.get("especialista"):
            qs = qs.filter(parceiro__especialista=form.cleaned_data["especialista"])

    abertos = qs.exclude(
        status__in=[StatusTicket.RESOLVIDO, StatusTicket.FECHADO, StatusTicket.CANCELADO]
    )
    filtros_ativos = any(
        (request.GET.get(k) or "").strip()
        for k in ("q", "status", "tipo", "parceiro", "especialista")
    )
    return render(
        request,
        "tickets/fila.html",
        {
            "form": form,
            "tickets": qs[:200],
            "abertos_count": abertos.count(),
            "mostrar_filtro_especialista": eh_gestor(request.user),
            "filtros_ativos": filtros_ativos,
        },
    )


@login_required
def ticket_criar(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = TicketCreateForm(request.POST, request.FILES)
        form.fields["parceiro"].queryset = parceiros_visiveis(request.user).filter(ativo=True)
        if form.is_valid():
            ticket = form.save(commit=False)
            if request.user.is_authenticated:
                ticket.atendente = request.user
            ticket.save()
            Mensagem.objects.create(
                ticket=ticket,
                autor=request.user,
                autor_nome=request.user.get_username(),
                corpo=ticket.descricao or f"Demanda aberta: {ticket.get_tipo_display()}",
            )
            _salvar_anexos(request, ticket)
            messages.success(request, f"Ticket {ticket.protocolo} criado.")
            return redirect("ticket_detalhe", protocolo=ticket.protocolo)
    else:
        form = TicketCreateForm()
        form.fields["parceiro"].queryset = parceiros_visiveis(request.user).filter(ativo=True)
    return render(
        request,
        "tickets/ticket_form.html",
        {
            "form": form,
            "titulo": "Nova demanda",
            "demanda_schema": schema_para_js(),
        },
    )


def abrir_demanda(request: HttpRequest) -> HttpResponse:
    """Portal: PDV → contato autorizado → formulário."""
    parceiros = Parceiro.objects.filter(ativo=True).prefetch_related("contatos")
    passo = request.GET.get("passo") or request.POST.get("passo") or "parceiro"
    parceiro = None
    contatos = ContatoParceiro.objects.none()

    parceiro_id = request.POST.get("parceiro") or request.session.get("parceiro_id")
    if parceiro_id:
        parceiro = Parceiro.objects.filter(pk=parceiro_id, ativo=True).first()
        if parceiro:
            contatos = parceiro.contatos.filter(ativo=True)

    if request.method == "POST":
        if passo == "parceiro":
            parceiro = get_object_or_404(Parceiro, pk=request.POST.get("parceiro"), ativo=True)
            token_pdv = (request.POST.get("token_pdv") or "").strip()
            if parceiro.token_acesso and parceiro.token_acesso != token_pdv:
                messages.error(request, "Token do PDV inválido.")
                return redirect("abrir_demanda")
            request.session["parceiro_id"] = parceiro.id
            request.session.pop("contato_id", None)
            if not parceiro.contatos.filter(ativo=True).exists():
                messages.error(
                    request,
                    "Este PDV ainda não tem contatos cadastrados. Peça ao gestor NIO para cadastrar.",
                )
                return redirect("abrir_demanda")
            return redirect(f"{reverse('abrir_demanda')}?passo=contato")

        if passo == "contato":
            if not parceiro:
                return redirect("abrir_demanda")
            contato = get_object_or_404(
                ContatoParceiro, pk=request.POST.get("contato"), parceiro=parceiro, ativo=True
            )
            request.session["contato_id"] = contato.id
            return redirect("portal_parceiro")

    return render(
        request,
        "tickets/parceiro_gate.html",
        {
            "parceiros": parceiros,
            "parceiro": parceiro if passo == "contato" else None,
            "contatos": contatos,
            "passo": passo if (passo == "contato" and parceiro) else "parceiro",
        },
    )


def portal_parceiro(request: HttpRequest) -> HttpResponse:
    """Hub do contato identificado: abrir nova ou ver histórico do PDV."""
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return redirect("abrir_demanda")
    recentes = (
        Ticket.objects.filter(parceiro=parceiro)
        .select_related("parceiro", "contato")
        .order_by("-criado_em")[:5]
    )
    return render(
        request,
        "tickets/portal_parceiro.html",
        {
            "parceiro": parceiro,
            "contato": contato,
            "recentes": recentes,
        },
    )


def minhas_demandas(request: HttpRequest) -> HttpResponse:
    """Lista todas as demandas do PDV (qualquer contato com token do parceiro)."""
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        messages.info(
            request,
            "Identifique o PDV e o seu contato para ver as demandas do parceiro.",
        )
        return redirect("abrir_demanda")
    tickets = (
        Ticket.objects.filter(parceiro=parceiro)
        .select_related("parceiro", "contato")
        .order_by("-criado_em")
    )
    return render(
        request,
        "tickets/minhas_demandas.html",
        {
            "parceiro": parceiro,
            "contato": contato,
            "tickets": tickets,
        },
    )


def portal_sair(request: HttpRequest) -> HttpResponse:
    request.session.pop("parceiro_id", None)
    request.session.pop("contato_id", None)
    messages.success(request, "Sessão do PDV encerrada.")
    return redirect("abrir_demanda")


def _portal_sessao(request: HttpRequest):
    parceiro_id = request.session.get("parceiro_id")
    contato_id = request.session.get("contato_id")
    if not parceiro_id or not contato_id:
        return None, None
    parceiro = Parceiro.objects.filter(pk=parceiro_id, ativo=True).first()
    if not parceiro:
        return None, None
    contato = ContatoParceiro.objects.filter(
        pk=contato_id, parceiro=parceiro, ativo=True
    ).first()
    return parceiro, contato


def abrir_demanda_form(request: HttpRequest) -> HttpResponse:
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return redirect("abrir_demanda")

    if request.method == "POST":
        form = TicketPublicCreateForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.parceiro = parceiro
            ticket.contato = contato
            if not ticket.solicitante_nome:
                ticket.solicitante_nome = contato.nome
            ticket.save()
            Mensagem.objects.create(
                ticket=ticket,
                autor_nome=contato.nome,
                corpo=ticket.descricao or f"Demanda aberta: {ticket.get_tipo_display()}",
            )
            _salvar_anexos(request, ticket)
            messages.success(
                request,
                f"Demanda registrada! Protocolo {ticket.protocolo}. Guarde este número.",
            )
            return redirect("consulta_protocolo", protocolo=ticket.protocolo)
    else:
        form = TicketPublicCreateForm(
            initial={"solicitante_nome": contato.nome}
        )
    return render(
        request,
        "tickets/ticket_form_public.html",
        {
            "form": form,
            "parceiro": parceiro,
            "contato": contato,
            "demanda_schema": schema_para_js(),
        },
    )


def consulta_busca(request: HttpRequest) -> HttpResponse:
    """Parceiro informa o protocolo para ver STATUS / RETORNO."""
    if request.method == "POST":
        protocolo = (request.POST.get("protocolo") or "").strip().upper()
        if not protocolo:
            messages.error(request, "Informe o número do protocolo.")
            return redirect("consulta_busca")
        if not Ticket.objects.filter(protocolo=protocolo).exists():
            messages.error(request, f"Protocolo {protocolo} não encontrado.")
            return redirect("consulta_busca")
        return redirect("consulta_protocolo", protocolo=protocolo)

    parceiro, contato = _portal_sessao(request)
    minhas = []
    if parceiro:
        minhas = (
            Ticket.objects.filter(parceiro=parceiro)
            .select_related("parceiro", "contato")
            .order_by("-criado_em")[:10]
        )
    return render(
        request,
        "tickets/consulta_busca.html",
        {"parceiro": parceiro, "contato": contato, "minhas": minhas},
    )


def consulta_protocolo(request: HttpRequest, protocolo: str) -> HttpResponse:
    ticket = get_object_or_404(
        Ticket.objects.select_related("parceiro"), protocolo=protocolo.upper()
    )
    msgs = ticket.mensagens.filter(interno=False)
    return render(
        request,
        "tickets/consulta.html",
        {"ticket": ticket, "mensagens": msgs},
    )


def _eh_ajax(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _ctx_modal_resposta(request: HttpRequest, ticket: Ticket, treat_form: TicketTreatForm) -> dict:
    proximo = request.POST.get("next") or request.GET.get("next") or ""
    mascaras = [
        m for m in Mascara.objects.filter(ativo=True) if m.aplica_para(ticket.tipo)
    ]
    abas = montar_abas_tratamento(treat_form)
    erros = treat_form.errors
    for aba in abas:
        aba["tem_erro"] = any(nome in erros for nome in aba["field_names"])
    return {
        "ticket": ticket,
        "treat_form": treat_form,
        "abas": abas,
        "contexto_demanda": contexto_demanda_para_resposta(ticket),
        "anexos": list(ticket.anexos.all()),
        "historico_respostas": list(ticket.mensagens.order_by("-criado_em")),
        "mascaras_prontas": [
            {"mascara": m, "conteudo": render_mascara(m, ticket)} for m in mascaras
        ],
        "resposta_field_names": [c["name"] for c in treat_form.campos_resposta_defs],
        "next": proximo,
        "tempo_ja_registrado": ticket.tempo_retorno_segundos is not None,
        "iniciado_iso": ticket.resposta_iniciada_em.isoformat()
        if ticket.resposta_iniciada_em
        else "",
    }


def _aplicar_tratamento(request: HttpRequest, ticket: Ticket, treat_form: TicketTreatForm) -> Ticket:
    t = treat_form.save(commit=False)
    t.registrar_tempo_resposta()
    if not t.atendente:
        t.atendente = request.user
    if not t.primeiro_atendimento_em:
        t.primeiro_atendimento_em = timezone.now()
    t.save()
    if t.resposta_publica:
        Mensagem.objects.create(
            ticket=t,
            autor=request.user,
            autor_nome=request.user.get_username(),
            corpo=t.resposta_publica,
            interno=False,
        )
    return t


def _aplicar_novo_tipo(ticket: Ticket, novo_tipo: str) -> tuple[bool, str]:
    novo = (novo_tipo or "").strip()
    if novo not in TipoDemanda.values:
        return False, "Tipo inválido."
    if ticket.tipo == novo:
        return True, "Tipo já estava selecionado."
    antigo = ticket.get_tipo_display()
    ticket.tipo = novo
    ticket.save(update_fields=["tipo", "atualizado_em"])
    return True, f"Tipo alterado de “{antigo}” para “{ticket.get_tipo_display()}”."


@login_required
def ticket_responder(request: HttpRequest, protocolo: str) -> HttpResponse:
    ticket = ticket_para_usuario(request.user, protocolo)
    proximo = request.POST.get("next") or request.GET.get("next") or reverse("fila")

    if request.method == "GET" or request.POST.get("action") == "abrir":
        ticket.iniciar_tratamento(request.user)
        ticket.refresh_from_db()
        treat_form = TicketTreatForm(instance=ticket)
        ctx = _ctx_modal_resposta(request, ticket, treat_form)
        if _eh_ajax(request) or request.GET.get("modal") == "1":
            return render(request, "tickets/_modal_responder.html", ctx)
        return redirect(f"{reverse('ticket_detalhe', args=[ticket.protocolo])}?responder=1")

    if request.POST.get("action") == "atualizar_tipo":
        ok, texto = _aplicar_novo_tipo(ticket, request.POST.get("tipo") or "")
        ticket.refresh_from_db()
        treat_form = TicketTreatForm(instance=ticket)
        ctx = _ctx_modal_resposta(request, ticket, treat_form)
        ctx["aviso_tipo"] = texto
        ctx["aviso_tipo_ok"] = ok
        status = 200 if ok else 400
        if _eh_ajax(request):
            return render(request, "tickets/_modal_responder.html", ctx, status=status)
        if ok:
            messages.success(request, texto)
        else:
            messages.error(request, texto)
        return redirect(f"{reverse('ticket_detalhe', args=[ticket.protocolo])}?responder=1")

    treat_form = TicketTreatForm(request.POST, instance=ticket)
    if treat_form.is_valid():
        _aplicar_tratamento(request, ticket, treat_form)
        messages.success(request, "Resposta salva.")
        if _eh_ajax(request):
            return JsonResponse(
                {
                    "ok": True,
                    "redirect": proximo or reverse("fila"),
                    "message": "Resposta salva.",
                }
            )
        return redirect(proximo)

    ctx = _ctx_modal_resposta(request, ticket, treat_form)
    if _eh_ajax(request):
        accept = (request.headers.get("Accept") or "").lower()
        if "application/json" in accept:
            msgs = []
            for field, errs in treat_form.errors.items():
                label = field
                if field in treat_form.fields:
                    label = str(treat_form.fields[field].label or field)
                elif field == "__all__":
                    label = "Formulário"
                for err in errs:
                    msgs.append(f"{label}: {err}")
            return JsonResponse(
                {
                    "ok": False,
                    "error": " ".join(msgs) or "Não foi possível salvar. Verifique os campos.",
                    "errors": treat_form.errors.get_json_data(),
                },
                status=400,
            )
        return render(request, "tickets/_modal_responder.html", ctx, status=400)
    messages.error(request, "Não foi possível salvar. Verifique os campos.")
    return redirect("ticket_detalhe", protocolo=ticket.protocolo)


@login_required
def ticket_detalhe(request: HttpRequest, protocolo: str) -> HttpResponse:
    ticket = ticket_para_usuario(request.user, protocolo)
    if request.GET.get("responder") == "1":
        ticket.iniciar_tratamento(request.user)
        ticket.refresh_from_db()
    treat_form = TicketTreatForm(instance=ticket)
    msg_form = MensagemForm()
    anexo_form = AnexoForm()
    mascaras = [
        m for m in Mascara.objects.filter(ativo=True) if m.aplica_para(ticket.tipo)
    ]
    mascaras_prontas = [
        {"mascara": m, "conteudo": render_mascara(m, ticket)} for m in mascaras
    ]

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "tratar":
            if request.POST.get("so_atualizar_tipo"):
                ok, texto = _aplicar_novo_tipo(ticket, request.POST.get("tipo") or "")
                if ok:
                    messages.success(request, texto)
                else:
                    messages.error(request, texto)
                return redirect("ticket_detalhe", protocolo=ticket.protocolo)

            treat_form = TicketTreatForm(request.POST, instance=ticket)
            if treat_form.is_valid():
                _aplicar_tratamento(request, ticket, treat_form)
                messages.success(request, "Resposta salva.")
                return redirect("ticket_detalhe", protocolo=ticket.protocolo)
        elif action == "mensagem":
            msg_form = MensagemForm(request.POST)
            if msg_form.is_valid():
                msg = msg_form.save(commit=False)
                msg.ticket = ticket
                msg.autor = request.user
                msg.autor_nome = request.user.get_username()
                msg.save()
                if not ticket.primeiro_atendimento_em:
                    ticket.primeiro_atendimento_em = timezone.now()
                    if ticket.status == StatusTicket.NOVO:
                        ticket.status = StatusTicket.EM_ANALISE
                    ticket.atendente = ticket.atendente or request.user
                    ticket.save(update_fields=[
                        "primeiro_atendimento_em",
                        "status",
                        "atendente",
                        "atualizado_em",
                    ])
                messages.success(request, "Mensagem registrada.")
                return redirect("ticket_detalhe", protocolo=ticket.protocolo)
        elif action == "anexo":
            anexo_form = AnexoForm(request.POST, request.FILES)
            if anexo_form.is_valid():
                anexo = anexo_form.save(commit=False)
                anexo.ticket = ticket
                anexo.enviado_por = request.user
                anexo.nome_original = request.FILES["arquivo"].name
                anexo.save()
                messages.success(request, "Anexo enviado.")
                return redirect("ticket_detalhe", protocolo=ticket.protocolo)
        elif action == "mascara":
            mascara = get_object_or_404(Mascara, pk=request.POST.get("mascara_id"), ativo=True)
            conteudo = render_mascara(mascara, ticket)
            Encaminhamento.objects.create(
                ticket=ticket,
                mascara=mascara,
                destino=mascara.destino,
                conteudo=conteudo,
                criado_por=request.user,
            )
            ticket.status = StatusTicket.ENCAMINHADO
            ticket.destino_encaminhamento = mascara.destino
            if not ticket.primeiro_atendimento_em:
                ticket.primeiro_atendimento_em = timezone.now()
            ticket.atendente = ticket.atendente or request.user
            ticket.save()
            return render(
                request,
                "tickets/mascara_resultado.html",
                {"ticket": ticket, "mascara": mascara, "conteudo": conteudo},
            )

    return render(
        request,
        "tickets/ticket_detalhe.html",
        {
            "ticket": ticket,
            "treat_form": treat_form,
            "msg_form": msg_form,
            "anexo_form": anexo_form,
            "mensagens": ticket.mensagens.select_related("autor"),
            "anexos": ticket.anexos.all(),
            "encaminhamentos": ticket.encaminhamentos.select_related("mascara"),
            "mascaras": mascaras,
            "mascaras_prontas": mascaras_prontas,
            "schema": schema_tipo(ticket.tipo),
            "labels_tipo": {**LABELS_SIMPLES, **LABELS_POR_TIPO.get(ticket.tipo, {})},
            "campos_resposta": treat_form.campos_resposta_defs,
            "resposta_field_names": [c["name"] for c in treat_form.campos_resposta_defs],
            "abrir_modal_resposta": request.GET.get("responder") == "1",
            **_ctx_modal_resposta(request, ticket, treat_form),
        },
    )


@login_required
def parceiros_lista(request: HttpRequest) -> HttpResponse:
    parceiros = (
        parceiros_visiveis(request.user)
        .select_related("especialista")
        .annotate(
            qtd_tickets=Count("tickets"),
            qtd_contatos=Count("contatos"),
        )
        .order_by("nome")
    )
    return render(
        request,
        "tickets/parceiros.html",
        {"parceiros": parceiros},
    )


@login_required
def parceiro_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    instance = get_object_or_404(parceiros_visiveis(request.user), pk=pk) if pk else None
    qtd_tickets = instance.tickets.count() if instance else 0
    contatos = instance.contatos.all() if instance else []
    contato_form = ContatoParceiroForm()
    form = ParceiroForm(instance=instance)
    if not eh_gestor(request.user):
        form.fields.pop("especialista", None)

    if request.method == "POST":
        action = request.POST.get("action") or "salvar_parceiro"
        if action == "salvar_parceiro":
            form = ParceiroForm(request.POST, instance=instance)
            if not eh_gestor(request.user):
                form.fields.pop("especialista", None)
            if form.is_valid():
                parceiro = form.save(commit=False)
                if not eh_gestor(request.user):
                    parceiro.especialista = request.user
                parceiro.save()
                messages.success(request, "Parceiro salvo.")
                return redirect("parceiro_editar", pk=parceiro.pk)
        elif action == "add_contato" and instance:
            contato_form = ContatoParceiroForm(request.POST)
            if contato_form.is_valid():
                contato = contato_form.save(commit=False)
                contato.parceiro = instance
                contato.save()
                messages.success(request, f"Contato {contato.nome} adicionado.")
                return redirect("parceiro_editar", pk=instance.pk)
        elif action == "salvar_contato" and instance:
            contato = get_object_or_404(
                ContatoParceiro, pk=request.POST.get("contato_id"), parceiro=instance
            )
            edit_form = ContatoParceiroForm(request.POST, instance=contato)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, f"Contato {contato.nome} atualizado.")
                return redirect("parceiro_editar", pk=instance.pk)
            messages.error(request, "Não foi possível salvar o contato. Verifique os campos.")

    codigo = (instance.codigo_pdv if instance else "pdv") or "pdv"
    codigo_slug = "".join(ch for ch in codigo.lower() if ch.isalnum())[:6] or "pdv"
    sugestoes_token = [
        f"nio{codigo_slug}",
        f"{codigo_slug}2026",
        "parceiro",
        "abertura",
        "demanda",
    ]
    return render(
        request,
        "tickets/parceiro_form.html",
        {
            "form": form,
            "contato_form": contato_form,
            "contatos": contatos,
            "titulo": "Editar parceiro" if instance else "Novo parceiro",
            "parceiro": instance,
            "qtd_tickets": qtd_tickets,
            "pode_excluir": bool(instance) and qtd_tickets == 0,
            "sugestoes_token": sugestoes_token,
        },
    )


@login_required
@require_POST
def contato_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    contato = get_object_or_404(
        ContatoParceiro.objects.filter(parceiro__in=parceiros_visiveis(request.user)),
        pk=pk,
    )
    contato.ativo = not contato.ativo
    contato.save(update_fields=["ativo", "atualizado_em"])
    estado = "ativado" if contato.ativo else "inativado"
    messages.success(request, f"Contato {contato.nome} {estado}.")
    return redirect("parceiro_editar", pk=contato.parceiro_id)


@login_required
@require_POST
def contato_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    contato = get_object_or_404(
        ContatoParceiro.objects.filter(parceiro__in=parceiros_visiveis(request.user)),
        pk=pk,
    )
    parceiro_id = contato.parceiro_id
    qtd = contato.tickets.count()
    if qtd > 0:
        contato.ativo = False
        contato.save(update_fields=["ativo", "atualizado_em"])
        messages.warning(
            request,
            f"Contato {contato.nome} tem {qtd} demanda(s) — foi inativado (não excluído).",
        )
    else:
        nome = contato.nome
        contato.delete()
        messages.success(request, f"Contato {nome} excluído.")
    return redirect("parceiro_editar", pk=parceiro_id)


@login_required
@require_POST
def contato_gerar_token(request: HttpRequest, pk: int) -> HttpResponse:
    import secrets

    contato = get_object_or_404(
        ContatoParceiro.objects.filter(parceiro__in=parceiros_visiveis(request.user)),
        pk=pk,
    )
    contato.token_acesso = secrets.token_urlsafe(6)
    contato.save(update_fields=["token_acesso", "atualizado_em"])
    messages.success(request, f"Token aleatório de {contato.nome}: {contato.token_acesso}")
    return redirect("parceiro_editar", pk=contato.parceiro_id)


@login_required
@require_POST
def parceiro_inativar(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    parceiro.ativo = False
    parceiro.save(update_fields=["ativo", "atualizado_em"])
    messages.success(
        request,
        f"Parceiro {parceiro.codigo_pdv} — {parceiro.nome} inativado. "
        "Demandas antigas permanecem; novas aberturas ficam bloqueadas.",
    )
    return redirect("parceiros")


@login_required
@require_POST
def parceiro_reativar(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    parceiro.ativo = True
    parceiro.save(update_fields=["ativo", "atualizado_em"])
    messages.success(request, f"Parceiro {parceiro.codigo_pdv} — {parceiro.nome} reativado.")
    return redirect("parceiros")


@login_required
@require_POST
def parceiro_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    qtd = parceiro.tickets.count()
    if qtd > 0:
        messages.error(
            request,
            f"Não é possível excluir: há {qtd} demanda(s) neste PDV. "
            "Use Inativar para tirar o parceiro do portal.",
        )
        return redirect("parceiro_editar", pk=parceiro.pk)
    nome = f"{parceiro.codigo_pdv} — {parceiro.nome}"
    parceiro.delete()
    messages.success(request, f"Parceiro {nome} excluído.")
    return redirect("parceiros")


@login_required
def mascaras_lista(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "tickets/mascaras.html",
        {"mascaras": Mascara.objects.all()},
    )


@login_required
def mascara_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    from .management.commands.seed_nio import MASCARAS as PADROES_SEED

    instance = get_object_or_404(Mascara, pk=pk) if pk else None
    if request.method == "POST":
        form = MascaraForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Máscara salva.")
            return redirect("mascaras")
    else:
        form = MascaraForm(instance=instance)

    padroes = [
        {
            "nome": p["nome"],
            "destino": p["destino"],
            "tipos": p["tipos"],
            "template": p["template"],
        }
        for p in PADROES_SEED
    ]
    return render(
        request,
        "tickets/mascara_form.html",
        {
            "form": form,
            "titulo": "Editar máscara" if instance else "Nova máscara",
            "padroes": padroes,
        },
    )


@gestor_required
def especialistas_lista(request: HttpRequest) -> HttpResponse:
    User = get_user_model()
    especialistas = (
        User.objects.filter(perfil_staff__isnull=False)
        .select_related("perfil_staff")
        .annotate(qtd_parceiros=Count("parceiros_especialista"))
        .order_by("perfil_staff__papel", "first_name", "username")
    )
    return render(
        request,
        "tickets/especialistas.html",
        {"especialistas": especialistas},
    )


@gestor_required
def especialista_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    User = get_user_model()
    instance = None
    if pk:
        instance = get_object_or_404(
            User.objects.filter(perfil_staff__isnull=False).select_related("perfil_staff"),
            pk=pk,
        )
        if instance.pk == request.user.pk:
            messages.info(
                request,
                "Para nome, e-mail ou senha do seu login, use Meu perfil. "
                "Peça a outro admin para alterar o seu papel.",
            )
            return redirect("meu_perfil")
    form = EspecialistaForm(instance=instance)
    if request.method == "POST":
        form = EspecialistaForm(request.POST, instance=instance)
        if form.is_valid():
            user = form.save()
            nome = user.get_full_name() or user.username
            if eh_gestor(user):
                messages.success(
                    request,
                    f"{nome} salvo como admin e passa a ver todos os tickets.",
                )
            else:
                messages.success(
                    request,
                    f"Especialista {nome} salvo. "
                    "Associe-o no cadastro de cada parceiro.",
                )
            return redirect("especialistas")
    parceiros = []
    if instance:
        parceiros = Parceiro.objects.filter(especialista=instance).order_by("nome")
    return render(
        request,
        "tickets/especialista_form.html",
        {
            "form": form,
            "especialista": instance,
            "parceiros": parceiros,
            "titulo": "Editar acesso" if instance else "Novo especialista",
        },
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    base = tickets_visiveis(request.user)
    por_status = dict(
        base.values_list("status").annotate(c=Count("id")).values_list("status", "c")
    )
    total = base.count()
    por_tipo_raw = list(base.values("tipo").annotate(c=Count("id")).order_by("-c"))
    labels = dict(TipoDemanda.choices)
    por_tipo = []
    for row in por_tipo_raw:
        qtd = int(row["c"] or 0)
        full = labels.get(row["tipo"], row["tipo"])
        # rótulo curto para o painel (corta código/parênteses longos)
        curto = full.split(" — ")[0].split(" (")[0].strip()
        por_tipo.append(
            {
                "tipo": row["tipo"],
                "label": curto,
                "label_full": full,
                "c": qtd,
                "pct": round((100.0 * qtd / total), 1) if total else 0.0,
            }
        )
    return render(
        request,
        "tickets/dashboard.html",
        {
            "total": total,
            "abertos": base.exclude(
                status__in=[
                    StatusTicket.RESOLVIDO,
                    StatusTicket.FECHADO,
                    StatusTicket.CANCELADO,
                ]
            ).count(),
            "novos": base.filter(status=StatusTicket.NOVO).count(),
            "por_status": por_status,
            "por_tipo": por_tipo,
            "por_tipo_total": sum(r["c"] for r in por_tipo),
            "recentes": base.select_related("parceiro")[:15],
        },
    )


@login_required
@require_GET
def ticket_mascaras_json(request: HttpRequest, protocolo: str) -> HttpResponse:
    """Máscaras preenchidas do ticket — usado para copiar direto na fila."""
    ticket = ticket_para_usuario(request.user, protocolo)
    mascaras = [
        m for m in Mascara.objects.filter(ativo=True) if m.aplica_para(ticket.tipo)
    ]
    payload = [
        {
            "id": m.id,
            "nome": m.nome,
            "destino": m.destino,
            "conteudo": render_mascara(m, ticket),
        }
        for m in mascaras
    ]
    return JsonResponse(
        {
            "protocolo": ticket.protocolo,
            "tipo": ticket.get_tipo_display(),
            "mascaras": payload,
        }
    )


@login_required
def config_resposta_lista(request: HttpRequest) -> HttpResponse:
    garantir_config_resposta_padrao()
    configs = {c.tipo: c for c in ConfigRespostaTipo.objects.all()}
    itens = []
    for codigo, label in TipoDemanda.choices:
        cfg = configs.get(codigo)
        ativos = len(cfg.campos_ativos()) if cfg else 0
        total = len(cfg.campos) if cfg else 0
        itens.append(
            {
                "tipo": codigo,
                "label": label,
                "ativos": ativos,
                "total": total,
            }
        )
    return render(
        request,
        "tickets/config_resposta_lista.html",
        {"itens": itens},
    )


@login_required
def config_resposta_editar(request: HttpRequest, tipo: str) -> HttpResponse:
    from .demanda_campos import CAMPOS_RESPOSTA_POR_TIPO

    if tipo not in TipoDemanda.values:
        messages.error(request, "Tipo de demanda inválido.")
        return redirect("config_resposta_lista")

    garantir_config_resposta_padrao()
    padrao = CAMPOS_RESPOSTA_POR_TIPO.get(tipo) or CAMPOS_RESPOSTA_POR_TIPO[TipoDemanda.OUTROS]
    cfg, _ = ConfigRespostaTipo.objects.get_or_create(
        tipo=tipo,
        defaults={"campos": [{**c, "ativo": True} for c in padrao]},
    )

    catalogo = catalogo_campos_resposta()
    atuais = {c["name"]: dict(c) for c in (cfg.campos or [])}

    if request.method == "POST":
        novos: list[dict] = []
        nomes: list[str] = []
        for c in catalogo:
            nomes.append(c["name"])
        for name in atuais:
            if name not in nomes:
                nomes.append(name)

        # novos campos custom
        novo_nome = (request.POST.get("novo_name") or "").strip().lower()
        novo_label = (request.POST.get("novo_label") or "").strip()
        if novo_nome and novo_label:
            import re

            novo_nome = re.sub(r"[^a-z0-9_]+", "_", novo_nome).strip("_")
            if novo_nome and novo_nome not in nomes:
                nomes.append(novo_nome)
                atuais[novo_nome] = {
                    "name": novo_nome,
                    "label": novo_label,
                    "widget": request.POST.get("novo_widget") or "text",
                    "required": False,
                    "ativo": True,
                    "help": "",
                    "placeholder": "",
                }

        for name in nomes:
            prefix = f"campo_{name}_"
            base = atuais.get(name) or next(
                (dict(c) for c in catalogo if c["name"] == name), {"name": name}
            )
            novos.append(
                {
                    "name": name,
                    "label": (
                        request.POST.get(prefix + "label") or base.get("label") or name
                    ).strip(),
                    "widget": request.POST.get(prefix + "widget")
                    or base.get("widget")
                    or "text",
                    "required": request.POST.get(prefix + "required") == "on",
                    "ativo": request.POST.get(prefix + "ativo") == "on",
                    "help": (
                        request.POST.get(prefix + "help") or base.get("help") or ""
                    ).strip(),
                    "placeholder": (
                        request.POST.get(prefix + "placeholder")
                        or base.get("placeholder")
                        or ""
                    ).strip(),
                }
            )

        cfg.campos = novos
        cfg.save()
        messages.success(
            request, f"Campos de resposta de “{cfg.get_tipo_display()}” salvos."
        )
        return redirect("config_resposta_editar", tipo=tipo)

    linhas = []
    vistos: set[str] = set()
    for c in catalogo:
        if c["name"] in atuais:
            linhas.append({**c, **atuais[c["name"]]})
        else:
            linhas.append({**c, "ativo": False})
        vistos.add(c["name"])
    for name, c in atuais.items():
        if name not in vistos:
            linhas.append(c)

    return render(
        request,
        "tickets/config_resposta_form.html",
        {
            "cfg": cfg,
            "tipo": tipo,
            "titulo": cfg.get_tipo_display(),
            "linhas": linhas,
        },
    )


def _salvar_anexos(request: HttpRequest, ticket: Ticket) -> None:
    files = request.FILES.getlist("evidencias") or request.FILES.getlist("arquivo")
    for f in files:
        Anexo.objects.create(
            ticket=ticket,
            arquivo=f,
            nome_original=f.name,
            enviado_por=request.user if request.user.is_authenticated else None,
        )
