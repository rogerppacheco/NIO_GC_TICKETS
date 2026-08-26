from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.db.models import Count, Max, Q
from django.urls import reverse

from tickets.acesso import eh_gestor, gestor_required, parceiros_visiveis
from tickets.models import Parceiro

from .forms import DestinatarioForm, GrossForm, PeriodoForm, UploadBaseForm
from .messaging.envio import (
    enviar_capilaridade_pdv,
    enviar_capilaridade_todos,
    enviar_churn_pdv,
    enviar_comissionamento_lote,
    enviar_comissionamento_pdv,
    enviar_fpd_pdv,
    enviar_osab_pdv,
    enviar_resumo_capilaridade,
    enviar_tarefa,
    enviar_tarefas_lote,
    enviar_teste,
    enviar_recompra,
    enviar_recompra_lote,
    enviar_venda_indevida,
    enviar_venda_indevida_lote,
)
from .messaging.syncwa import healthcheck, listar_grupos, modo_teste_ativo, syncwa_configurado
from .models import (
    CadastroTerceiro,
    ConfiguracaoOSAB,
    Destinatario,
    EnvioWhatsApp,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    LoteImportacao,
    MetaCapilaridade,
    RelatorioComissionamento,
    RelatorioFPD,
    RelatorioRecompra,
    RelatorioTarefa,
    RelatorioVendaIndevida,
    VendaOSAB,
)
from .periodo import periodo_ativo, salvar_periodo
from .pipelines.churn import processar_churn
from .pipelines.comissionamento import mapa_pdv_razoes, processar_comissionamento
from .pipelines.fpd import processar_fpd
from .pipelines.osab import calcular_osab, persistir_capilaridade, processar_osab
from .pipelines.recompra import processar_recompra
from .pipelines.tarefas import processar_tarefas
from .pipelines.venda_indevida import processar_venda_indevida
from .relatorios import montar_mascara_pdv, resumo_geral
from .terceiros import importar_sysmap


def _lote(request, tipo: str, arquivo_nome: str, ok: bool, resumo: dict, erro: str = "") -> LoteImportacao:
    return LoteImportacao.objects.create(
        tipo=tipo,
        arquivo_nome=arquivo_nome,
        ok=ok,
        erro=erro,
        resumo=resumo or {},
        criado_por=request.user if request.user.is_authenticated else None,
    )


def _parceiros(request):
    return parceiros_visiveis(request.user).filter(ativo=True).order_by("nome")


@login_required
def hub(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    if request.method == "POST" and eh_gestor(request.user) and request.POST.get("action") == "periodo":
        form = PeriodoForm(request.POST)
        if form.is_valid():
            salvar_periodo(form.cleaned_data["ano"], form.cleaned_data["mes"])
            messages.success(request, "Período ativo atualizado.")
            return redirect("gestao_hub")
    else:
        form = PeriodoForm(initial={"ano": ano, "mes": mes})

    ultima_osab = VendaOSAB.objects.aggregate(n=Count("id"), dt=Max("data_importacao"))
    ultima_sysmap = CadastroTerceiro.objects.aggregate(n=Count("id"), dt=Max("data_atualizacao"))
    ultima_fpd = RelatorioFPD.objects.aggregate(n=Count("id"), dt=Max("criado_em"))
    ultima_churn = HistoricoChurn.objects.aggregate(n=Count("id"), dt=Max("data_analise"))
    lotes = LoteImportacao.objects.all()[:8]
    return render(
        request,
        "gestao/hub.html",
        {
            "ano": ano,
            "mes": mes,
            "periodo_form": form,
            "pode_importar": eh_gestor(request.user),
            "osab": ultima_osab,
            "sysmap": ultima_sysmap,
            "fpd": ultima_fpd,
            "churn": ultima_churn,
            "lotes": lotes,
        },
    )


@login_required
def importar_sysmap_view(request: HttpRequest) -> HttpResponse:
    form = None
    if eh_gestor(request.user):
        form = UploadBaseForm(request.POST or None, request.FILES or None, extensoes=[".xlsx", ".xls", ".xlsb"])
        if request.method == "POST" and form.is_valid():
            arquivo = form.cleaned_data["arquivo"]
            try:
                resumo = importar_sysmap(arquivo, arquivo.name)
                _lote(request, LoteImportacao.Tipo.SYSMAP, arquivo.name, True, resumo)
                messages.success(
                    request,
                    f"Sysmap importado: {resumo['inseridos']} novos, {resumo['atualizados']} atualizados, "
                    f"{resumo['total_ativos']} ativos.",
                )
                return redirect("gestao_sysmap")
            except Exception as exc:
                _lote(request, LoteImportacao.Tipo.SYSMAP, arquivo.name, False, {}, str(exc))
                messages.error(request, f"Falha ao importar Sysmap: {exc}")
    terceiros = CadastroTerceiro.objects.select_related("parceiro").order_by("nome_terceiro")[:400]
    visiveis_ids = set(_parceiros(request).values_list("id", flat=True))
    if not eh_gestor(request.user):
        terceiros = terceiros.filter(parceiro_id__in=visiveis_ids)
    return render(
        request,
        "gestao/sysmap.html",
        {
            "form": form,
            "terceiros": terceiros,
            "total": CadastroTerceiro.objects.count(),
            "ativos": CadastroTerceiro.objects.filter(ativo=True).count(),
            "vinculados": CadastroTerceiro.objects.filter(parceiro__isnull=False).count(),
        },
    )


@login_required
def capilaridade_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action")
        if action == "recalcular":
            resumo = persistir_capilaridade(ano, mes)
            messages.success(
                request,
                f"Capilaridade recalculada: {resumo['linhas']} TTs, {resumo['ativos']} ativos.",
            )
            return redirect("gestao_capilaridade")
        if action == "enviar_pdv":
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(request, "Capilaridade", enviar_capilaridade_pdv(parceiro, request.user))
            return redirect("gestao_capilaridade")
        if action == "enviar_todos":
            _flash_resumo(
                request,
                "Capilaridade (todos)",
                enviar_capilaridade_todos(list(_parceiros(request)), request.user),
            )
            return redirect("gestao_capilaridade")

    parceiros = list(_parceiros(request))
    cards = []
    for p in parceiros:
        mascara = montar_mascara_pdv(p, ano, mes)
        meta = (
            MetaCapilaridade.objects.filter(parceiro=p, ano=ano, mes=mes)
            .values_list("meta_vendedores", flat=True)
            .first()
            or 0
        )
        cards.append({"parceiro": p, "mascara": mascara, "meta": meta})
    return render(
        request,
        "gestao/capilaridade.html",
        {
            "ano": ano,
            "mes": mes,
            "resumo": resumo_geral(parceiros, ano, mes),
            "cards": cards,
            "pode_recalcular": eh_gestor(request.user),
            "pode_enviar": eh_gestor(request.user) and syncwa_configurado(),
            "modo_teste": modo_teste_ativo(),
        },
    )


@login_required
def osab_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    if request.method == "POST" and eh_gestor(request.user):
        if request.POST.get("action") == "recalcular":
            resumo = calcular_osab(ano, mes)
            messages.success(request, f"OSAB recalculada: {resumo['pdvs']} PDV(s).")
            return redirect("gestao_osab")
        form = UploadBaseForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = form.cleaned_data["arquivo"]
            try:
                resumo = processar_osab(arquivo, arquivo.name, ano, mes)
                _lote(request, LoteImportacao.Tipo.OSAB, arquivo.name, True, resumo)
                vendas = resumo["vendas"]
                messages.success(
                    request,
                    f"OSAB atualizada ({mes:02d}/{ano}): {vendas['inseridos']} inseridos, "
                    f"{vendas['atualizados']} atualizados. Capilaridade: {resumo['capilaridade']['linhas']} TTs.",
                )
                return redirect("gestao_osab")
            except Exception as exc:
                _lote(request, LoteImportacao.Tipo.OSAB, arquivo.name, False, {}, str(exc))
                messages.error(request, f"Falha ao importar OSAB: {exc}")
        else:
            messages.error(request, "Selecione um arquivo OSAB válido (.xlsb ou .xlsx).")
    visiveis = _parceiros(request)
    historico = (
        HistoricoOSAB.objects.select_related("parceiro")
        .filter(Q(parceiro__in=visiveis) | Q(parceiro__isnull=True))
        .order_by("-data_processamento")[:80]
    )
    return render(
        request,
        "gestao/osab.html",
        {
            "form": UploadBaseForm() if eh_gestor(request.user) else None,
            "ano": ano,
            "mes": mes,
            "total_vendas": VendaOSAB.objects.count(),
            "historico": historico,
            "pode_importar": eh_gestor(request.user),
        },
    )


@gestor_required
def importar_fpd_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        lote = _lote(request, LoteImportacao.Tipo.FPD, arquivo.name, True, {})
        try:
            resumo = processar_fpd(arquivo, arquivo.name, lote)
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])
            messages.success(request, f"FPD processado: {resumo['pdvs']} PDV(s).")
            return redirect("gestao_fpd")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha ao importar FPD: {exc}")
    return _render_fpd(request, form)


@login_required
def fpd_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return importar_fpd_view(request)
    return _render_fpd(request, UploadBaseForm() if eh_gestor(request.user) else None)


def _render_fpd(request, form):
    visiveis = _parceiros(request)
    relatorios = RelatorioFPD.objects.select_related("parceiro", "lote").filter(parceiro__in=visiveis)[:80]
    return render(
        request,
        "gestao/fpd.html",
        {"form": form, "relatorios": relatorios, "pode_importar": eh_gestor(request.user)},
    )


@gestor_required
def importar_churn_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        try:
            resumo = processar_churn(arquivo, arquivo.name)
            _lote(request, LoteImportacao.Tipo.CHURN, arquivo.name, True, resumo)
            messages.success(request, f"Churn processado: {resumo['pdvs']} PDV(s), {resumo['linhas']} safras.")
            return redirect("gestao_churn")
        except Exception as exc:
            _lote(request, LoteImportacao.Tipo.CHURN, arquivo.name, False, {}, str(exc))
            messages.error(request, f"Falha ao importar Churn: {exc}")
    return _render_churn(request, form)


@login_required
def churn_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and request.POST.get("action") == "gross":
        return gross_salvar(request)
    if request.method == "POST" and request.FILES:
        return importar_churn_view(request)
    return _render_churn(request, UploadBaseForm() if eh_gestor(request.user) else None)


@gestor_required
def gross_salvar(request: HttpRequest) -> HttpResponse:
    form = GrossForm(request.POST)
    if form.is_valid():
        GrossMensal.objects.update_or_create(
            parceiro=form.cleaned_data["parceiro"],
            anomes=form.cleaned_data["anomes"],
            defaults={"gross": form.cleaned_data["gross"]},
        )
        messages.success(request, "Gross mensal salvo.")
    else:
        messages.error(request, "Não foi possível salvar o gross. Verifique AAAAMM e o valor.")
    return redirect("gestao_churn")


def _render_churn(request, form):
    visiveis = _parceiros(request)
    ultima = HistoricoChurn.objects.order_by("-data_analise").values_list("data_analise", flat=True).first()
    historico = HistoricoChurn.objects.select_related("parceiro").none()
    if ultima:
        historico = HistoricoChurn.objects.select_related("parceiro").filter(
            data_analise=ultima, parceiro__in=visiveis
        )
    mensagens = []
    vistos = set()
    for row in historico:
        if row.parceiro_id in vistos:
            continue
        if row.mensagem:
            mensagens.append(row)
            vistos.add(row.parceiro_id)
    return render(
        request,
        "gestao/churn.html",
        {
            "form": form,
            "gross_form": GrossForm() if eh_gestor(request.user) else None,
            "historico": historico,
            "mensagens": mensagens,
            "gross": GrossMensal.objects.select_related("parceiro").filter(parceiro__in=visiveis).order_by("-anomes")[:40],
            "pode_importar": eh_gestor(request.user),
        },
    )


@gestor_required
def importar_comissionamento_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    enviar = bool(request.POST.get("enviar_whatsapp"))
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        lote = _lote(request, LoteImportacao.Tipo.COMISSIONAMENTO, arquivo.name, True, {})
        try:
            resumo = processar_comissionamento(arquivo, arquivo.name, lote)
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])
            messages.success(
                request,
                f"Comissionamento: {resumo['pdvs']} PDV(s) gerado(s)"
                f" ({resumo['sem_linhas']} sem linhas / {resumo['pdvs_configurados']} configurados).",
            )
            if enviar and resumo["pdvs"]:
                _flash_resumo(
                    request,
                    "Envio comissionamento",
                    enviar_comissionamento_lote(lote.id, request.user),
                )
            return redirect("gestao_comissionamento")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha no comissionamento: {exc}")
    return _render_comissionamento(request, form)


@login_required
def comissionamento_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action") or ""
        if action == "enviar_pdv":
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(request, "Comissionamento", enviar_comissionamento_pdv(parceiro, request.user))
            return redirect("gestao_comissionamento")
        if action == "enviar_lote":
            lote_id = request.POST.get("lote")
            if not lote_id:
                messages.error(request, "Informe o lote.")
            else:
                _flash_resumo(
                    request,
                    "Comissionamento (lote)",
                    enviar_comissionamento_lote(int(lote_id), request.user),
                )
            return redirect("gestao_comissionamento")
        if request.FILES:
            return importar_comissionamento_view(request)
    return _render_comissionamento(
        request, UploadBaseForm() if eh_gestor(request.user) else None
    )


def _render_comissionamento(request, form):
    visiveis = _parceiros(request)
    relatorios = (
        RelatorioComissionamento.objects.select_related("parceiro", "lote")
        .filter(parceiro__in=visiveis)[:80]
    )
    lotes = LoteImportacao.objects.filter(
        tipo=LoteImportacao.Tipo.COMISSIONAMENTO, ok=True
    )[:15]
    return render(
        request,
        "gestao/comissionamento.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "mapa_razoes": mapa_pdv_razoes(),
            "pode_importar": eh_gestor(request.user),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@gestor_required
def importar_tarefas_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    enviar = bool(request.POST.get("enviar_whatsapp"))
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        lote = _lote(request, LoteImportacao.Tipo.TAREFAS, arquivo.name, True, {})
        try:
            resumo = processar_tarefas(arquivo, arquivo.name, lote)
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])
            messages.success(
                request,
                f"Tarefas ({resumo.get('indicador')}): {resumo.get('relatorios', 0)} relatório(s).",
            )
            if enviar and resumo.get("relatorios"):
                _flash_resumo(request, "Envio tarefas", enviar_tarefas_lote(lote.id, request.user))
            return redirect("gestao_tarefas")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Tarefas: {exc}")
    return _render_tarefas(request, form)


@login_required
def tarefas_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio"):
            rel = get_object_or_404(RelatorioTarefa, pk=request.POST.get("relatorio"))
            _flash_resumo(request, "Tarefas", enviar_tarefa(rel, request.user))
            return redirect("gestao_tarefas")
        if action == "enviar_lote" and request.POST.get("lote"):
            _flash_resumo(
                request,
                "Tarefas (lote)",
                enviar_tarefas_lote(int(request.POST.get("lote")), request.user),
            )
            return redirect("gestao_tarefas")
        if request.FILES:
            return importar_tarefas_view(request)
    return _render_tarefas(request, UploadBaseForm() if eh_gestor(request.user) else None)


def _render_tarefas(request, form):
    visiveis = _parceiros(request)
    relatorios = RelatorioTarefa.objects.select_related("parceiro", "lote").filter(
        Q(parceiro__isnull=True) | Q(parceiro__in=visiveis)
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.TAREFAS, ok=True)[:15]
    return render(
        request,
        "gestao/tarefas.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": eh_gestor(request.user),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@gestor_required
def importar_venda_indevida_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    enviar = bool(request.POST.get("enviar_whatsapp"))
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        lote = _lote(request, LoteImportacao.Tipo.VENDA_INDEVIDA, arquivo.name, True, {})
        try:
            resumo = processar_venda_indevida(arquivo, arquivo.name, lote)
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])
            messages.success(
                request,
                f"Venda indevida: {resumo['pdvs']} PDV(s), {resumo['total_linhas']} linha(s).",
            )
            if enviar:
                _flash_resumo(
                    request,
                    "Envio VI",
                    enviar_venda_indevida_lote(lote.id, request.user),
                )
            return redirect("gestao_venda_indevida")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Venda indevida: {exc}")
    return _render_venda_indevida(request, form)


@login_required
def venda_indevida_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio"):
            rel = get_object_or_404(RelatorioVendaIndevida, pk=request.POST.get("relatorio"))
            _flash_resumo(request, "Venda indevida", enviar_venda_indevida(rel, request.user))
            return redirect("gestao_venda_indevida")
        if action == "enviar_lote" and request.POST.get("lote"):
            _flash_resumo(
                request,
                "VI (lote)",
                enviar_venda_indevida_lote(int(request.POST.get("lote")), request.user),
            )
            return redirect("gestao_venda_indevida")
        if request.FILES:
            return importar_venda_indevida_view(request)
    return _render_venda_indevida(
        request, UploadBaseForm() if eh_gestor(request.user) else None
    )


def _render_venda_indevida(request, form):
    visiveis = _parceiros(request)
    relatorios = RelatorioVendaIndevida.objects.select_related("parceiro", "lote").filter(
        Q(parceiro__isnull=True) | Q(parceiro__in=visiveis)
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.VENDA_INDEVIDA, ok=True)[:15]
    return render(
        request,
        "gestao/venda_indevida.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": eh_gestor(request.user),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@gestor_required
def importar_recompra_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    enviar = bool(request.POST.get("enviar_whatsapp"))
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        lote = _lote(request, LoteImportacao.Tipo.RECOMPRA, arquivo.name, True, {})
        try:
            resumo = processar_recompra(arquivo, arquivo.name, lote)
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])
            messages.success(
                request,
                f"Recompra: {resumo['pdvs']} PDV(s), {resumo['total_linhas']} linha(s).",
            )
            if enviar:
                _flash_resumo(request, "Envio recompra", enviar_recompra_lote(lote.id, request.user))
            return redirect("gestao_recompra")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Recompra: {exc}")
    return _render_recompra(request, form)


@login_required
def recompra_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio"):
            rel = get_object_or_404(RelatorioRecompra, pk=request.POST.get("relatorio"))
            _flash_resumo(request, "Recompra", enviar_recompra(rel, request.user))
            return redirect("gestao_recompra")
        if action == "enviar_lote" and request.POST.get("lote"):
            _flash_resumo(
                request,
                "Recompra (lote)",
                enviar_recompra_lote(int(request.POST.get("lote")), request.user),
            )
            return redirect("gestao_recompra")
        if request.FILES:
            return importar_recompra_view(request)
    return _render_recompra(request, UploadBaseForm() if eh_gestor(request.user) else None)


def _render_recompra(request, form):
    visiveis = _parceiros(request)
    relatorios = RelatorioRecompra.objects.select_related("parceiro", "lote").filter(
        Q(parceiro__isnull=True) | Q(parceiro__in=visiveis)
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.RECOMPRA, ok=True)[:15]
    return render(
        request,
        "gestao/recompra.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": eh_gestor(request.user),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@gestor_required
def configs_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    parceiros = list(Parceiro.objects.filter(ativo=True).order_by("nome"))
    if request.method == "POST":
        for p in parceiros:
            prefix = f"p{p.id}_"
            meta_v = int(request.POST.get(prefix + "meta_vendedores") or 0)
            MetaCapilaridade.objects.update_or_create(
                parceiro=p, ano=ano, mes=mes, defaults={"meta_vendedores": meta_v}
            )
            ConfiguracaoOSAB.objects.update_or_create(
                parceiro=p,
                ano=ano,
                mes=mes,
                defaults={
                    "meta_vl": int(request.POST.get(prefix + "meta_vl") or 0),
                    "du_vl": float(request.POST.get(prefix + "du_vl") or 0),
                    "meta_gross": int(request.POST.get(prefix + "meta_gross") or 0),
                    "du_gross": float(request.POST.get(prefix + "du_gross") or 0),
                    "comissao_500": int(request.POST.get(prefix + "comissao_500") or 0),
                    "comissao_700": int(request.POST.get(prefix + "comissao_700") or 0),
                    "comissao_1000": int(request.POST.get(prefix + "comissao_1000") or 0),
                    "tem_bonus": prefix + "tem_bonus" in request.POST,
                    "comissao_bonus": int(request.POST.get(prefix + "comissao_bonus") or 0),
                    "tem_bonus_m10": prefix + "tem_bonus_m10" in request.POST,
                },
            )
        messages.success(request, f"Metas salvas para {mes:02d}/{ano}.")
        return redirect("gestao_configs")

    metas = {(m.parceiro_id): m for m in MetaCapilaridade.objects.filter(ano=ano, mes=mes)}
    configs = {(c.parceiro_id): c for c in ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes)}
    linhas = []
    for p in parceiros:
        linhas.append({"parceiro": p, "meta": metas.get(p.id), "osab": configs.get(p.id)})
    return render(request, "gestao/configs.html", {"ano": ano, "mes": mes, "linhas": linhas})


def _flash_resumo(request, titulo: str, resumo) -> None:
    texto = (
        f"{titulo}: {resumo.enviados} enviado(s), {resumo.erros} erro(s), "
        f"{resumo.ignorados} ignorado(s)."
    )
    if resumo.erros:
        messages.error(request, texto)
    elif resumo.enviados:
        messages.success(request, texto)
    else:
        messages.warning(request, texto)
    for linha in (resumo.detalhes or [])[:8]:
        messages.info(request, linha)


@gestor_required
def destinatarios_view(request: HttpRequest) -> HttpResponse:
    form = DestinatarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Destinatário salvo.")
        return redirect("gestao_destinatarios")
    lista = Destinatario.objects.select_related("parceiro").all()
    grupos = None
    if request.GET.get("grupos") == "1" and syncwa_configurado():
        grupos = listar_grupos()
        if not grupos.get("ok"):
            messages.error(request, f"Não foi possível listar grupos: {grupos.get('error')}")
    return render(
        request,
        "gestao/destinatarios.html",
        {
            "form": form,
            "destinatarios": lista,
            "syncwa_ok": syncwa_configurado(),
            "modo_teste": modo_teste_ativo(),
            "grupos": grupos,
            "parceiros": Parceiro.objects.filter(ativo=True).order_by("nome"),
        },
    )


@gestor_required
def destinatario_do_grupo(request: HttpRequest) -> HttpResponse:
    """Cadastra rápido um grupo WhatsApp como destinatário de um PDV."""
    if request.method != "POST":
        return redirect("gestao_destinatarios")
    parceiro_id = request.POST.get("parceiro")
    jid = (request.POST.get("jid") or "").strip()
    nome = (request.POST.get("nome") or "").strip() or jid
    if not parceiro_id or not jid or "@g.us" not in jid:
        messages.error(request, "Informe o PDV e um JID de grupo válido (@g.us).")
        return redirect(f"{reverse('gestao_destinatarios')}?grupos=1")
    parceiro = get_object_or_404(Parceiro, pk=parceiro_id, ativo=True)
    existente = Destinatario.objects.filter(parceiro=parceiro, jid=jid).first()
    if existente:
        messages.warning(request, f"Já existe destinatário {existente.nome} com este JID neste PDV.")
        return redirect("gestao_destinatarios")
    Destinatario.objects.create(
        parceiro=parceiro,
        nome=nome[:150],
        jid=jid,
        tipo=Destinatario.TipoDestino.GRUPO,
        ativo=True,
        envio_capilaridade=True,
        envio_osab=True,
        envio_fpd=True,
        envio_churn=True,
    )
    messages.success(request, f"Grupo «{nome}» vinculado a {parceiro.nome}.")
    return redirect("gestao_destinatarios")


@gestor_required
def destinatario_editar(request: HttpRequest, pk: int) -> HttpResponse:
    dest = get_object_or_404(Destinatario, pk=pk)
    form = DestinatarioForm(request.POST or None, instance=dest)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Destinatário atualizado.")
        return redirect("gestao_destinatarios")
    return render(
        request,
        "gestao/destinatario_form.html",
        {"form": form, "destinatario": dest},
    )


@gestor_required
def destinatario_excluir(request: HttpRequest, pk: int) -> HttpResponse:
    dest = get_object_or_404(Destinatario, pk=pk)
    if request.method == "POST":
        dest.delete()
        messages.success(request, "Destinatário excluído.")
    return redirect("gestao_destinatarios")


@gestor_required
def destinatario_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    dest = get_object_or_404(Destinatario, pk=pk)
    if request.method == "POST":
        dest.ativo = not dest.ativo
        dest.save(update_fields=["ativo", "atualizado_em"])
        messages.success(request, f"{dest.nome}: {'ativo' if dest.ativo else 'inativo'}.")
    return redirect("gestao_destinatarios")


@login_required
def envios_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and eh_gestor(request.user):
        action = request.POST.get("action") or ""
        parceiro_id = request.POST.get("parceiro") or ""
        parceiro = None
        if parceiro_id:
            parceiro = get_object_or_404(_parceiros(request), pk=parceiro_id)

        if action == "teste":
            _flash_resumo(request, "Teste WhatsApp", enviar_teste(request.user))
            return redirect("gestao_envios")
        if action == "capilaridade":
            if parceiro:
                _flash_resumo(request, "Capilaridade", enviar_capilaridade_pdv(parceiro, request.user))
            else:
                _flash_resumo(
                    request,
                    "Capilaridade (todos)",
                    enviar_capilaridade_todos(list(_parceiros(request)), request.user),
                )
            return redirect("gestao_envios")
        if action == "resumo_capilaridade":
            _flash_resumo(
                request,
                "Resumo capilaridade",
                enviar_resumo_capilaridade(list(_parceiros(request)), request.user),
            )
            return redirect("gestao_envios")
        if action == "osab":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar OSAB.")
            else:
                _flash_resumo(request, "OSAB", enviar_osab_pdv(parceiro, request.user))
            return redirect("gestao_envios")
        if action == "fpd":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar FPD.")
            else:
                _flash_resumo(request, "FPD", enviar_fpd_pdv(parceiro, request.user))
            return redirect("gestao_envios")
        if action == "churn":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar Churn.")
            else:
                _flash_resumo(request, "Churn", enviar_churn_pdv(parceiro, request.user))
            return redirect("gestao_envios")
        if action == "comissionamento":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar Comissionamento.")
            else:
                _flash_resumo(
                    request,
                    "Comissionamento",
                    enviar_comissionamento_pdv(parceiro, request.user),
                )
            return redirect("gestao_envios")
        if action == "tarefas":
            # último relatório do PDV (abertas) ou consolidado se sem PDV
            if parceiro:
                rel = (
                    RelatorioTarefa.objects.filter(parceiro=parceiro)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                rel = (
                    RelatorioTarefa.objects.filter(parceiro__isnull=True)
                    .order_by("-criado_em")
                    .first()
                )
            if not rel:
                messages.error(request, "Nenhum relatório de tarefas para enviar.")
            else:
                _flash_resumo(request, "Tarefas", enviar_tarefa(rel, request.user))
            return redirect("gestao_envios")
        if action == "venda_indevida":
            if parceiro:
                rel = (
                    RelatorioVendaIndevida.objects.filter(parceiro=parceiro, consolidado=False)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                rel = (
                    RelatorioVendaIndevida.objects.filter(consolidado=True)
                    .order_by("-criado_em")
                    .first()
                )
            if not rel:
                messages.error(request, "Nenhum relatório de venda indevida para enviar.")
            else:
                _flash_resumo(request, "Venda indevida", enviar_venda_indevida(rel, request.user))
            return redirect("gestao_envios")
        if action == "recompra":
            if parceiro:
                rel = (
                    RelatorioRecompra.objects.filter(parceiro=parceiro, consolidado=False)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                rel = (
                    RelatorioRecompra.objects.filter(consolidado=True)
                    .order_by("-criado_em")
                    .first()
                )
            if not rel:
                messages.error(request, "Nenhum relatório de recompra para enviar.")
            else:
                _flash_resumo(request, "Recompra", enviar_recompra(rel, request.user))
            return redirect("gestao_envios")

    health = healthcheck() if syncwa_configurado() else {"ok": False, "error": "não configurado"}
    logs = EnvioWhatsApp.objects.select_related("parceiro", "destinatario")[:60]
    return render(
        request,
        "gestao/envios.html",
        {
            "parceiros": _parceiros(request),
            "pode_enviar": eh_gestor(request.user),
            "syncwa_ok": syncwa_configurado(),
            "modo_teste": modo_teste_ativo(),
            "health": health,
            "logs": logs,
            "qtd_destinatarios": Destinatario.objects.filter(ativo=True).count(),
        },
    )
