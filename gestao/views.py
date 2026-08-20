from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.contrib import messages
from django.db.models import Count, Max, Q

from tickets.acesso import eh_gestor, gestor_required, parceiros_visiveis
from tickets.models import Parceiro

from .forms import GrossForm, PeriodoForm, UploadBaseForm
from .models import (
    CadastroTerceiro,
    ConfiguracaoOSAB,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    LoteImportacao,
    MetaCapilaridade,
    RelatorioFPD,
    VendaOSAB,
)
from .periodo import periodo_ativo, salvar_periodo
from .pipelines.churn import processar_churn
from .pipelines.fpd import processar_fpd
from .pipelines.osab import calcular_osab, persistir_capilaridade, processar_osab
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
    if request.method == "POST" and eh_gestor(request.user) and request.POST.get("action") == "recalcular":
        resumo = persistir_capilaridade(ano, mes)
        messages.success(request, f"Capilaridade recalculada: {resumo['linhas']} TTs, {resumo['ativos']} ativos.")
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
