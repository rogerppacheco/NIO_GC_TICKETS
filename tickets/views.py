from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .acesso import (
    eh_admin,
    eh_gestor,
    eh_gerencia,
    escopo_gestao,
    gestor_required,
    parceiro_de,
    parceiros_da_fila,
    parceiros_para_cadastro,
    parceiros_visiveis,
    pode_importar_bases,
    qs_equipe,
    qs_equipe_da_gerencia,
    tem_acesso_interno,
    ticket_para_usuario,
    tickets_da_fila,
    tickets_visiveis,
    destino_pos_login,
)
from .demanda_campos import (
    catalogo_campos_resposta,
    contexto_demanda_para_resposta,
    garantir_config_resposta_padrao,
    labels_para_ticket,
    montar_abas_tratamento,
    schema_para_js,
    schema_tipo,
)
from .forms import (
    AnexoForm,
    ContatoParceiroForm,
    DashboardFiltroForm,
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
    PerfilStaff,
    StatusTicket,
    Ticket,
    TipoDemanda,
)
from .services import (
    enviar_mascara_whatsapp,
    notificar_demanda_com_anexo,
    notificar_mascaras_por_email,
    notificar_mascaras_por_whatsapp,
    render_mascara,
)
from gestao.messaging.syncwa import syncwa_configurado


class StaffLoginView(LoginView):
    template_name = "tickets/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        from .seguranca import esta_bloqueado, ip_de, registrar_evento
        from .models import RegistroAcesso

        username = (request.POST.get("username") or "").strip()
        ip = ip_de(request)
        if esta_bloqueado(username, ip):
            registrar_evento(
                RegistroAcesso.Tipo.BLOQUEIO,
                username_tentativa=username,
                ip=ip,
            )
            form = self.get_form()
            form.add_error(None, "Usuário ou senha inválidos.")
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        from .seguranca import ip_de, limpar_falhas_login, registrar_evento, tocar_atividade
        from .models import RegistroAcesso

        response = super().form_valid(form)
        username = form.cleaned_data.get("username") or ""
        ip = ip_de(self.request)
        limpar_falhas_login(username, ip)
        registrar_evento(RegistroAcesso.Tipo.LOGIN_OK, ator=self.request.user, ip=ip)
        tocar_atividade(self.request)
        return response

    def form_invalid(self, form):
        from .seguranca import (
            esta_bloqueado,
            ip_de,
            registrar_evento,
            registrar_falha_login,
        )
        from .models import RegistroAcesso

        username = (self.request.POST.get("username") or "").strip()
        ip = ip_de(self.request)
        bloqueou = registrar_falha_login(username, ip)
        registrar_evento(
            RegistroAcesso.Tipo.LOGIN_FALHA,
            username_tentativa=username,
            ip=ip,
        )
        if bloqueou or esta_bloqueado(username, ip):
            registrar_evento(
                RegistroAcesso.Tipo.BLOQUEIO,
                username_tentativa=username,
                ip=ip,
            )
        return super().form_invalid(form)

    def get_success_url(self):
        from .seguranca import deve_trocar_senha

        user = self.request.user
        if deve_trocar_senha(user):
            return reverse("senha_trocar")
        proximo = self.get_redirect_url()
        if proximo:
            return proximo
        return destino_pos_login(user)


class StaffLogoutView(LogoutView):
    next_page = "login"


@login_required
def meu_perfil(request: HttpRequest) -> HttpResponse:
    if parceiro_de(request.user):
        return render(
            request,
            "tickets/perfil_parceiro.html",
            {"parceiro": parceiro_de(request.user)},
        )
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
        from .seguranca import deve_trocar_senha

        if deve_trocar_senha(request.user):
            return redirect("senha_trocar")
        return redirect(destino_pos_login(request.user))
    return redirect("login")


@login_required
def portal_inicio(request: HttpRequest) -> HttpResponse:
    pdv = parceiro_de(request.user)
    if pdv:
        return redirect("portal_parceiro")
    if not tem_acesso_interno(request.user):
        return redirect("login")
    return render(request, "tickets/portal_inicio.html")


def _chave_pedido(pedido: str | None) -> str:
    if not pedido:
        return ""
    chave = str(pedido).strip()
    if chave.endswith(".0") and chave[:-2].isdigit():
        chave = chave[:-2]
    return chave


def _anexar_osab_fila(tickets: list) -> None:
    from gestao.models import VendaOSAB

    pedidos = {_chave_pedido(t.pedido) for t in tickets}
    pedidos.discard("")
    mapa = {}
    if pedidos:
        mapa = {
            v.pedido: v
            for v in VendaOSAB.objects.filter(pedido__in=pedidos).only(
                "pedido", "situacao", "dt_ref"
            )
        }
    for t in tickets:
        venda = mapa.get(_chave_pedido(t.pedido))
        t.osab_situacao = (venda.situacao if venda else "") or ""
        t.osab_atualizacao = venda.dt_ref if venda else None


@login_required
def fila(request: HttpRequest) -> HttpResponse:
    especialistas_qs = qs_equipe_da_gerencia(request.user)
    get_data = request.GET.copy()
    spec_sel = None
    raw_spec = (get_data.get("especialista") or "").strip()
    if raw_spec.isdigit():
        spec_sel = especialistas_qs.filter(pk=int(raw_spec)).first()
        if not spec_sel:
            get_data.pop("especialista", None)

    parceiros_qs = parceiros_da_fila(request.user, spec_sel)
    raw_pdv = (get_data.get("parceiro") or "").strip()
    if raw_pdv.isdigit() and not parceiros_qs.filter(pk=int(raw_pdv)).exists():
        get_data.pop("parceiro", None)

    form = FilaFiltroForm(
        get_data or None,
        parceiros_qs=parceiros_qs,
        especialistas_qs=especialistas_qs,
    )
    qs = tickets_da_fila(request.user, spec_sel)

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
        sit_osab = form.cleaned_data.get("situacao_osab")
        if sit_osab:
            from gestao.models import VendaOSAB

            if sit_osab == "__sem__":
                pedidos_osab = VendaOSAB.objects.exclude(situacao="").values_list(
                    "pedido", flat=True
                )
                qs = qs.filter(Q(pedido="") | ~Q(pedido__in=pedidos_osab))
            else:
                pedidos_osab = VendaOSAB.objects.filter(situacao=sit_osab).values_list(
                    "pedido", flat=True
                )
                qs = qs.filter(pedido__in=pedidos_osab)

    abertos = qs.exclude(
        status__in=[StatusTicket.RESOLVIDO, StatusTicket.FECHADO, StatusTicket.CANCELADO]
    )
    filtros_ativos = any(
        (request.GET.get(k) or "").strip()
        for k in ("q", "status", "tipo", "parceiro", "especialista", "situacao_osab")
    )
    tickets = list(qs[:200])
    _anexar_osab_fila(tickets)
    return render(
        request,
        "tickets/fila.html",
        {
            "form": form,
            "tickets": tickets,
            "abertos_count": abertos.count(),
            "mostrar_filtro_especialista": True,
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
            notificar_mascaras_por_email(ticket)
            notificar_mascaras_por_whatsapp(ticket)
            notificar_demanda_com_anexo(ticket, ator=request.user)
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


_DESTINO_APOS_CONTATO = {
    "rota": "rota_portal",
    "formulario": "abrir_demanda_form",
    "demanda": "abrir_demanda_form",
    "minhas": "minhas_demandas",
    "consulta": "consulta_busca",
}
_URL_PARA_NEXT = {
    "abrir_demanda_form": "formulario",
    "abrir_demanda": "formulario",
    "minhas_demandas": "minhas",
    "rota_portal": "rota",
    "consulta_busca": "consulta",
}


def _gravar_contato_sessao(request: HttpRequest, contato_id: int) -> None:
    request.session["contato_id"] = contato_id
    request.session.modified = True


def _redirect_apos_contato(next_destino: str) -> HttpResponse:
    nome = _DESTINO_APOS_CONTATO.get((next_destino or "").strip().lower(), "portal_parceiro")
    return redirect(nome)


@login_required
def abrir_demanda(request: HttpRequest) -> HttpResponse:
    """Atalho antigo do card: vai ao formulário (pede contato só se ainda não escolheu)."""
    return redirect("abrir_demanda_form")


@login_required
def portal_contato(request: HttpRequest) -> HttpResponse:
    pdv = parceiro_de(request.user)
    if not pdv:
        if tem_acesso_interno(request.user):
            return redirect("fila")
        return redirect("login")
    if not pdv.ativo:
        messages.error(request, "Este PDV está inativo.")
        return redirect("login")
    next_destino = (request.POST.get("next") or request.GET.get("next") or "").strip()
    trocar = (request.GET.get("trocar") or request.POST.get("trocar") or "").strip() == "1"
    _pdv, contato_atual = _portal_sessao(request)
    if request.method != "POST" and contato_atual and not trocar:
        return _redirect_apos_contato(next_destino)

    contatos = pdv.contatos.filter(ativo=True)
    if request.method == "POST":
        contato = get_object_or_404(
            ContatoParceiro, pk=request.POST.get("contato"), parceiro=pdv, ativo=True
        )
        _gravar_contato_sessao(request, contato.id)
        return _redirect_apos_contato(next_destino)
    if contatos.count() == 1:
        _gravar_contato_sessao(request, contatos.first().id)
        return _redirect_apos_contato(next_destino)
    if not contatos.exists():
        messages.error(
            request,
            "Este PDV ainda não tem contato ativo. Peça ao especialista para cadastrar Empresário ou Backoffice.",
        )
    return render(
        request,
        "tickets/parceiro_gate.html",
        {
            "parceiro": pdv,
            "contatos": contatos,
            "passo": "contato",
            "next": next_destino,
        },
    )


@login_required
def portal_parceiro(request: HttpRequest) -> HttpResponse:
    """Hub do contato identificado: abrir nova ou ver histórico do PDV."""
    parceiro, contato, redirecionar = _exigir_contato_portal(request)
    if redirecionar:
        return redirecionar
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


@login_required
def minhas_demandas(request: HttpRequest) -> HttpResponse:
    parceiro, contato, redirecionar = _exigir_contato_portal(request)
    if redirecionar:
        return redirecionar
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
    auth_logout(request)
    return redirect("login")


def _portal_sessao(request: HttpRequest):
    pdv = parceiro_de(request.user) if getattr(request.user, "is_authenticated", False) else None
    if not pdv or not pdv.ativo:
        return None, None
    contato_id = request.session.get("contato_id")
    contato = None
    if contato_id:
        contato = ContatoParceiro.objects.filter(
            pk=contato_id, parceiro=pdv, ativo=True
        ).first()
    return pdv, contato


def _exigir_contato_portal(request: HttpRequest, next_destino: str = ""):
    pdv, contato = _portal_sessao(request)
    if not pdv:
        if tem_acesso_interno(request.user):
            return None, None, redirect("fila")
        return None, None, redirect("login")
    if contato:
        return pdv, contato, None
    nxt = next_destino
    if not nxt:
        match = getattr(request, "resolver_match", None)
        nxt = _URL_PARA_NEXT.get(getattr(match, "url_name", "") or "", "")
    url = reverse("portal_contato")
    if nxt:
        url = f"{url}?next={nxt}"
    return pdv, None, redirect(url)


@login_required
def abrir_demanda_form(request: HttpRequest) -> HttpResponse:
    parceiro, contato, redirecionar = _exigir_contato_portal(request)
    if redirecionar:
        return redirecionar

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
            notificar_mascaras_por_email(ticket)
            notificar_mascaras_por_whatsapp(ticket)
            notificar_demanda_com_anexo(ticket, ator=request.user)
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


@login_required
def consulta_busca(request: HttpRequest) -> HttpResponse:
    """Parceiro informa o protocolo para ver STATUS / RETORNO."""
    if request.method == "POST":
        protocolo = (request.POST.get("protocolo") or "").strip().upper()
        if not protocolo:
            messages.error(request, "Informe o número do protocolo.")
            return redirect("consulta_busca")
        ticket = Ticket.objects.filter(protocolo=protocolo).first()
        from .acesso import pode_ver_ticket

        if not ticket or not pode_ver_ticket(request.user, ticket):
            messages.error(request, "Protocolo não encontrado.")
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
    elif tem_acesso_interno(request.user):
        minhas = tickets_visiveis(request.user)[:10]
    return render(
        request,
        "tickets/consulta_busca.html",
        {"parceiro": parceiro, "contato": contato, "minhas": minhas},
    )


@login_required
def consulta_protocolo(request: HttpRequest, protocolo: str) -> HttpResponse:
    from .acesso import pode_ver_ticket

    ticket = Ticket.objects.select_related("parceiro").filter(protocolo=protocolo.upper()).first()
    if not ticket or not pode_ver_ticket(request.user, ticket):
        raise Http404("Ticket não encontrado.")
    msgs = ticket.mensagens.filter(interno=False)
    return render(
        request,
        "tickets/consulta.html",
        {"ticket": ticket, "mensagens": msgs},
    )


def _eh_ajax(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _proximo_seguro(request: HttpRequest, fallback: str = "") -> str:
    bruto = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if bruto and url_has_allowed_host_and_scheme(
        bruto,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return bruto
    return fallback


def _ctx_modal_resposta(request: HttpRequest, ticket: Ticket, treat_form: TicketTreatForm) -> dict:
    proximo = _proximo_seguro(request)
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
    proximo = _proximo_seguro(request, reverse("fila"))

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


def _destinos_whatsapp_para_ticket(ticket: Ticket) -> list[dict]:
    """Retorna opções organizadas de destinatários para quando o especialista for admin."""
    from django.contrib.auth import get_user_model
    from gestao.models import Destinatario

    opcoes = []

    # 1. Grupos de WhatsApp cadastrados em Destinatario
    grupos = (
        Destinatario.objects.filter(
            ativo=True, owner__isnull=True, tipo=Destinatario.TipoDestino.GRUPO
        )
        .order_by("nome")
    )
    itens_grupos = []
    for g in grupos:
        itens_grupos.append({
            "jid": g.jid,
            "nome": g.nome,
            "rotulo": f"{g.nome} (Grupo)",
        })
    if itens_grupos:
        opcoes.append({"categoria": "Grupos de WhatsApp", "itens": itens_grupos})

    # 2. Contatos do próprio parceiro (empresários, backoffice)
    if ticket.parceiro:
        itens_parceiro = []
        for c in ticket.parceiro.contatos.filter(ativo=True).exclude(telefone=""):
            cargo = f" - {c.cargo}" if c.cargo else ""
            itens_parceiro.append({
                "jid": c.telefone,
                "nome": f"{c.nome}{cargo}",
                "rotulo": f"{c.nome}{cargo} ({c.telefone})",
            })
        if itens_parceiro:
            opcoes.append({"categoria": f"Contatos de {ticket.parceiro.nome}", "itens": itens_parceiro})

    # 3. Especialistas da equipe (com WhatsApp cadastrado)
    User = get_user_model()
    specs = (
        User.objects.filter(is_active=True, perfil_staff__isnull=False)
        .exclude(perfil_staff__whatsapp="")
        .select_related("perfil_staff")
        .order_by("first_name", "username")
    )
    itens_specs = []
    for s in specs:
        wpp = (getattr(s.perfil_staff, "whatsapp", "") or "").strip()
        if wpp:
            nome = (s.get_full_name() or s.username).strip()
            itens_specs.append({
                "jid": wpp,
                "nome": f"Especialista {nome}",
                "rotulo": f"Especialista {nome} ({wpp})",
            })
    if itens_specs:
        opcoes.append({"categoria": "Especialistas NIO", "itens": itens_specs})

    # 4. Outros contatos individuais cadastrados em Destinatario
    individuais = (
        Destinatario.objects.filter(
            ativo=True, owner__isnull=True, tipo=Destinatario.TipoDestino.INDIVIDUAL
        )
        .order_by("nome")
    )
    itens_indiv = []
    for d in individuais:
        itens_indiv.append({
            "jid": d.jid,
            "nome": d.nome,
            "rotulo": f"{d.nome} ({d.jid})",
        })
    if itens_indiv:
        opcoes.append({"categoria": "Outros Contatos Cadastrados", "itens": itens_indiv})

    return opcoes


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

    spec = ticket.parceiro.especialista if ticket.parceiro else None
    eh_admin_spec = not spec or spec.username.lower() == "admin"
    destinos_wpp = _destinos_whatsapp_para_ticket(ticket) if eh_admin_spec else []
    dest_info_spec = (
        spec.perfil_staff.obter_destino_mascara()
        if (spec and getattr(spec, "perfil_staff", None))
        else {}
    )

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
                {
                    "ticket": ticket,
                    "mascara": mascara,
                    "conteudo": conteudo,
                    "eh_admin_spec": eh_admin_spec,
                    "especialista_parceiro": spec,
                    "destino_mascara_especialista": dest_info_spec,
                    "destinos_wpp": destinos_wpp,
                    "syncwa_ok": syncwa_configurado(),
                },
            )
        elif action == "enviar_mascara_wpp":
            mascara = get_object_or_404(Mascara, pk=request.POST.get("mascara_id"), ativo=True)
            destino_jid = (request.POST.get("destino_jid") or "").strip()
            destino_nome = (request.POST.get("destino_nome") or "").strip()

            destino_escolhido = (request.POST.get("destino_escolhido") or "").strip()
            if destino_escolhido and "|" in destino_escolhido:
                partes = destino_escolhido.split("|", 1)
                destino_jid = partes[0].strip()
                destino_nome = partes[1].strip()
            elif destino_escolhido:
                destino_jid = destino_escolhido.strip()

            destino_custom = (request.POST.get("destino_custom") or "").strip()
            if destino_custom:
                destino_jid = destino_custom
                destino_nome = f"Contato {destino_custom}"

            ok, msg = enviar_mascara_whatsapp(
                ticket,
                mascara,
                destino_jid=destino_jid or None,
                destino_nome=destino_nome or None,
                user=request.user,
            )
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect("ticket_detalhe", protocolo=ticket.protocolo)

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
            "eh_admin_spec": eh_admin_spec,
            "especialista_parceiro": spec,
            "destino_mascara_especialista": dest_info_spec,
            "destinos_wpp": destinos_wpp,
            "syncwa_ok": syncwa_configurado(),
            "schema": schema_tipo(ticket.tipo),
            "labels_tipo": labels_para_ticket(ticket),
            "campos_resposta": treat_form.campos_resposta_defs,
            "resposta_field_names": [c["name"] for c in treat_form.campos_resposta_defs],
            "abrir_modal_resposta": request.GET.get("responder") == "1",
            **_ctx_modal_resposta(request, ticket, treat_form),
        },
    )


@login_required
def parceiros_lista(request: HttpRequest) -> HttpResponse:
    escopo = escopo_gestao(request)
    if request.method == "POST" and request.POST.get("action") == "importar_carteira":
        if not pode_importar_bases(request.user):
            messages.error(request, "Sem permissão para importar a carteira.")
            return redirect(f"{reverse('parceiros')}?escopo={escopo}")
        from gestao.forms import UploadBaseForm
        from gestao.pipelines.carteira import processar_carteira

        form_imp = UploadBaseForm(request.POST, request.FILES, extensoes=[".xlsx", ".xlsb", ".xls"])
        if form_imp.is_valid():
            arquivo = form_imp.cleaned_data["arquivo"]
            try:
                resumo = processar_carteira(arquivo, arquivo.name)
                extra = ""
                if resumo.get("sem_cadastro_n"):
                    extra = (
                        f" {resumo['sem_cadastro_n']} PDV(s) da carteira sem cadastro"
                        f" (ex.: {', '.join(resumo['sem_cadastro'][:5])})."
                    )
                if resumo.get("divergencias_n"):
                    extra += f" {resumo['divergencias_n']} divergência(s) de aging vs. data."
                messages.success(
                    request,
                    f"Carteira PP: {resumo['atualizados']} PDV(s) com data credenciamento atualizada.{extra}",
                )
            except Exception as exc:
                messages.error(request, f"Falha ao importar carteira: {exc}")
        else:
            messages.error(request, "Selecione a Carteira PP (.xlsx).")
        return redirect(f"{reverse('parceiros')}?escopo={escopo}")

    parceiros = (
        parceiros_para_cadastro(request.user, escopo)
        .select_related("especialista", "especialista__perfil_staff")
        .prefetch_related("contatos")
        .annotate(qtd_tickets=Count("tickets"))
        .order_by("nome")
    )
    for p in parceiros:
        contatos = list(p.contatos.all())
        p.qtd_contatos = len(contatos)
        p.empresarios = [c for c in contatos if c.ativo and c.eh_empresario()]
        if p.especialista:
            completo = (p.especialista.get_full_name() or p.especialista.username or "").strip()
            p.especialista_curto = completo.split()[0] if completo else "—"
        else:
            p.especialista_curto = "—"
    return render(
        request,
        "tickets/parceiros.html",
        {
            "parceiros": parceiros,
            "gestao_escopo": escopo,
            "gestao_qtd_meus": parceiros_para_cadastro(request.user, "meus").count(),
            "gestao_qtd_outros": parceiros_para_cadastro(request.user, "outros").count(),
            "pode_importar_carteira": pode_importar_bases(request.user),
        },
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
                if parceiro.usuario_id and parceiro.usuario.is_active != parceiro.ativo:
                    parceiro.usuario.is_active = parceiro.ativo
                    parceiro.usuario.save(update_fields=["is_active"])
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
            "cargos_contato": ContatoParceiro.Cargo.choices,
            "cargos_contato_valores": {c.value for c in ContatoParceiro.Cargo},
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
    contato = get_object_or_404(
        ContatoParceiro.objects.filter(parceiro__in=parceiros_visiveis(request.user)),
        pk=pk,
    )
    messages.info(
        request,
        "O portal agora usa login e senha do PDV (código). Use “Gerar senha de acesso” nesta tela.",
    )
    return redirect("parceiro_editar", pk=contato.parceiro_id)


@login_required
@require_POST
def parceiro_inativar(request: HttpRequest, pk: int) -> HttpResponse:
    from .models import RegistroAcesso
    from .seguranca import invalidar_sessoes, ip_de, registrar_evento

    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    parceiro.ativo = False
    parceiro.save(update_fields=["ativo", "atualizado_em"])
    if parceiro.usuario_id:
        parceiro.usuario.is_active = False
        parceiro.usuario.save(update_fields=["is_active"])
        invalidar_sessoes(parceiro.usuario)
        registrar_evento(
            RegistroAcesso.Tipo.INATIVACAO,
            ator=request.user,
            alvo=parceiro.usuario,
            ip=ip_de(request),
            detalhe=parceiro.codigo_pdv,
        )
    messages.success(
        request,
        f"Parceiro {parceiro.codigo_pdv} — {parceiro.nome} inativado. "
        "Demandas antigas permanecem; login e novas aberturas ficam bloqueados.",
    )
    return redirect("parceiros")


@login_required
@require_POST
def parceiro_reativar(request: HttpRequest, pk: int) -> HttpResponse:
    from .models import RegistroAcesso
    from .seguranca import ip_de, registrar_evento

    parceiro = get_object_or_404(parceiros_visiveis(request.user), pk=pk)
    parceiro.ativo = True
    parceiro.save(update_fields=["ativo", "atualizado_em"])
    if parceiro.usuario_id:
        parceiro.usuario.is_active = True
        parceiro.usuario.save(update_fields=["is_active"])
        registrar_evento(
            RegistroAcesso.Tipo.REATIVACAO,
            ator=request.user,
            alvo=parceiro.usuario,
            ip=ip_de(request),
            detalhe=parceiro.codigo_pdv,
        )
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


@gestor_required
def mascaras_lista(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "tickets/mascaras.html",
        {"mascaras": Mascara.objects.all()},
    )


@gestor_required
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
            from gestao.parceiros import associar_parceiros_ao_especialista

            pdvs = associar_parceiros_ao_especialista(user)
            if eh_gestor(user):
                messages.success(
                    request,
                    f"{nome} salvo como admin e passa a ver todos os tickets.",
                )
            elif pdvs:
                messages.success(
                    request,
                    f"Especialista {nome} salvo. "
                    f"Parceiros da OSAB vinculados: {', '.join(pdvs)}.",
                )
            else:
                messages.success(
                    request,
                    f"Especialista {nome} salvo. "
                    "Associe-o no cadastro de cada parceiro se a OSAB ainda não tiver o GC.",
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


@gestor_required
@require_POST
def especialista_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    User = get_user_model()
    alvo = get_object_or_404(
        User.objects.filter(perfil_staff__isnull=False).select_related("perfil_staff"),
        pk=pk,
    )
    if alvo.pk == request.user.pk:
        messages.error(request, "Não é possível excluir o próprio acesso.")
        return redirect("especialistas")
    if eh_gestor(alvo):
        outros_admins = PerfilStaff.objects.filter(
            papel=PerfilStaff.Papel.GESTOR
        ).exclude(user_id=alvo.pk)
        if not outros_admins.exists():
            messages.error(
                request,
                "Não é possível excluir o último admin. Marque outra pessoa como admin antes.",
            )
            return redirect("especialistas")
    nome = alvo.get_full_name() or alvo.username
    alvo.delete()
    messages.success(request, f"{nome} excluído da equipe.")
    return redirect("especialistas")


def _periodo_dashboard(request: HttpRequest, hoje: date) -> tuple[str, date | None, date | None]:
    inicio_mes = hoje.replace(day=1)
    presets = {
        "7d": (hoje - timedelta(days=6), hoje),
        "30d": (hoje - timedelta(days=29), hoje),
        "mes": (inicio_mes, hoje),
        "tudo": (None, None),
    }
    periodo = (request.GET.get("periodo") or "mes").strip()
    if periodo not in presets and periodo != "custom":
        periodo = "mes"

    def _parse(val: str | None) -> date | None:
        texto = (val or "").strip()
        if not texto:
            return None
        try:
            return date.fromisoformat(texto)
        except ValueError:
            return None

    de = _parse(request.GET.get("de"))
    ate = _parse(request.GET.get("ate"))
    if de and ate and de > ate:
        de, ate = ate, de
    if de or ate:
        esperado = presets.get(periodo)
        if not esperado or (de, ate) != esperado:
            periodo = "custom"
    else:
        if periodo == "custom":
            periodo = "mes"
        de, ate = presets[periodo]
    return periodo, de, ate


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    hoje = timezone.localdate()
    periodo, de, ate = _periodo_dashboard(request, hoje)
    parceiros_qs = parceiros_visiveis(request.user).filter(ativo=True)
    especialistas_qs = qs_equipe()
    data = request.GET.copy()
    data["periodo"] = periodo
    if de:
        data["de"] = de.isoformat()
    else:
        data.pop("de", None)
    if ate:
        data["ate"] = ate.isoformat()
    else:
        data.pop("ate", None)

    form = DashboardFiltroForm(
        data,
        parceiros_qs=parceiros_qs,
        especialistas_qs=especialistas_qs,
    )
    gestor = eh_admin(request.user) or eh_gerencia(request.user)
    if not gestor:
        form.fields.pop("especialista", None)
    cleaned = form.cleaned_data if form.is_valid() else {}
    parceiro_sel = cleaned.get("parceiro")
    spec_sel = cleaned.get("especialista") if gestor else None

    base = tickets_visiveis(request.user)
    if parceiro_sel:
        base = base.filter(parceiro=parceiro_sel)
    if spec_sel:
        base = base.filter(parceiro__especialista=spec_sel)
    if de:
        base = base.filter(criado_em__date__gte=de)
    if ate:
        base = base.filter(criado_em__date__lte=ate)

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
        por_tipo.append(
            {
                "tipo": row["tipo"],
                "label": full,
                "label_full": full,
                "c": qtd,
                "pct": round((100.0 * qtd / total), 1) if total else 0.0,
            }
        )

    if spec_sel and getattr(spec_sel, "perfil_staff", None):
        fte_total = spec_sel.perfil_staff.fte or Decimal("0")
    else:
        fte_total = qs_equipe().aggregate(total=Sum("perfil_staff__fte"))["total"] or Decimal("0")
    tickets_por_fte = round(float(total) / float(fte_total), 1) if fte_total else 0.0

    qs_params = request.GET.copy()

    def _url_periodo(nome: str) -> str:
        q = qs_params.copy()
        q.pop("de", None)
        q.pop("ate", None)
        if nome == "mes":
            q.pop("periodo", None)
        else:
            q["periodo"] = nome
        encoded = q.urlencode()
        return f"{reverse('dashboard')}?{encoded}" if encoded else reverse("dashboard")

    prod_label = {
        "mes": "Tickets / FTE (mês)",
        "7d": "Tickets / FTE (7 dias)",
        "30d": "Tickets / FTE (30 dias)",
        "tudo": "Tickets / FTE",
        "custom": "Tickets / FTE",
    }.get(periodo, "Tickets / FTE")

    return render(
        request,
        "tickets/dashboard.html",
        {
            "form": form,
            "periodo": periodo,
            "periodo_de": de,
            "periodo_ate": ate,
            "url_mes": _url_periodo("mes"),
            "url_7d": _url_periodo("7d"),
            "url_30d": _url_periodo("30d"),
            "url_tudo": _url_periodo("tudo"),
            "filtros_ativos": bool(parceiro_sel or spec_sel or periodo != "mes"),
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
            "fte_total": fte_total,
            "fte_label": "FTE do especialista" if spec_sel else "FTE da equipe",
            "prod_label": prod_label,
            "tickets_mes": total,
            "tickets_por_fte": tickets_por_fte,
            "mostrar_filtro_especialista": gestor,
        },
    )


@login_required
@require_GET
def ticket_mascaras_json(request: HttpRequest, protocolo: str) -> HttpResponse:
    """Máscaras preenchidas do ticket e informações de destino — usado para copiar e enviar direto na fila."""
    from gestao.messaging.syncwa import syncwa_configurado

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

    spec = ticket.parceiro.especialista if ticket.parceiro else None
    eh_admin_spec = not spec or spec.username.lower() == "admin"
    dest_info = {}
    if spec:
        perfil = getattr(spec, "perfil_staff", None)
        if perfil:
            dest_info = perfil.obter_destino_mascara()

    destinos_disponiveis = _destinos_whatsapp_para_ticket(ticket)

    return JsonResponse(
        {
            "protocolo": ticket.protocolo,
            "parceiro": ticket.parceiro.nome if ticket.parceiro else "—",
            "tipo": ticket.get_tipo_display(),
            "mascaras": payload,
            "especialista": {
                "nome": (spec.get_full_name() or spec.username).strip() if spec else "",
                "eh_admin": eh_admin_spec,
                "tem_especialista": bool(spec),
                "destino_tipo": dest_info.get("tipo", "proprio"),
                "destino_tipo_display": dest_info.get("tipo_display", ""),
                "destino_jid": dest_info.get("jid", ""),
                "destino_nome": dest_info.get("nome", ""),
                "destino_rotulo": dest_info.get("rotulo", ""),
                "configurado": bool(dest_info.get("configurado")),
            },
            "destinos_disponiveis": destinos_disponiveis,
            "syncwa_ok": syncwa_configurado(),
        }
    )


@login_required
@require_POST
def ticket_enviar_mascara_api(request: HttpRequest, protocolo: str) -> HttpResponse:
    """Dispara o envio da máscara por WhatsApp diretamente da fila ou de modal."""
    import json

    ticket = ticket_para_usuario(request.user, protocolo)

    mascara_id = request.POST.get("mascara_id")
    destino_jid = (request.POST.get("destino_jid") or "").strip()
    destino_nome = (request.POST.get("destino_nome") or "").strip()

    # Suporta payload JSON caso enviado via fetch com Content-Type application/json
    if not mascara_id and request.body:
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            mascara_id = body_data.get("mascara_id")
            if not destino_jid:
                destino_jid = (body_data.get("destino_jid") or "").strip()
            if not destino_nome:
                destino_nome = (body_data.get("destino_nome") or "").strip()
        except Exception:
            pass

    if mascara_id:
        mascara = get_object_or_404(Mascara, pk=mascara_id, ativo=True)
    else:
        mascaras = [
            m for m in Mascara.objects.filter(ativo=True) if m.aplica_para(ticket.tipo)
        ]
        if not mascaras:
            return JsonResponse(
                {"ok": False, "erro": "Nenhuma máscara aplicável para este ticket."},
                status=400,
            )
        mascara = mascaras[0]

    if destino_jid and "|" in destino_jid:
        partes = destino_jid.split("|", 1)
        destino_jid = partes[0].strip()
        if not destino_nome:
            destino_nome = partes[1].strip()

    ok, msg = enviar_mascara_whatsapp(
        ticket,
        mascara,
        destino_jid=destino_jid or None,
        destino_nome=destino_nome or None,
        user=request.user,
    )

    if ok:
        return JsonResponse({
            "ok": True,
            "mensagem": msg,
            "protocolo": ticket.protocolo,
            "status": ticket.status,
            "status_display": ticket.get_status_display(),
        })
    else:
        return JsonResponse({
            "ok": False,
            "erro": msg,
            "protocolo": ticket.protocolo,
        }, status=400)


@gestor_required
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


@gestor_required
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
