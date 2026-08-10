from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .demanda_campos import LABELS_POR_TIPO, LABELS_SIMPLES, schema_para_js, schema_tipo
from .forms import (
    AnexoForm,
    ContatoParceiroForm,
    FilaFiltroForm,
    LoginForm,
    MascaraForm,
    MensagemForm,
    ParceiroForm,
    TicketCreateForm,
    TicketPublicCreateForm,
    TicketTreatForm,
)
from .models import (
    Anexo,
    ContatoParceiro,
    Encaminhamento,
    Mascara,
    Mensagem,
    Parceiro,
    StatusTicket,
    Ticket,
)
from .services import render_mascara


class StaffLoginView(LoginView):
    template_name = "tickets/login.html"
    authentication_form = LoginForm


class StaffLogoutView(LogoutView):
    next_page = "login"


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("fila")
    return redirect("abrir_demanda")


@login_required
def fila(request: HttpRequest) -> HttpResponse:
    form = FilaFiltroForm(request.GET or None)
    qs = Ticket.objects.select_related("parceiro", "atendente")

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

    abertos = qs.exclude(
        status__in=[StatusTicket.RESOLVIDO, StatusTicket.FECHADO, StatusTicket.CANCELADO]
    )
    return render(
        request,
        "tickets/fila.html",
        {
            "form": form,
            "tickets": qs[:200],
            "abertos_count": abertos.count(),
        },
    )


@login_required
def ticket_criar(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = TicketCreateForm(request.POST, request.FILES)
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


@login_required
def ticket_detalhe(request: HttpRequest, protocolo: str) -> HttpResponse:
    ticket = get_object_or_404(
        Ticket.objects.select_related("parceiro", "atendente"), protocolo=protocolo
    )
    treat_form = TicketTreatForm(instance=ticket)
    msg_form = MensagemForm()
    anexo_form = AnexoForm()
    mascaras = [
        m for m in Mascara.objects.filter(ativo=True) if m.aplica_para(ticket.tipo)
    ]

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "tratar":
            treat_form = TicketTreatForm(request.POST, instance=ticket)
            if treat_form.is_valid():
                t = treat_form.save(commit=False)
                if not t.primeiro_atendimento_em and t.status != StatusTicket.NOVO:
                    t.primeiro_atendimento_em = timezone.now()
                if not t.atendente:
                    t.atendente = request.user
                t.save()
                if t.resposta_publica:
                    Mensagem.objects.create(
                        ticket=t,
                        autor=request.user,
                        autor_nome=request.user.get_username(),
                        corpo=t.resposta_publica,
                        interno=False,
                    )
                messages.success(request, "Ticket atualizado.")
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
            "schema": schema_tipo(ticket.tipo),
            "labels_tipo": {**LABELS_SIMPLES, **LABELS_POR_TIPO.get(ticket.tipo, {})},
            "campos_resposta": treat_form.campos_resposta_defs,
            "resposta_field_names": [c["name"] for c in treat_form.campos_resposta_defs],
        },
    )


@login_required
def parceiros_lista(request: HttpRequest) -> HttpResponse:
    parceiros = Parceiro.objects.annotate(
        qtd_tickets=Count("tickets"),
        qtd_contatos=Count("contatos"),
    ).order_by("nome")
    return render(
        request,
        "tickets/parceiros.html",
        {"parceiros": parceiros},
    )


@login_required
def parceiro_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    instance = get_object_or_404(Parceiro, pk=pk) if pk else None
    qtd_tickets = instance.tickets.count() if instance else 0
    contatos = instance.contatos.all() if instance else []
    contato_form = ContatoParceiroForm()
    form = ParceiroForm(instance=instance)

    if request.method == "POST":
        action = request.POST.get("action") or "salvar_parceiro"
        if action == "salvar_parceiro":
            form = ParceiroForm(request.POST, instance=instance)
            if form.is_valid():
                form.save()
                messages.success(request, "Parceiro salvo.")
                return redirect("parceiro_editar", pk=form.instance.pk)
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
    contato = get_object_or_404(ContatoParceiro, pk=pk)
    contato.ativo = not contato.ativo
    contato.save(update_fields=["ativo", "atualizado_em"])
    estado = "ativado" if contato.ativo else "inativado"
    messages.success(request, f"Contato {contato.nome} {estado}.")
    return redirect("parceiro_editar", pk=contato.parceiro_id)


@login_required
@require_POST
def contato_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    contato = get_object_or_404(ContatoParceiro, pk=pk)
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

    contato = get_object_or_404(ContatoParceiro, pk=pk)
    contato.token_acesso = secrets.token_urlsafe(6)
    contato.save(update_fields=["token_acesso", "atualizado_em"])
    messages.success(request, f"Token aleatório de {contato.nome}: {contato.token_acesso}")
    return redirect("parceiro_editar", pk=contato.parceiro_id)


@login_required
@require_POST
def parceiro_inativar(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(Parceiro, pk=pk)
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
    parceiro = get_object_or_404(Parceiro, pk=pk)
    parceiro.ativo = True
    parceiro.save(update_fields=["ativo", "atualizado_em"])
    messages.success(request, f"Parceiro {parceiro.codigo_pdv} — {parceiro.nome} reativado.")
    return redirect("parceiros")


@login_required
@require_POST
def parceiro_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    parceiro = get_object_or_404(Parceiro, pk=pk)
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
    instance = get_object_or_404(Mascara, pk=pk) if pk else None
    if request.method == "POST":
        form = MascaraForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Máscara salva.")
            return redirect("mascaras")
    else:
        form = MascaraForm(instance=instance)
    return render(
        request,
        "tickets/mascara_form.html",
        {"form": form, "titulo": "Editar máscara" if instance else "Nova máscara"},
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    base = Ticket.objects.all()
    por_status = dict(
        base.values_list("status").annotate(c=Count("id")).values_list("status", "c")
    )
    por_tipo = list(
        base.values("tipo").annotate(c=Count("id")).order_by("-c")
    )
    return render(
        request,
        "tickets/dashboard.html",
        {
            "total": base.count(),
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
            "recentes": base.select_related("parceiro")[:15],
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
