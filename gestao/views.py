from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.db.models import Q
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from tickets.acesso import (
    GERENCIA_SESSAO,
    GERENCIA_TODAS,
    eh_gestor,
    escopo_gestao,
    gestor_required,
    listar_gerencias,
    parceiros_gestao,
    parceiros_gestao_ambos,
    parceiros_para_destinatarios,
    pode_importar_bases,
    tem_acesso_interno,
    ve_relatorios_sem_pdv,
)
from tickets.models import Parceiro

from .forms import (
    DestinatarioForm,
    GdpImportForm,
    GrossForm,
    ParcialResultadoForm,
    PeriodoForm,
    PracaBTUForm,
    UploadBaseForm,
)
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
    enviar_tarefas_todos,
    enviar_teste,
    enviar_recompra,
    enviar_recompra_lote,
    enviar_venda_indevida,
    enviar_venda_indevida_lote,
    enviar_parcial_especialista,
    enviar_parcial_carteira,
    enviar_parcial_gerencia,
    enviar_parcial_grupos,
    enviar_parcial_pdv,
    enviar_acumulado_pdv,
    enviar_acumulado_todos,
    enviar_ranking,
)
from .messaging.syncwa import (
    alternar_modo_teste_sessao,
    healthcheck,
    listar_grupos,
    modo_teste_ativo,
    modo_teste_sessao,
    syncwa_configurado,
)
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
    PoliticaComissao,
    PracaBTU,
    RelatorioComissionamento,
    RelatorioFPD,
    RelatorioRecompra,
    RelatorioTarefa,
    RelatorioVendaIndevida,
    VendaOSAB,
)
from .destinatarios_especialista import sincronizar_destinatarios_especialistas
from .parceiros import classificar_parceiros_osab, sincronizar_parceiros_osab
from .periodo import periodo_ativo, salvar_periodo
from .pipelines.churn import processar_churn
from .pipelines.comissionamento import mapa_pdv_razoes, processar_comissionamento
from .pipelines.fpd import processar_fpd
from .pipelines.gdp import processar_gdp
from .pipelines.metas import processar_metas
from .pipelines.carteira import processar_carteira
from .pipelines.du_consolidado import aplicar_du_consolidado
from .pipelines.comissao import aplicar_politica_nos_pdvs
from .pipelines.calendario import (
    aplicar_nos_pdvs as aplicar_du_pdvs,
    defaults_osab,
    desmarcar_feriado,
    estrutura_calendario,
    feriados_do_mes,
    marcar_feriado,
    navegacao,
    salvar_lote as salvar_calendario_lote,
    totais_mes,
)
from .pipelines.osab import calcular_osab, persistir_capilaridade, processar_osab, relatorios_osab_atuais
from .pipelines.recompra import processar_recompra
from .pipelines.parcial_vendas import (
    HORARIOS_PARCIAL,
    agrupar_por_especialista,
    linha_pdv,
    processar_parcial_excel,
    sub_parcial,
    turno_parcial,
)
from .pipelines.resultados import (
    cadastrar_praca_btu,
    gaps_ranking,
    linhas_acumulado,
    mensagem_acumulado_consolidada,
    montar_ranking,
)
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


def _pode_enviar(request) -> bool:
    return tem_acesso_interno(request.user) and syncwa_configurado()


def _pode_importar(request) -> bool:
    return pode_importar_bases(request.user)


def _filtros_capilaridade(request) -> dict:
    src = request.POST if request.method == "POST" else request.GET
    return {
        "tt": (src.get("tt") or "").strip(),
        "nome": (src.get("nome") or "").strip(),
        "pdv": (src.get("pdv") or "").strip(),
        "cargo": (src.get("cargo") or "").strip(),
        "situacao": (src.get("situacao") or "").strip(),
    }


def _opcoes_filtro_terceiros(parceiros):
    qs = CadastroTerceiro.objects.filter(parceiro__in=parceiros)
    cargos = sorted(
        {c.strip() for c in qs.exclude(cargo_funcao="").values_list("cargo_funcao", flat=True) if c}
    )
    situacoes = set()
    for emp, fun, con in qs.values_list("situacao_empresa", "situacao_funcional", "situacao_contrato"):
        for valor in (emp, fun, con):
            txt = (valor or "").strip()
            if txt:
                situacoes.add(txt)
    return cargos, sorted(situacoes)


def _parceiros(request):
    return parceiros_gestao(request.user, escopo_gestao(request))


def _filtro_relatorios(request):
    visiveis = _parceiros(request)
    filtro = Q(parceiro__in=visiveis)
    if ve_relatorios_sem_pdv(request.user):
        filtro |= Q(parceiro__isnull=True)
    return visiveis, filtro


def _relatorio_escopo(request, model, pk):
    _, filtro = _filtro_relatorios(request)
    return get_object_or_404(model.objects.filter(filtro), pk=pk)


def _voltar(request, nome: str, extra: str = "") -> HttpResponse:
    qs = f"escopo={escopo_gestao(request)}"
    if extra:
        qs = f"{qs}&{extra}"
    return redirect(f"{reverse(nome)}?{qs}")


def _msg_cadastro_osab(cad: dict) -> str:
    partes = [
        f"{len(cad.get('ja_ok') or [])} já cadastrado(s) com o nome certo",
        f"{len(cad.get('criados') or [])} novo(s)",
    ]
    if cad.get("grafia"):
        partes.append(
            f"{len(cad['grafia'])} com grafia diferente (mantido o cadastro atual)"
        )
    if cad.get("nio_sem_osab"):
        partes.append(
            f"{len(cad['nio_sem_osab'])} do NIO sem nome igual na OSAB (mantidos)"
        )
    novos = cad.get("criados") or []
    extra = ""
    if novos:
        amostra = ", ".join(novos[:8])
        if len(novos) > 8:
            amostra += f"… (+{len(novos) - 8})"
        extra = f" Novos: {amostra}."
    sap_ok = cad.get("codigos_sap") or []
    if sap_ok:
        amostra = ", ".join(sap_ok[:8])
        if len(sap_ok) > 8:
            amostra += f"… (+{len(sap_ok) - 8})"
        extra += f" Códigos PDV_SAP atualizados: {amostra}."
    colisoes = cad.get("sap_colisoes") or []
    if colisoes:
        extra += f" PDV_SAP já usado (código OSAB- mantido): {', '.join(colisoes[:5])}."
    specs = cad.get("especialistas_novos") or []
    if specs:
        extra += f" Especialistas criados: {', '.join(specs)} (defina a senha em Equipe)."
    gerencias = cad.get("gerencias") or []
    if gerencias:
        extra += f" Gerência OSAB preenchida em {len(gerencias)} especialista(s)."
    return "Parceiros da OSAB: " + "; ".join(partes) + "." + extra


def _enviar_todos_pdv(request, enviar_fn, parceiros, titulo: str) -> None:
    from gestao.messaging.envio import ResumoEnvio

    acc = ResumoEnvio()
    for p in parceiros:
        parte = enviar_fn(p, request.user)
        acc.enviados += parte.enviados
        acc.erros += parte.erros
        acc.ignorados += parte.ignorados
        acc.detalhes.extend(parte.detalhes[:1])
    _flash_resumo(request, titulo, acc)


@gestor_required
@require_POST
def gerencia_ativa_view(request: HttpRequest) -> HttpResponse:
    """Troca a gerência das bases da Gestão só nesta sessão (não altera o cadastro)."""
    valor = (request.POST.get("gerencia") or "").strip()
    if valor == GERENCIA_TODAS:
        request.session[GERENCIA_SESSAO] = GERENCIA_TODAS
    else:
        nomes = {g.casefold(): g for g in listar_gerencias()}
        if valor.casefold() in nomes:
            request.session[GERENCIA_SESSAO] = nomes[valor.casefold()]
        else:
            request.session.pop(GERENCIA_SESSAO, None)
    nxt = request.POST.get("next") or reverse("gestao_hub")
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("gestao_hub")
    return redirect(nxt)


@login_required
def hub(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    if request.method == "POST" and _pode_importar(request) and request.POST.get("action") == "periodo":
        form = PeriodoForm(request.POST)
        if form.is_valid():
            salvar_periodo(form.cleaned_data["ano"], form.cleaned_data["mes"])
            messages.success(request, "Período ativo atualizado.")
            return _voltar(request, "gestao_hub")
    else:
        form = PeriodoForm(initial={"ano": ano, "mes": mes})

    visiveis = _parceiros(request)
    ultima_osab = VendaOSAB.objects.filter(parceiro__in=visiveis).aggregate(
        n=Count("id"), dt=Max("data_importacao")
    )
    ultima_sysmap = CadastroTerceiro.objects.filter(parceiro__in=visiveis).aggregate(
        n=Count("id"), dt=Max("data_atualizacao")
    )
    ultima_fpd = RelatorioFPD.objects.filter(parceiro__in=visiveis).aggregate(
        n=Count("id"), dt=Max("criado_em")
    )
    ultima_churn = HistoricoChurn.objects.filter(parceiro__in=visiveis).aggregate(
        n=Count("id"), dt=Max("data_analise")
    )
    lotes = LoteImportacao.objects.all()[:8]
    return render(
        request,
        "gestao/hub.html",
        {
            "ano": ano,
            "mes": mes,
            "periodo_form": form,
            "pode_importar": _pode_importar(request),
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
    if _pode_importar(request):
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
                return _voltar(request, "gestao_sysmap")
            except Exception as exc:
                _lote(request, LoteImportacao.Tipo.SYSMAP, arquivo.name, False, {}, str(exc))
                messages.error(request, f"Falha ao importar Sysmap: {exc}")
    visiveis_ids = set(_parceiros(request).values_list("id", flat=True))
    filtro = Q(parceiro_id__in=visiveis_ids)
    if ve_relatorios_sem_pdv(request.user):
        filtro |= Q(parceiro__isnull=True)
    terceiros = (
        CadastroTerceiro.objects.select_related("parceiro", "parceiro__especialista")
        .filter(filtro)
        .order_by("nome_terceiro")[:400]
    )
    return render(
        request,
        "gestao/sysmap.html",
        {
            "form": form,
            "terceiros": terceiros,
            "total": CadastroTerceiro.objects.filter(filtro).count(),
            "ativos": CadastroTerceiro.objects.filter(filtro, ativo=True).count(),
            "vinculados": CadastroTerceiro.objects.filter(
                filtro, parceiro__isnull=False
            ).count(),
        },
    )


@login_required
def capilaridade_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    filtros = _filtros_capilaridade(request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "recalcular" and _pode_importar(request):
            resumo = persistir_capilaridade(ano, mes)
            messages.success(
                request,
                f"Capilaridade recalculada: {resumo['linhas']} TTs, {resumo['ativos']} ativos.",
            )
            return _voltar(request, "gestao_capilaridade")
        if action in {"enviar_pdv", "enviar_todos"} and _pode_enviar(request):
            parceiros = list(_parceiros(request))
            if filtros.get("pdv"):
                parceiros = [p for p in parceiros if str(p.id) == filtros["pdv"]]
            if action == "enviar_pdv":
                parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
                try:
                    _flash_resumo(
                        request,
                        "Capilaridade",
                        enviar_capilaridade_pdv(parceiro, request.user, filtros),
                    )
                except Exception as exc:
                    messages.error(request, f"Falha ao enviar capilaridade: {exc}")
            else:
                try:
                    _flash_resumo(
                        request,
                        "Capilaridade (todos)",
                        enviar_capilaridade_todos(
                            parceiros, request.user, filtros=filtros
                        ),
                    )
                except Exception as exc:
                    messages.error(request, f"Falha ao enviar capilaridade: {exc}")
            extra = "&".join(
                f"{k}={v}" for k, v in filtros.items() if v
            )
            return _voltar(request, "gestao_capilaridade", extra)

    parceiros = list(_parceiros(request))
    if filtros.get("pdv"):
        parceiros = [p for p in parceiros if str(p.id) == filtros["pdv"]]
    cards = []
    for p in parceiros:
        mascara = montar_mascara_pdv(p, ano, mes, filtros)
        meta = (
            MetaCapilaridade.objects.filter(parceiro=p, ano=ano, mes=mes)
            .values_list("meta_vendedores", flat=True)
            .first()
            or 0
        )
        cards.append({"parceiro": p, "mascara": mascara, "meta": meta})
    cargos, situacoes = _opcoes_filtro_terceiros(_parceiros(request))
    return render(
        request,
        "gestao/capilaridade.html",
        {
            "ano": ano,
            "mes": mes,
            "resumo": resumo_geral(parceiros, ano, mes, filtros),
            "cards": cards,
            "filtros": filtros,
            "cargos": cargos,
            "situacoes": situacoes,
            "parceiros_filtro": _parceiros(request),
            "pode_recalcular": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
            "modo_teste": modo_teste_ativo(),
            "whatsapp_usuario": ""
            if eh_gestor(request.user)
            else (getattr(getattr(request.user, "perfil_staff", None), "whatsapp", "") or "").strip(),
        },
    )


@login_required
def osab_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    visiveis = _parceiros(request)
    historico = relatorios_osab_atuais(
        visiveis, incluir_sem_pdv=ve_relatorios_sem_pdv(request.user)
    )
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "recalcular" and _pode_importar(request):
            resumo = calcular_osab(ano, mes)
            messages.success(request, f"OSAB recalculada: {resumo['pdvs']} PDV(s).")
            return _voltar(request, "gestao_osab")
        if action == "cadastrar_parceiros" and _pode_importar(request):
            cad = sincronizar_parceiros_osab()
            novos = cad["criados"]
            if novos:
                calcular_osab(ano, mes)
            messages.success(
                request,
                _msg_cadastro_osab(cad),
            )
            return _voltar(request, "gestao_osab")
        if action == "enviar_pdv" and _pode_enviar(request):
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(request, "OSAB", enviar_osab_pdv(parceiro, request.user))
            return _voltar(request, "gestao_osab")
        if action == "enviar_todos" and _pode_enviar(request):
            _enviar_todos_pdv(request, enviar_osab_pdv, visiveis, "OSAB (todos)")
            return _voltar(request, "gestao_osab")
        if _pode_importar(request) and request.FILES:
            form = UploadBaseForm(request.POST, request.FILES)
            if form.is_valid():
                arquivo = form.cleaned_data["arquivo"]
                try:
                    resumo = processar_osab(arquivo, arquivo.name, ano, mes)
                    _lote(request, LoteImportacao.Tipo.OSAB, arquivo.name, True, resumo)
                    vendas = resumo["vendas"]
                    cad = resumo.get("parceiros") or {}
                    msg = (
                        f"OSAB atualizada ({mes:02d}/{ano}): {vendas['inseridos']} inseridos, "
                        f"{vendas['atualizados']} atualizados. Capilaridade: {resumo['capilaridade']['linhas']} TTs."
                    )
                    if cad:
                        msg = f"{msg} {_msg_cadastro_osab(cad)}"
                    messages.success(request, msg)
                    return _voltar(request, "gestao_osab")
                except Exception as exc:
                    _lote(request, LoteImportacao.Tipo.OSAB, arquivo.name, False, {}, str(exc))
                    messages.error(request, f"Falha ao importar OSAB: {exc}")
            else:
                messages.error(request, "Selecione um arquivo OSAB válido (.xlsb ou .xlsx).")
    return render(
        request,
        "gestao/osab.html",
        {
            "form": UploadBaseForm() if _pode_importar(request) else None,
            "ano": ano,
            "mes": mes,
            "total_vendas": VendaOSAB.objects.filter(parceiro__in=visiveis).count(),
            "historico": historico,
            "cadastro_osab": classificar_parceiros_osab() if _pode_importar(request) else None,
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
        },
    )


def _parcial_sub(request) -> str:
    sub = (request.GET.get("parcial_sub") or request.POST.get("parcial_sub") or "").strip().lower()
    if sub not in {"gerencia", "consolidado", "especialistas", "parceiros"}:
        sub = "gerencia" if eh_gestor(request.user) else "especialistas"
    if sub in {"gerencia", "consolidado"} and not eh_gestor(request.user):
        sub = "especialistas"
    return sub


def _parcial_extra(request) -> str:
    return f"aba=parcial&parcial_sub={_parcial_sub(request)}"


def _grupos_parcial(parceiros: list[Parceiro]):
    return _grupos_ranking(parceiros)


def _parcial_dados(request) -> dict | None:
    lote = (
        LoteImportacao.objects.filter(
            tipo=LoteImportacao.Tipo.PARCIAL,
            ok=True,
            criado_por=request.user,
        )
        .order_by("-criado_em")
        .first()
    )
    if not lote or not lote.resumo:
        return None
    return lote.resumo


def _grupos_ranking(parceiros: list[Parceiro]):
    ids = [p.pk for p in parceiros]
    return (
        Destinatario.objects.filter(
            ativo=True,
            tipo=Destinatario.TipoDestino.GRUPO,
            envio_resultados=True,
        )
        .filter(Q(ranking_consolidado=True) | Q(parceiro_id__in=ids))
        .select_related("parceiro")
        .order_by("-ranking_consolidado", "parceiro__nome", "prioridade", "nome")
    )


def _grupo_ranking_padrao(grupos) -> Destinatario | None:
    for g in grupos:
        if g.ranking_consolidado and "parceiros_pp" in (g.nome or "").casefold():
            return g
    for g in grupos:
        if g.ranking_consolidado:
            return g
    return grupos[0] if grupos else None


def _buscar_grupo_pp_wa() -> dict | None:
    """Localiza Parceiros_PP_Nio na sessão Evolution (WhatsApp pareado)."""
    if not syncwa_configurado():
        return None
    res = listar_grupos()
    if not res.get("ok"):
        return None
    candidatos: list[dict] = []
    for g in res.get("groups") or []:
        nome = (g.get("name") or "").strip()
        chave = nome.casefold().replace(" ", "_")
        if "parceiros_pp" in chave:
            candidatos.append(
                {
                    "jid": g.get("jid") or "",
                    "name": nome,
                    "size": g.get("size") or "",
                }
            )
    if not candidatos:
        return None
    for c in candidatos:
        if c["name"].casefold().replace(" ", "_") == "parceiros_pp_nio":
            return c
    return candidatos[0]


def _ativar_destinatario_ranking(jid: str, nome: str) -> Destinatario:
    existente = Destinatario.objects.filter(jid=jid).first()
    if existente:
        existente.parceiro = None
        existente.nome = nome[:150]
        existente.tipo = Destinatario.TipoDestino.GRUPO
        existente.ativo = True
        existente.ranking_consolidado = True
        existente.envio_resultados = True
        existente.save(
            update_fields=[
                "parceiro",
                "nome",
                "tipo",
                "ativo",
                "ranking_consolidado",
                "envio_resultados",
                "atualizado_em",
            ]
        )
        return existente
    return Destinatario.objects.create(
        parceiro=None,
        nome=nome[:150],
        jid=jid,
        tipo=Destinatario.TipoDestino.GRUPO,
        ativo=True,
        ranking_consolidado=True,
        envio_resultados=True,
        envio_osab=False,
        envio_capilaridade=False,
        envio_fpd=False,
        envio_churn=False,
    )


@login_required
def exportar_vb_sem_municipio(request: HttpRequest) -> HttpResponse:
    from .planilhas import planilha_vb_sem_municipio

    visiveis = list(_parceiros(request))
    conteudo, nome = planilha_vb_sem_municipio(visiveis)
    resp = HttpResponse(
        conteudo,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


@gestor_required
def toggle_modo_teste_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect(request.META.get("HTTP_REFERER") or reverse("gestao_hub"))
    ativo, msg = alternar_modo_teste_sessao(request)
    if ativo or "desligado" in msg.lower():
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    ref = request.META.get("HTTP_REFERER") or ""
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()}):
        return redirect(ref)
    return redirect("gestao_hub")


@login_required
def ranking_preview(request: HttpRequest) -> HttpResponse:
    from .ranking_imagem import imagem_ranking

    visiveis = list(_parceiros(request))
    ranking = montar_ranking(visiveis)
    png, _ = imagem_ranking(ranking)
    return HttpResponse(png, content_type="image/png")


@login_required
def parcial_preview(request: HttpRequest) -> HttpResponse:
    from .parcial_imagem import (
        imagem_parcial_especialista,
        imagem_parcial_especialistas,
        imagem_parcial_gerencia,
        imagem_parcial_pdv,
    )

    visao = (request.GET.get("visao") or "gerencia").strip().lower()
    dados = _parcial_dados(request)
    if not dados:
        return HttpResponse("Importe a base Excel primeiro.", status=404)
    cache = request.GET.get("_") or ""

    if visao == "consolidado":
        sub = sub_parcial(dados["linhas"], dados, titulo="Carteira PP")
        png, _ = imagem_parcial_especialistas(sub, titulo="Carteira PP")
    elif visao == "especialista":
        esp_raw = (request.GET.get("esp") or "").strip()
        if not esp_raw.isdigit():
            return HttpResponse("Especialista inválido.", status=400)
        grupo = next(
            (
                g
                for g in agrupar_por_especialista(dados["linhas"])
                if g.get("especialista_id") == int(esp_raw)
            ),
            None,
        )
        if not grupo:
            return HttpResponse("Especialista sem PDVs na base.", status=404)
        png, _ = imagem_parcial_especialista(grupo, dados)
    elif visao == "pdv":
        pdv_raw = (request.GET.get("pdv") or "").strip()
        if not pdv_raw.isdigit():
            return HttpResponse("PDV inválido.", status=400)
        linha = linha_pdv(dados, int(pdv_raw))
        if not linha:
            return HttpResponse("PDV fora da base.", status=404)
        png, _ = imagem_parcial_pdv(linha, dados)
    elif visao == "carteira":
        from .pipelines.parcial_vendas import linhas_especialista

        linhas = linhas_especialista(dados, request.user.id)
        sub = sub_parcial(linhas or dados["linhas"], dados, titulo="Minha carteira")
        png, _ = imagem_parcial_especialistas(sub, titulo="Minha carteira")
    else:
        png, _ = imagem_parcial_gerencia(dados)
    del cache
    return HttpResponse(png, content_type="image/png")


@login_required
def resultados_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    visiveis = list(_parceiros(request))
    _, rotulo_turno = turno_parcial()
    parcial_dados = _parcial_dados(request)
    grupos_parcial = list(_grupos_parcial(visiveis))
    form = ParcialResultadoForm(
        request.POST or None,
        request.FILES or None,
        parceiros=Parceiro.objects.filter(pk__in=[p.pk for p in visiveis]),
        grupos=Destinatario.objects.filter(pk__in=[g.pk for g in grupos_parcial]),
        initial={"turno": str(turno_parcial()[0])},
    )
    form_btu = PracaBTUForm(request.POST or None)
    form_gdp = GdpImportForm()

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "importar_gdp" and _pode_importar(request):
            form_gdp = GdpImportForm(request.POST, request.FILES)
            if form_gdp.is_valid():
                arquivos = []
                for chave in ("arquivo_b2c", "arquivo_b2b"):
                    arq = form_gdp.cleaned_data.get(chave)
                    if arq:
                        arquivos.append((arq, arq.name))
                try:
                    nomes = " + ".join(n for _, n in arquivos)
                    resumo = processar_gdp(arquivos)
                    _lote(request, LoteImportacao.Tipo.GDP, nomes, True, resumo)
                    mg = resumo.get("mg") or 0
                    messages.success(
                        request,
                        f"GDP importado: {resumo['especial_uniao']} praça(s) ESPECIAL "
                        f"({mg} em MG). {resumo['inseridos']} novas, "
                        f"{resumo['atualizados']} atualizadas, "
                        f"{resumo['desativados']} saíram da oferta.",
                    )
                except Exception as exc:
                    _lote(
                        request,
                        LoteImportacao.Tipo.GDP,
                        " + ".join(n for _, n in arquivos) or "gdp.xlsx",
                        False,
                        {},
                        str(exc),
                    )
                    messages.error(request, f"Falha ao importar GDP: {exc}")
            else:
                messages.error(request, "Envie o GDP B2C e/ou B2B em .xlsx.")
            return _voltar(request, "gestao_resultados", extra="aba=ranking")
        if action == "add_praca_btu" and _pode_importar(request):
            form_btu = PracaBTUForm(request.POST)
            if form_btu.is_valid():
                try:
                    praca = cadastrar_praca_btu(form_btu.cleaned_data["nome"])
                    messages.success(request, f"Praça BTU cadastrada: {praca.nome}.")
                except ValueError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, "Informe o município BTU.")
            return _voltar(request, "gestao_resultados", extra="aba=ranking")
        if action == "del_praca_btu" and _pode_importar(request):
            pk = request.POST.get("praca")
            apagada, _ = PracaBTU.objects.filter(pk=pk).delete()
            if apagada:
                messages.success(request, "Praça BTU removida.")
            return _voltar(request, "gestao_resultados", extra="aba=ranking")
        if action == "importar_parcial" and _pode_importar(request):
            form = ParcialResultadoForm(
                request.POST,
                request.FILES,
                parceiros=Parceiro.objects.filter(pk__in=[p.pk for p in visiveis]),
                grupos=Destinatario.objects.filter(pk__in=[g.pk for g in grupos_parcial]),
            )
            if form.is_valid():
                arquivo = form.cleaned_data.get("arquivo")
                if not arquivo:
                    messages.error(request, "Envie a base Excel com PDV, total e D-7.")
                    return _voltar(request, "gestao_resultados", extra="aba=parcial&parcial_sub=gerencia")
                try:
                    resumo = processar_parcial_excel(
                        arquivo,
                        arquivo.name,
                        visiveis,
                        turno=form.turno_int(),
                        ano=ano,
                        mes=mes,
                    )
                    _lote(request, LoteImportacao.Tipo.PARCIAL, arquivo.name, True, resumo)
                    aviso = ""
                    if resumo.get("sem_cadastro"):
                        aviso = f" {len(resumo['sem_cadastro'])} PDV(s) da planilha sem cadastro."
                    messages.success(
                        request,
                        f"Base importada: {resumo['qtd_pdvs']} PDV(s) · total {resumo['total_pp']} VB · "
                        f"∆ D-7 {resumo['delta_pp']:+d} · turno {resumo['rotulo_turno']}.{aviso}",
                    )
                except Exception as exc:
                    _lote(request, LoteImportacao.Tipo.PARCIAL, arquivo.name, False, {}, str(exc))
                    messages.error(request, f"Falha ao importar parcial: {exc}")
            else:
                messages.error(request, "Envie a base Excel com PDV, total e D-7.")
            return _voltar(request, "gestao_resultados", extra="aba=parcial&parcial_sub=gerencia")
        if action in {
            "enviar_parcial_gerencia",
            "enviar_parcial_carteira",
            "enviar_parcial_especialista",
            "enviar_parcial_grupos",
            "enviar_parcial_pdv",
        } and _pode_enviar(request):
            dados = _parcial_dados(request)
            if not dados:
                messages.error(request, "Importe a base Excel antes de enviar.")
                return _voltar(request, "gestao_resultados", extra=_parcial_extra(request))
            if action == "enviar_parcial_gerencia":
                dest_raw = (request.POST.get("destinatario") or "").strip()
                dest_id = int(dest_raw) if dest_raw.isdigit() else None
                _flash_resumo(
                    request,
                    "Parcial gerência",
                    enviar_parcial_gerencia(
                        dados,
                        request.user,
                        destinatario_id=dest_id,
                        parceiros=visiveis,
                    ),
                )
            elif action == "enviar_parcial_carteira":
                _flash_resumo(
                    request,
                    "Parcial carteira",
                    enviar_parcial_carteira(visiveis, request.user, dados),
                )
            elif action == "enviar_parcial_especialista":
                esp_raw = (request.POST.get("especialista") or "").strip()
                if not esp_raw.isdigit():
                    messages.error(request, "Especialista inválido.")
                else:
                    _flash_resumo(
                        request,
                        "Parcial especialista",
                        enviar_parcial_especialista(
                            dados,
                            request.user,
                            especialista_id=int(esp_raw),
                        ),
                    )
            elif action == "enviar_parcial_grupos":
                _flash_resumo(
                    request,
                    "Parcial grupos",
                    enviar_parcial_grupos(visiveis, request.user, dados),
                )
            else:
                parceiro = get_object_or_404(
                    Parceiro.objects.filter(pk__in=[p.pk for p in visiveis]),
                    pk=request.POST.get("parceiro"),
                )
                _flash_resumo(
                    request,
                    "Parcial PDV",
                    enviar_parcial_pdv(parceiro, request.user, dados),
                )
            return _voltar(request, "gestao_resultados", extra=_parcial_extra(request))
        if action == "enviar_acumulado_pdv" and _pode_enviar(request):
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(
                request,
                "Acumulado",
                enviar_acumulado_pdv(parceiro, request.user, ano=ano, mes=mes),
            )
            return _voltar(request, "gestao_resultados")
        if action == "enviar_acumulado_todos" and _pode_enviar(request):
            _flash_resumo(
                request,
                "Acumulado (todos)",
                enviar_acumulado_todos(visiveis, request.user, ano=ano, mes=mes),
            )
            return _voltar(request, "gestao_resultados")
        if action == "ativar_grupo_ranking_pp" and eh_gestor(request.user):
            grupo_wa = _buscar_grupo_pp_wa()
            jid = (request.POST.get("jid") or "").strip() or (grupo_wa or {}).get("jid", "")
            nome = (request.POST.get("nome") or "").strip() or (grupo_wa or {}).get("name") or "Parceiros_PP_Nio"
            if not jid or "@g.us" not in jid:
                messages.error(
                    request,
                    "Não foi possível obter o JID do grupo. Abra Destinatários → Listar grupos WhatsApp.",
                )
            else:
                dest = _ativar_destinatario_ranking(jid, nome)
                messages.success(
                    request,
                    f"Grupo «{dest.nome}» ativado para o Ranking VB. Agora é só clicar em Enviar imagem no grupo.",
                )
            return _voltar(request, "gestao_resultados", extra="aba=ranking")
        if action == "enviar_ranking" and _pode_enviar(request):
            dest_raw = (request.POST.get("destinatario") or "").strip()
            dest_id = int(dest_raw) if dest_raw.isdigit() else None
            _flash_resumo(
                request,
                "Ranking VB",
                enviar_ranking(visiveis, request.user, destinatario_id=dest_id),
            )
            return _voltar(request, "gestao_resultados", extra="aba=ranking")

    acumulado = linhas_acumulado(visiveis, ano, mes)
    ranking = montar_ranking(visiveis)
    pracas_ativas = PracaBTU.objects.filter(ativo=True)
    aba = (request.GET.get("aba") or "parcial").strip().lower()
    if aba not in {"parcial", "acumulado", "ranking"}:
        aba = "parcial"
    grupos_ranking = list(_grupos_ranking(visiveis))
    grupo_pp_wa = _buscar_grupo_pp_wa() if not grupos_ranking else None
    parcial_sub = _parcial_sub(request)
    parcial_especialistas = []
    parcial_pdvs = []
    if parcial_dados:
        todos_grupos = agrupar_por_especialista(parcial_dados.get("linhas") or [])
        if eh_gestor(request.user):
            parcial_especialistas = todos_grupos
        else:
            parcial_especialistas = [
                g for g in todos_grupos if g.get("especialista_id") == request.user.id
            ]
        ids_visiveis = {p.pk for p in visiveis}
        for linha in parcial_dados.get("linhas") or []:
            pid = linha.get("parceiro_id")
            if pid in ids_visiveis:
                parcial_pdvs.append(linha)
        parcial_pdvs.sort(key=lambda l: l.get("pdv", "").upper())
    ultimo_parcial = LoteImportacao.objects.filter(
        tipo=LoteImportacao.Tipo.PARCIAL, ok=True, criado_por=request.user
    ).first()
    return render(
        request,
        "gestao/resultados.html",
        {
            "aba": aba,
            "ano": ano,
            "mes": mes,
            "form": form,
            "form_btu": form_btu if _pode_importar(request) else None,
            "form_gdp": form_gdp if _pode_importar(request) else None,
            "acumulado": acumulado,
            "msg_acumulado": mensagem_acumulado_consolidada(acumulado),
            "ranking": ranking,
            "gaps_ranking": gaps_ranking(ranking),
            "grupos_ranking": grupos_ranking,
            "grupos_parcial": grupos_parcial,
            "parcial_dados": parcial_dados,
            "parcial_sub": parcial_sub,
            "parcial_especialistas": parcial_especialistas,
            "parcial_pdvs": parcial_pdvs,
            "parcial_turno": rotulo_turno,
            "parcial_horarios": HORARIOS_PARCIAL,
            "ultimo_parcial": ultimo_parcial,
            "ranking_grupo_padrao": _grupo_ranking_padrao(grupos_ranking),
            "grupo_pp_wa": grupo_pp_wa,
            "pracas_btu": pracas_ativas,
            "pracas_btu_mg": pracas_ativas.filter(uf="MG").count(),
            "ultimo_gdp": LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.GDP).first(),
            "pode_enviar": _pode_enviar(request),
            "pode_editar": _pode_importar(request),
            "eh_gestor": eh_gestor(request.user),
        },
    )


@login_required
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
            return _voltar(request, "gestao_fpd")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha ao importar FPD: {exc}")
    return _render_fpd(request, form)


@login_required
def fpd_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "enviar_pdv" and _pode_enviar(request):
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(request, "FPD", enviar_fpd_pdv(parceiro, request.user))
            return _voltar(request, "gestao_fpd")
        if action == "enviar_todos" and _pode_enviar(request):
            ids = (
                RelatorioFPD.objects.filter(parceiro__in=_parceiros(request))
                .values_list("parceiro_id", flat=True)
                .distinct()
            )
            _enviar_todos_pdv(
                request,
                enviar_fpd_pdv,
                _parceiros(request).filter(id__in=ids),
                "FPD (todos)",
            )
            return _voltar(request, "gestao_fpd")
        if _pode_importar(request) and request.FILES:
            return importar_fpd_view(request)
    return _render_fpd(request, UploadBaseForm() if _pode_importar(request) else None)


def _render_fpd(request, form):
    from django.db.models import Max

    visiveis = _parceiros(request)
    ultimos_ids = (
        RelatorioFPD.objects.filter(parceiro__in=visiveis)
        .values("parceiro_id")
        .annotate(ultimo_id=Max("id"))
        .values_list("ultimo_id", flat=True)
    )
    relatorios = (
        RelatorioFPD.objects.select_related("parceiro__especialista", "lote")
        .filter(id__in=ultimos_ids)
        .order_by("-percentual", "pdv_nome")
    )
    return render(
        request,
        "gestao/fpd.html",
        {"form": form, "relatorios": relatorios, "pode_importar": _pode_importar(request), "pode_enviar": _pode_enviar(request)},
    )


@login_required
def importar_churn_view(request: HttpRequest) -> HttpResponse:
    form = UploadBaseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        try:
            resumo = processar_churn(arquivo, arquivo.name)
            _lote(request, LoteImportacao.Tipo.CHURN, arquivo.name, True, resumo)
            messages.success(request, f"Churn processado: {resumo['pdvs']} PDV(s), {resumo['linhas']} safras.")
            return _voltar(request, "gestao_churn")
        except Exception as exc:
            _lote(request, LoteImportacao.Tipo.CHURN, arquivo.name, False, {}, str(exc))
            messages.error(request, f"Falha ao importar Churn: {exc}")
    return _render_churn(request, form)


@login_required
def churn_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and request.POST.get("action") == "gross":
        return gross_salvar(request)
    if request.method == "POST" and request.POST.get("action") == "enviar_pdv" and _pode_enviar(request):
        parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
        _flash_resumo(request, "Churn", enviar_churn_pdv(parceiro, request.user))
        return _voltar(request, "gestao_churn")
    if request.method == "POST" and request.POST.get("action") == "enviar_todos" and _pode_enviar(request):
        ids = (
            HistoricoChurn.objects.filter(parceiro__in=_parceiros(request))
            .exclude(mensagem="")
            .values_list("parceiro_id", flat=True)
            .distinct()
        )
        _enviar_todos_pdv(
            request,
            enviar_churn_pdv,
            _parceiros(request).filter(id__in=ids),
            "Churn (todos)",
        )
        return _voltar(request, "gestao_churn")
    if request.method == "POST" and _pode_importar(request) and request.FILES:
        return importar_churn_view(request)
    return _render_churn(request, UploadBaseForm() if _pode_importar(request) else None)


@login_required
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
    return _voltar(request, "gestao_churn")


def _render_churn(request, form):
    visiveis = _parceiros(request)
    ultima = HistoricoChurn.objects.order_by("-data_analise").values_list("data_analise", flat=True).first()
    historico = HistoricoChurn.objects.select_related("parceiro__especialista").none()
    if ultima:
        historico = HistoricoChurn.objects.select_related("parceiro__especialista").filter(
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
            "gross_form": GrossForm() if _pode_importar(request) else None,
            "historico": historico,
            "mensagens": mensagens,
            "gross": GrossMensal.objects.select_related("parceiro").filter(parceiro__in=visiveis).order_by("-anomes")[:40],
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
        },
    )


@login_required
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
                    enviar_comissionamento_lote(
                        lote.id, request.user, parceiros=_parceiros(request)
                    ),
                )
            return _voltar(request, "gestao_comissionamento")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha no comissionamento: {exc}")
    return _render_comissionamento(request, form)


@login_required
def comissionamento_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "enviar_pdv" and _pode_enviar(request):
            parceiro = get_object_or_404(_parceiros(request), pk=request.POST.get("parceiro"))
            _flash_resumo(request, "Comissionamento", enviar_comissionamento_pdv(parceiro, request.user))
            return _voltar(request, "gestao_comissionamento")
        if action == "enviar_lote" and _pode_enviar(request):
            lote_id = request.POST.get("lote")
            if not lote_id:
                messages.error(request, "Informe o lote.")
            else:
                _flash_resumo(
                    request,
                    "Comissionamento (lote)",
                    enviar_comissionamento_lote(
                        int(lote_id), request.user, parceiros=_parceiros(request)
                    ),
                )
            return _voltar(request, "gestao_comissionamento")
        if _pode_importar(request) and request.FILES:
            return importar_comissionamento_view(request)
    return _render_comissionamento(
        request, UploadBaseForm() if _pode_importar(request) else None
    )


def _render_comissionamento(request, form):
    visiveis = _parceiros(request)
    relatorios = (
        RelatorioComissionamento.objects.select_related("parceiro__especialista", "lote")
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
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@login_required
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
                _flash_resumo(
                    request,
                    "Envio tarefas",
                    enviar_tarefas_lote(
                        lote.id, request.user, parceiros=_parceiros(request)
                    ),
                )
            return _voltar(request, "gestao_tarefas")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Tarefas: {exc}")
    return _render_tarefas(request, form)


@login_required
def tarefas_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio") and _pode_enviar(request):
            rel = _relatorio_escopo(request, RelatorioTarefa, request.POST.get("relatorio"))
            _flash_resumo(request, "Tarefas", enviar_tarefa(rel, request.user))
            return _voltar(request, "gestao_tarefas")
        if action == "enviar_lote" and request.POST.get("lote") and _pode_enviar(request):
            _flash_resumo(
                request,
                "Tarefas (lote)",
                enviar_tarefas_lote(
                    int(request.POST.get("lote")),
                    request.user,
                    parceiros=_parceiros(request),
                ),
            )
            return _voltar(request, "gestao_tarefas")
        if action == "enviar_todos" and _pode_enviar(request):
            _flash_resumo(
                request,
                "Tarefas (todos)",
                enviar_tarefas_todos(_parceiros(request), request.user),
            )
            return _voltar(request, "gestao_tarefas")
        if _pode_importar(request) and request.FILES:
            return importar_tarefas_view(request)
    return _render_tarefas(request, UploadBaseForm() if _pode_importar(request) else None)


def _render_tarefas(request, form):
    visiveis, filtro = _filtro_relatorios(request)
    relatorios = RelatorioTarefa.objects.select_related("parceiro__especialista", "lote").filter(
        filtro
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.TAREFAS, ok=True)[:15]
    return render(
        request,
        "gestao/tarefas.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@login_required
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
                    enviar_venda_indevida_lote(lote.id, request.user, parceiros=_parceiros(request)),
                )
            return _voltar(request, "gestao_venda_indevida")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Venda indevida: {exc}")
    return _render_venda_indevida(request, form)


@login_required
def venda_indevida_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio") and _pode_enviar(request):
            rel = _relatorio_escopo(
                request, RelatorioVendaIndevida, request.POST.get("relatorio")
            )
            _flash_resumo(request, "Venda indevida", enviar_venda_indevida(rel, request.user))
            return _voltar(request, "gestao_venda_indevida")
        if action == "enviar_lote" and request.POST.get("lote") and _pode_enviar(request):
            _flash_resumo(
                request,
                "VI (lote)",
                enviar_venda_indevida_lote(
                    int(request.POST.get("lote")),
                    request.user,
                    parceiros=_parceiros(request),
                ),
            )
            return _voltar(request, "gestao_venda_indevida")
        if _pode_importar(request) and request.FILES:
            return importar_venda_indevida_view(request)
    return _render_venda_indevida(
        request, UploadBaseForm() if _pode_importar(request) else None
    )


def _render_venda_indevida(request, form):
    visiveis, filtro = _filtro_relatorios(request)
    relatorios = RelatorioVendaIndevida.objects.select_related("parceiro__especialista", "lote").filter(
        filtro
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.VENDA_INDEVIDA, ok=True)[:15]
    return render(
        request,
        "gestao/venda_indevida.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@login_required
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
                _flash_resumo(
                    request,
                    "Envio recompra",
                    enviar_recompra_lote(
                        lote.id, request.user, parceiros=_parceiros(request)
                    ),
                )
            return _voltar(request, "gestao_recompra")
        except Exception as exc:
            lote.ok = False
            lote.erro = str(exc)
            lote.save(update_fields=["ok", "erro"])
            messages.error(request, f"Falha em Recompra: {exc}")
    return _render_recompra(request, form)


@login_required
def recompra_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "enviar" and request.POST.get("relatorio") and _pode_enviar(request):
            rel = _relatorio_escopo(request, RelatorioRecompra, request.POST.get("relatorio"))
            _flash_resumo(request, "Recompra", enviar_recompra(rel, request.user))
            return _voltar(request, "gestao_recompra")
        if action == "enviar_lote" and request.POST.get("lote") and _pode_enviar(request):
            _flash_resumo(
                request,
                "Recompra (lote)",
                enviar_recompra_lote(
                    int(request.POST.get("lote")),
                    request.user,
                    parceiros=_parceiros(request),
                ),
            )
            return _voltar(request, "gestao_recompra")
        if _pode_importar(request) and request.FILES:
            return importar_recompra_view(request)
    return _render_recompra(request, UploadBaseForm() if _pode_importar(request) else None)


def _render_recompra(request, form):
    visiveis, filtro = _filtro_relatorios(request)
    relatorios = RelatorioRecompra.objects.select_related("parceiro__especialista", "lote").filter(
        filtro
    )[:80]
    lotes = LoteImportacao.objects.filter(tipo=LoteImportacao.Tipo.RECOMPRA, ok=True)[:15]
    return render(
        request,
        "gestao/recompra.html",
        {
            "form": form,
            "relatorios": relatorios,
            "lotes": lotes,
            "pode_importar": _pode_importar(request),
            "pode_enviar": _pode_enviar(request),
            "syncwa_ok": syncwa_configurado(),
        },
    )


@login_required
def configs_view(request: HttpRequest) -> HttpResponse:
    ano, mes = periodo_ativo()
    parceiros = list(_parceiros(request))
    form_import = UploadBaseForm() if _pode_importar(request) else None
    aba = (request.GET.get("aba") or "metas").strip().lower()
    if aba not in ("importar", "calendario", "comissao", "metas"):
        aba = "metas"
    if aba == "importar" and not form_import:
        aba = "metas"
    aba_qs = f"aba={aba}"
    if request.method == "POST":
        action = request.POST.get("action") or "salvar"
        post_aba = (request.POST.get("aba") or aba).strip().lower()
        if post_aba in ("importar", "calendario", "comissao", "metas"):
            aba_qs = f"aba={post_aba}"
        if action == "importar_metas":
            if not _pode_importar(request):
                messages.error(request, "Sem permissão para importar metas.")
                return _voltar(request, "gestao_configs", aba_qs)
            form_import = UploadBaseForm(
                request.POST, request.FILES, extensoes=[".xlsx", ".xlsb", ".xls"]
            )
            if form_import.is_valid():
                arquivo = form_import.cleaned_data["arquivo"]
                try:
                    resumo = processar_metas(arquivo, arquivo.name, ano, mes)
                    _lote(request, LoteImportacao.Tipo.METAS, arquivo.name, True, resumo)
                    du = ""
                    if resumo.get("du_vl") is not None:
                        du = f" DU VL {resumo['du_vl']:.2f} · DU Gross {resumo['du_gross']:.2f}."
                    extra = ""
                    if resumo.get("sem_cadastro_n"):
                        extra = (
                            f" {resumo['sem_cadastro_n']} PDV(s) da base sem cadastro"
                            f" (ex.: {', '.join(resumo['sem_cadastro'][:5])})."
                        )
                    messages.success(
                        request,
                        f"Metas {mes:02d}/{ano}: {resumo['atualizados']} PDV(s) atualizados."
                        f"{du}{extra}",
                    )
                    return _voltar(request, "gestao_configs", aba_qs)
                except Exception as exc:
                    _lote(request, LoteImportacao.Tipo.METAS, arquivo.name, False, {}, str(exc))
                    messages.error(request, f"Falha ao importar metas: {exc}")
            else:
                messages.error(request, "Selecione o acompanhamento semanal (.xlsb ou .xlsx).")
            return _voltar(request, "gestao_configs", aba_qs)
        if action == "importar_du_consolidado":
            if not _pode_importar(request):
                messages.error(request, "Sem permissão para importar DU.")
                return _voltar(request, "gestao_configs", aba_qs)
            form_du = UploadBaseForm(
                request.POST, request.FILES, extensoes=[".xlsx", ".xlsb", ".xls"]
            )
            if form_du.is_valid():
                arquivo = form_du.cleaned_data["arquivo"]
                try:
                    resumo = aplicar_du_consolidado(arquivo, arquivo.name, ano, mes)
                    messages.success(
                        request,
                        f"DU consolidado {mes:02d}/{ano}: VL {resumo['du_vl']:.2f} · "
                        f"Gross {resumo['du_gross']:.2f}. Aplicado em {resumo['pdvs_atualizados']} PDV(s).",
                    )
                    return _voltar(request, "gestao_configs", "aba=calendario")
                except Exception as exc:
                    messages.error(request, f"Falha ao importar DU consolidado: {exc}")
            else:
                messages.error(request, "Selecione o Consolidado_DU (.xlsx).")
            return _voltar(request, "gestao_configs", "aba=calendario")
        if not eh_gestor(request.user):
            messages.error(request, "Só o admin altera metas, política e calendário.")
            return _voltar(request, "gestao_configs", aba_qs)
        if action == "salvar_politica":
            politica = PoliticaComissao.vigente()
            campos = [
                "comissao_400",
                "comissao_400_btu",
                "comissao_500",
                "comissao_500_btu",
                "comissao_600",
                "comissao_600_btu",
                "comissao_800",
                "comissao_800_btu",
                "comissao_1000",
                "comissao_1000_btu",
                "comissao_1000_mesh",
                "comissao_1000_mesh_btu",
                "comissao_fixo",
                "comissao_globoplay_anuncios",
                "comissao_globoplay_premium",
                "comissao_max",
                "comissao_paramount",
                "bonus_m10",
            ]
            for campo in campos:
                if campo in request.POST:
                    setattr(politica, campo, int(request.POST.get(campo) or 0))
            politica.save()
            n = aplicar_politica_nos_pdvs(politica, ano, mes)
            messages.success(
                request,
                f"Política PAP salva. Comissões 500/800/1Gb copiadas para {n} PDV(s) do período.",
            )
            return _voltar(request, "gestao_configs", "aba=comissao")
        if action == "salvar_calendario":
            salvar_calendario_lote(
                request.POST.getlist("dia_id"),
                request.POST.getlist("peso_vl"),
                request.POST.getlist("peso_gross"),
                request.POST.getlist("observacao_dia"),
            )
            n = aplicar_du_pdvs(ano, mes)
            tot = totais_mes(ano, mes)
            messages.success(
                request,
                f"Calendário DU {mes:02d}/{ano}: VL {tot['du_vl']:.2f} · Gross {tot['du_gross']:.2f}. "
                f"Aplicado em {n} PDV(s).",
            )
            return _voltar(request, "gestao_configs", "aba=calendario")
        if action == "add_feriado":
            raw = (request.POST.get("feriado_data") or "").strip()
            desc = (request.POST.get("feriado_desc") or "Feriado").strip()
            try:
                partes = raw.replace("/", "-").split("-")
                if len(partes) == 3 and len(partes[0]) == 4:
                    dia = date(int(partes[0]), int(partes[1]), int(partes[2]))
                else:
                    dia = date(int(partes[2]), int(partes[1]), int(partes[0]))
                marcar_feriado(dia, desc)
                aplicar_du_pdvs(ano, mes)
                messages.success(request, f"Feriado {dia.strftime('%d/%m/%Y')} com peso 0.")
            except (TypeError, ValueError, IndexError):
                messages.error(request, "Informe a data do feriado (dd/mm/aaaa).")
            return _voltar(request, "gestao_configs", "aba=calendario")
        if action == "del_feriado":
            try:
                desmarcar_feriado(int(request.POST.get("feriado_id") or 0))
                aplicar_du_pdvs(ano, mes)
                messages.success(request, "Feriado removido e o dia voltou ao peso padrão.")
            except (TypeError, ValueError):
                messages.error(request, "Não foi possível remover o feriado.")
            return _voltar(request, "gestao_configs", "aba=calendario")
        du_padrao = defaults_osab(ano, mes)
        for p in parceiros:
            prefix = f"p{p.id}_"
            meta_v = int(request.POST.get(prefix + "meta_vendedores") or 0)
            MetaCapilaridade.objects.update_or_create(
                parceiro=p, ano=ano, mes=mes, defaults={"meta_vendedores": meta_v}
            )
            du_vl = float(request.POST.get(prefix + "du_vl") or 0)
            du_gross = float(request.POST.get(prefix + "du_gross") or 0)
            osab_defaults = {
                "meta_vl": int(request.POST.get(prefix + "meta_vl") or 0),
                "du_vl": du_vl,
                "meta_gross": int(request.POST.get(prefix + "meta_gross") or 0),
                "du_gross": du_gross,
                "tem_bonus": prefix + "tem_bonus" in request.POST,
                "comissao_bonus": int(request.POST.get(prefix + "comissao_bonus") or 0),
                "tem_bonus_m10": prefix + "tem_bonus_m10" in request.POST,
            }
            if du_padrao:
                if du_vl <= 0:
                    osab_defaults["du_vl"] = du_padrao["du_vl"]
                    osab_defaults["pesos_diarios_vl"] = du_padrao["pesos_diarios_vl"]
                if du_gross <= 0:
                    osab_defaults["du_gross"] = du_padrao["du_gross"]
                    osab_defaults["pesos_diarios_gross"] = du_padrao["pesos_diarios_gross"]
                if du_vl <= 0 or du_gross <= 0:
                    osab_defaults.setdefault("pesos_diarios_vl", du_padrao["pesos_diarios_vl"])
                    osab_defaults.setdefault("pesos_diarios_gross", du_padrao["pesos_diarios_gross"])
            ConfiguracaoOSAB.objects.update_or_create(
                parceiro=p,
                ano=ano,
                mes=mes,
                defaults=osab_defaults,
            )
        messages.success(request, f"Metas salvas para {mes:02d}/{ano}.")
        return _voltar(request, "gestao_configs", "aba=metas")

    metas = {(m.parceiro_id): m for m in MetaCapilaridade.objects.filter(ano=ano, mes=mes)}
    configs = {(c.parceiro_id): c for c in ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes)}
    linhas = []
    for p in parceiros:
        linhas.append({"parceiro": p, "meta": metas.get(p.id), "osab": configs.get(p.id)})
    nav = navegacao(ano, mes)
    tot_cal = totais_mes(ano, mes)
    return render(
        request,
        "gestao/configs.html",
        {
            "ano": ano,
            "mes": mes,
            "linhas": linhas,
            "pode_editar": eh_gestor(request.user),
            "form_import": form_import,
            "politica": PoliticaComissao.vigente(),
            "calendario": estrutura_calendario(ano, mes),
            "calendario_totais": tot_cal,
            "feriados": feriados_do_mes(ano, mes),
            "cal_nav": nav,
            "aba": aba,
        },
    )


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
    visiveis = parceiros_para_destinatarios(request.user)
    if request.method == "POST" and request.POST.get("action") == "sincronizar_especialistas":
        cad = sincronizar_destinatarios_especialistas(visiveis)
        partes = [
            f"{len(cad['criados'])} criado(s)",
            f"{len(cad['atualizados'])} atualizado(s)",
        ]
        if cad.get("removidos"):
            partes.append(
                f"{len(cad['removidos'])} removido(s) dos PDVs do admin (número próprio)"
            )
        extra = ""
        if cad["sem_whatsapp"]:
            extra += (
                f" Sem WhatsApp no cadastro: {', '.join(cad['sem_whatsapp'][:8])}"
                f"{'…' if len(cad['sem_whatsapp']) > 8 else ''}."
            )
        if cad["sem_especialista"]:
            extra += f" Sem especialista: {len(cad['sem_especialista'])} PDV(s)."
        messages.success(
            request,
            "Destinatários com o WhatsApp do especialista: "
            + "; ".join(partes)
            + "."
            + extra,
        )
        return _voltar(request, "gestao_destinatarios")
    form = DestinatarioForm(request.POST or None)
    form.fields["parceiro"].queryset = visiveis
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Destinatário salvo.")
        return _voltar(request, "gestao_destinatarios")
    lista = Destinatario.objects.select_related(
        "parceiro",
        "parceiro__especialista",
        "parceiro__especialista__perfil_staff",
    ).filter(parceiro__in=visiveis)
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
            "parceiros": visiveis,
        },
    )


@gestor_required
def destinatario_do_grupo(request: HttpRequest) -> HttpResponse:
    """Cadastra rápido um grupo WhatsApp como destinatário de um PDV ou ranking consolidado."""
    if request.method != "POST":
        return _voltar(request, "gestao_destinatarios")
    parceiro_id = (request.POST.get("parceiro") or "").strip()
    ranking_consolidado = request.POST.get("ranking_consolidado") == "1"
    jid = (request.POST.get("jid") or "").strip()
    nome = (request.POST.get("nome") or "").strip() or jid
    if not jid or "@g.us" not in jid:
        messages.error(request, "Informe um JID de grupo válido (@g.us).")
        return redirect(f"{reverse('gestao_destinatarios')}?grupos=1")
    if ranking_consolidado:
        existente = Destinatario.objects.filter(jid=jid, ranking_consolidado=True).first()
        if existente:
            existente.nome = nome[:150]
            existente.envio_resultados = True
            existente.ativo = True
            existente.save(update_fields=["nome", "envio_resultados", "ativo", "atualizado_em"])
            messages.success(request, f"Grupo «{nome}» atualizado para ranking consolidado.")
            return _voltar(request, "gestao_destinatarios")
        Destinatario.objects.create(
            parceiro=None,
            nome=nome[:150],
            jid=jid,
            tipo=Destinatario.TipoDestino.GRUPO,
            ativo=True,
            ranking_consolidado=True,
            envio_resultados=True,
            envio_osab=False,
            envio_capilaridade=False,
            envio_fpd=False,
            envio_churn=False,
        )
        messages.success(
            request,
            f"Grupo «{nome}» vinculado ao Ranking VB consolidado. "
            f"Aparece em Resultados → Ranking de VB.",
        )
        return _voltar(request, "gestao_destinatarios")
    if not parceiro_id:
        messages.error(request, "Informe o PDV ou marque Ranking consolidado.")
        return redirect(f"{reverse('gestao_destinatarios')}?grupos=1")
    parceiro = get_object_or_404(Parceiro, pk=parceiro_id, ativo=True)
    existente = Destinatario.objects.filter(parceiro=parceiro, jid=jid).first()
    if existente:
        messages.warning(request, f"Já existe destinatário {existente.nome} com este JID neste PDV.")
        return _voltar(request, "gestao_destinatarios")
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
    return _voltar(request, "gestao_destinatarios")


@gestor_required
def destinatario_editar(request: HttpRequest, pk: int) -> HttpResponse:
    dest = get_object_or_404(Destinatario, pk=pk)
    form = DestinatarioForm(request.POST or None, instance=dest)
    form.fields["parceiro"].queryset = parceiros_para_destinatarios(request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Destinatário atualizado.")
        return _voltar(request, "gestao_destinatarios")
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
    return _voltar(request, "gestao_destinatarios")


@gestor_required
def destinatario_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    dest = get_object_or_404(Destinatario, pk=pk)
    if request.method == "POST":
        dest.ativo = not dest.ativo
        dest.save(update_fields=["ativo", "atualizado_em"])
        messages.success(request, f"{dest.nome}: {'ativo' if dest.ativo else 'inativo'}.")
    return _voltar(request, "gestao_destinatarios")


@login_required
def envios_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and _pode_enviar(request):
        action = request.POST.get("action") or ""
        parceiro_id = request.POST.get("parceiro") or ""
        parceiro = None
        if parceiro_id:
            parceiro = get_object_or_404(_parceiros(request), pk=parceiro_id)

        if action == "teste":
            _flash_resumo(request, "Teste WhatsApp", enviar_teste(request.user))
            return _voltar(request, "gestao_envios")
        if action == "capilaridade":
            if parceiro:
                _flash_resumo(request, "Capilaridade", enviar_capilaridade_pdv(parceiro, request.user))
            else:
                _flash_resumo(
                    request,
                    "Capilaridade (todos)",
                    enviar_capilaridade_todos(list(_parceiros(request)), request.user),
                )
            return _voltar(request, "gestao_envios")
        if action == "resumo_capilaridade":
            _flash_resumo(
                request,
                "Resumo capilaridade",
                enviar_resumo_capilaridade(list(_parceiros(request)), request.user),
            )
            return _voltar(request, "gestao_envios")
        if action == "osab":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar OSAB.")
            else:
                _flash_resumo(request, "OSAB", enviar_osab_pdv(parceiro, request.user))
            return _voltar(request, "gestao_envios")
        if action == "fpd":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar FPD.")
            else:
                _flash_resumo(request, "FPD", enviar_fpd_pdv(parceiro, request.user))
            return _voltar(request, "gestao_envios")
        if action == "churn":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar Churn.")
            else:
                _flash_resumo(request, "Churn", enviar_churn_pdv(parceiro, request.user))
            return _voltar(request, "gestao_envios")
        if action == "comissionamento":
            if not parceiro:
                messages.error(request, "Escolha o PDV para enviar Comissionamento.")
            else:
                _flash_resumo(
                    request,
                    "Comissionamento",
                    enviar_comissionamento_pdv(parceiro, request.user),
                )
            return _voltar(request, "gestao_envios")
        if action == "tarefas":
            if parceiro:
                rel = (
                    RelatorioTarefa.objects.filter(parceiro=parceiro)
                    .order_by("-criado_em")
                    .first()
                )
            elif ve_relatorios_sem_pdv(request.user):
                rel = (
                    RelatorioTarefa.objects.filter(parceiro__isnull=True)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                messages.error(
                    request,
                    "Escolha o PDV. O consolidado de tarefas mistura gerências.",
                )
                return _voltar(request, "gestao_envios")
            if not rel:
                messages.error(request, "Nenhum relatório de tarefas para enviar.")
            else:
                _flash_resumo(request, "Tarefas", enviar_tarefa(rel, request.user))
            return _voltar(request, "gestao_envios")
        if action == "venda_indevida":
            if parceiro:
                rel = (
                    RelatorioVendaIndevida.objects.filter(parceiro=parceiro, consolidado=False)
                    .order_by("-criado_em")
                    .first()
                )
            elif ve_relatorios_sem_pdv(request.user):
                rel = (
                    RelatorioVendaIndevida.objects.filter(consolidado=True)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                messages.error(
                    request,
                    "Escolha o PDV. O consolidado de venda indevida mistura gerências.",
                )
                return _voltar(request, "gestao_envios")
            if not rel:
                messages.error(request, "Nenhum relatório de venda indevida para enviar.")
            else:
                _flash_resumo(request, "Venda indevida", enviar_venda_indevida(rel, request.user))
            return _voltar(request, "gestao_envios")
        if action == "recompra":
            if parceiro:
                rel = (
                    RelatorioRecompra.objects.filter(parceiro=parceiro, consolidado=False)
                    .order_by("-criado_em")
                    .first()
                )
            elif ve_relatorios_sem_pdv(request.user):
                rel = (
                    RelatorioRecompra.objects.filter(consolidado=True)
                    .order_by("-criado_em")
                    .first()
                )
            else:
                messages.error(
                    request,
                    "Escolha o PDV. O consolidado de recompra mistura gerências.",
                )
                return _voltar(request, "gestao_envios")
            if not rel:
                messages.error(request, "Nenhum relatório de recompra para enviar.")
            else:
                _flash_resumo(request, "Recompra", enviar_recompra(rel, request.user))
            return _voltar(request, "gestao_envios")

    health = healthcheck() if syncwa_configurado() else {"ok": False, "error": "não configurado"}
    _, filtro_logs = _filtro_relatorios(request)
    logs = EnvioWhatsApp.objects.select_related("parceiro__especialista", "destinatario").filter(
        filtro_logs
    )
    if not eh_gestor(request.user):
        logs = logs.filter(criado_por=request.user)
    logs = logs[:60]
    return render(
        request,
        "gestao/envios.html",
        {
            "parceiros": _parceiros(request),
            "pode_enviar": _pode_enviar(request),
            "syncwa_ok": syncwa_configurado(),
            "modo_teste": modo_teste_ativo(),
            "health": health,
            "logs": logs,
            "qtd_destinatarios": Destinatario.objects.filter(ativo=True).count(),
        },
    )
