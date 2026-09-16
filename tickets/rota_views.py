# -*- coding: utf-8 -*-
"""Views do card Rota (portal parceiro e equipe)."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from tickets.acesso import parceiros_visiveis, tem_acesso_interno
from tickets.consultas.dfv_powerbi_service import (
    DfvPowerBiDisabled,
    DfvPowerBiError,
    DfvPowerBiTimeout,
    consultar_agregado_por_bairro,
    listar_bairros_dfv,
)
from tickets.models import CheckinRotaDiaria, PlanejamentoSemanalRota
from tickets.rota_services import (
    agendas_equipe,
    classificar_alerta,
    data_na_semana_atual,
    defaults_localizacao,
    dias_da_semana,
    domingo_da_semana,
    eh_segunda,
    hoje_local,
    listar_bairros_parceiro,
    listar_cidades,
    listar_ufs,
    meta_semana_parceiro,
    normalizar_equipes,
    precisa_local,
    resumo_semana,
    salvar_checkin,
    segunda_da_semana,
    serializar_checkin,
    serializar_planejamento,
)
from tickets.views import _portal_sessao

logger = logging.getLogger(__name__)


def _json_error(
    code: str,
    message: str,
    status: int = 400,
    fields: dict[str, str] | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
            },
        },
        status=status,
    )


def _json_ok(data: Any, status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data}, status=status)


def _parse_json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _int_campo(valor: Any, default: int | None = None) -> int | None:
    if valor is None or valor == "":
        return default
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _exige_rota(request: HttpRequest, *, exige_pdv: bool = True, body: dict | None = None):
    user = request.user
    if tem_acesso_interno(user):
        qs = parceiros_visiveis(user)
        raw = ""
        if body:
            raw = str(body.get("pdv") or "").strip()
        if not raw:
            raw = (request.GET.get("pdv") or "").strip()
        pdv = None
        if raw:
            try:
                pdv = qs.filter(pk=int(raw)).first()
            except (TypeError, ValueError):
                pdv = None
            if not pdv:
                return None, None, _json_error("not_found", "PDV não encontrado.", status=404)
        if exige_pdv and not pdv:
            return None, None, _json_error(
                "validation_error",
                "Selecione o PDV.",
                status=422,
                fields={"pdv": "Obrigatório."},
            )
        return pdv, None, None

    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return None, None, _json_error(
            "unauthenticated",
            "Identifique o PDV e o contato para usar a Rota.",
            status=401,
        )
    return parceiro, contato, None


def _serial_pdv(parceiro) -> dict[str, Any] | None:
    if not parceiro:
        return None
    return {"id": parceiro.id, "codigo_pdv": parceiro.codigo_pdv, "nome": parceiro.nome}


@login_required
def rota_portal(request: HttpRequest) -> HttpResponse:
    """Página do check-in diário de rota."""
    if tem_acesso_interno(request.user):
        return render(
            request,
            "tickets/rota_portal.html",
            {
                "parceiro": None,
                "contato": None,
                "visao_equipe": True,
            },
        )
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return redirect(f"{reverse('portal_contato')}?next=rota")
    return render(
        request,
        "tickets/rota_portal.html",
        {
            "parceiro": parceiro,
            "contato": contato,
            "visao_equipe": False,
        },
    )


@login_required
@require_GET
def rota_api_hoje(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_rota(
        request, exige_pdv=not tem_acesso_interno(request.user)
    )
    if err:
        return err

    hoje = hoje_local()
    raw_dia = (request.GET.get("data") or "").strip()
    dia = hoje
    if raw_dia:
        try:
            dia = date.fromisoformat(raw_dia)
        except ValueError:
            return _json_error("validation_error", "Data inválida.", fields={"data": "Use AAAA-MM-DD."})
        if not data_na_semana_atual(dia):
            return _json_error(
                "validation_error",
                "Só é possível ver a semana atual.",
                fields={"data": "Fora da semana corrente."},
            )

    checkin = None
    plan = None
    defaults = {"uf": "", "cidade": "", "pracas": []}
    meta = {"fonte": "", "valor": 0, "meta_mensal_vl": 0, "plano_dia": 0, "meta_vendedores": 0}
    semana = {
        "semana_inicio": segunda_da_semana(hoje).isoformat(),
        "semana_fim": domingo_da_semana(hoje).isoformat(),
        "dias": dias_da_semana(hoje),
    }
    if parceiro:
        semana = resumo_semana(parceiro, hoje)
        checkin = CheckinRotaDiaria.objects.filter(parceiro=parceiro, data=dia).select_related(
            "planejamento"
        ).first()
        plan = PlanejamentoSemanalRota.objects.filter(
            parceiro=parceiro, semana_inicio=segunda_da_semana(hoje)
        ).first()
        if checkin and checkin.planejamento_id:
            plan = checkin.planejamento
        defaults = defaults_localizacao(parceiro)
        meta = meta_semana_parceiro(parceiro, hoje)

    return _json_ok(
        {
            "data": dia.isoformat(),
            "hoje": hoje.isoformat(),
            "eh_segunda": eh_segunda(dia),
            "semana": semana,
            "checkin": serializar_checkin(checkin),
            "planejamento_semana": serializar_planejamento(plan),
            "defaults": defaults,
            "meta_semana": meta,
            "pdv": _serial_pdv(parceiro),
            "visao_equipe": tem_acesso_interno(request.user),
            "permissoes": {
                "pode_registrar": bool(parceiro),
                "pode_editar": bool(parceiro),
            },
        }
    )


@login_required
@require_GET
def rota_api_agendas(request: HttpRequest) -> JsonResponse:
    if not tem_acesso_interno(request.user):
        return _json_error("forbidden", "Agenda consolidada só para a equipe NIO.", status=403)
    raw_dia = (request.GET.get("data") or "").strip()
    dia = hoje_local()
    if raw_dia:
        try:
            dia = date.fromisoformat(raw_dia)
        except ValueError:
            return _json_error("validation_error", "Data inválida.", fields={"data": "Use AAAA-MM-DD."})
    return _json_ok(agendas_equipe(request.user, request.GET.get("q") or "", dia))


@login_required
@require_GET
def rota_api_ufs(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_rota(request)
    if err:
        return err
    return _json_ok({"items": listar_ufs(parceiro)})


@login_required
@require_GET
def rota_api_cidades(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_rota(request)
    if err:
        return err
    uf = (request.GET.get("uf") or "").strip().upper()
    if len(uf) != 2:
        return _json_error("validation_error", "Informe a UF.", fields={"uf": "Obrigatório."})
    return _json_ok({"uf": uf, "items": listar_cidades(parceiro, uf)})


@login_required
@require_GET
def rota_api_bairros(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_rota(request)
    if err:
        return err
    uf = (request.GET.get("uf") or "").strip().upper()
    cidade = (request.GET.get("cidade") or "").strip()
    fields = {}
    if len(uf) != 2:
        fields["uf"] = "Obrigatório."
    if not cidade:
        fields["cidade"] = "Obrigatório."
    if fields:
        return _json_error("validation_error", "Parâmetros inválidos.", fields=fields)

    items = listar_bairros_parceiro(parceiro, uf, cidade)
    fonte = "parceiro_praca"
    if not items:
        try:
            nomes = listar_bairros_dfv(uf, cidade)
            items = [{"bairro": n, "origem": "dfv"} for n in nomes]
            fonte = "dfv_cache" if items else "vazio"
        except DfvPowerBiDisabled:
            fonte = "dfv_disabled"
        except DfvPowerBiTimeout:
            return _json_error(
                "dfv_timeout",
                "Consulta DFV demorou demais ao listar bairros. Tente novamente.",
                status=504,
            )
        except DfvPowerBiError as exc:
            logger.warning("[ROTA] listar bairros DFV: %s", exc)
            fonte = "dfv_erro"
            items = []

    return _json_ok(
        {
            "uf": uf,
            "cidade": cidade,
            "items": items,
            "total": len(items),
            "fonte": fonte,
        }
    )


@login_required
@require_GET
def rota_api_dfv_resumo(request: HttpRequest) -> JsonResponse:
    _parceiro, _contato, err = _exige_rota(request)
    if err:
        return err
    uf = (request.GET.get("uf") or "").strip().upper()
    cidade = (request.GET.get("cidade") or "").strip()
    bairro = (request.GET.get("bairro") or "").strip()
    fields = {}
    if len(uf) != 2:
        fields["uf"] = "Obrigatório."
    if not cidade:
        fields["cidade"] = "Obrigatório."
    if not bairro:
        fields["bairro"] = "Obrigatório."
    if fields:
        return _json_error("validation_error", "Parâmetros inválidos.", fields=fields)

    try:
        resumo = consultar_agregado_por_bairro(uf, cidade, bairro)
    except DfvPowerBiDisabled:
        return _json_error(
            "dfv_unavailable",
            "Consulta DFV está desabilitada no momento.",
            status=503,
        )
    except DfvPowerBiTimeout:
        return _json_error(
            "dfv_timeout",
            "Consulta DFV demorou demais. Tente novamente em instantes.",
            status=504,
        )
    except DfvPowerBiError as exc:
        msg = str(exc)
        if "Nenhum registro" in msg:
            return _json_error("not_found", msg, status=404)
        logger.warning("[ROTA] DFV resumo: %s", exc)
        return _json_error("dfv_unavailable", msg, status=503)

    return _json_ok(resumo)


@login_required
@require_http_methods(["POST"])
def rota_api_planejamento_validar(request: HttpRequest) -> JsonResponse:
    body = _parse_json(request)
    parceiro, _contato, err = _exige_rota(request, body=body)
    if err:
        return err
    try:
        vendas = int(body.get("vendas_planejadas"))
    except (TypeError, ValueError):
        return _json_error(
            "validation_error",
            "Informe vendas_planejadas.",
            fields={"vendas_planejadas": "Número inválido."},
        )
    if vendas < 0:
        return _json_error(
            "validation_error",
            "Valor inválido.",
            fields={"vendas_planejadas": "Deve ser >= 0."},
        )

    meta = meta_semana_parceiro(parceiro)
    meta_ref = int(meta["valor"] or 0)
    status, desvio, msg = classificar_alerta(vendas, meta_ref)
    return _json_ok(
        {
            "vendas_planejadas": vendas,
            "meta_referencia": meta_ref,
            "desvio_pct": desvio,
            "status_alerta": status,
            "mensagem": msg,
            "bloqueia_envio": False,
        }
    )


@login_required
@require_http_methods(["POST", "PUT"])
def rota_api_checkin(request: HttpRequest) -> JsonResponse:
    body = _parse_json(request)
    parceiro, contato, err = _exige_rota(request, body=body)
    if err:
        return err

    fields: dict[str, str] = {}
    hoje = hoje_local()
    raw_dia = str(body.get("data") or "").strip()
    dia = hoje
    if raw_dia:
        try:
            dia = date.fromisoformat(raw_dia)
        except ValueError:
            fields["data"] = "Data inválida."
        else:
            if not data_na_semana_atual(dia):
                fields["data"] = "Só a semana atual (segunda a domingo)."

    equipes = body.get("equipes")
    qtd = _int_campo(body.get("qtd_vendedores"), 0) or 0
    tipo = str(body.get("tipo_rota") or "").strip().upper()
    if not isinstance(equipes, list) or not equipes:
        if tipo not in CheckinRotaDiaria.TipoRota.values:
            fields["equipes"] = "Informe as equipes em campo."
        if qtd < 1 and "equipes" not in fields:
            fields["qtd_vendedores"] = "Informe um número maior que zero."

    contratacoes = _int_campo(body.get("qtd_contratacoes"), 0)
    desligamentos = _int_campo(body.get("qtd_desligamentos"), 0)
    if contratacoes is None or contratacoes < 0:
        fields["qtd_contratacoes"] = "Número inválido."
        contratacoes = 0
    if desligamentos is None or desligamentos < 0:
        fields["qtd_desligamentos"] = "Número inválido."
        desligamentos = 0

    vb_dia = _int_campo(body.get("planejamento_vb_dia"), 0)
    if vb_dia is None or vb_dia < 0:
        fields["planejamento_vb_dia"] = "Informe o planejamento de VBs do dia."
        vb_dia = 0

    uf = str(body.get("uf") or "").strip().upper()[:2]
    cidade = str(body.get("cidade") or "").strip()
    bairro = str(body.get("bairro") or "").strip()

    vendas_semana = body.get("vendas_planejadas_semana", None)
    if eh_segunda(dia) and "data" not in fields:
        if vendas_semana is None or str(vendas_semana).strip() == "":
            fields["vendas_planejadas_semana"] = "Obrigatório às segundas-feiras."
            vendas_int = None
        else:
            vendas_int = _int_campo(vendas_semana)
            if vendas_int is None or vendas_int < 0:
                fields["vendas_planejadas_semana"] = "Número inválido."
                vendas_int = None
    else:
        vendas_int = None

    if fields:
        return _json_error("validation_error", "Dados inválidos.", status=422, fields=fields)

    try:
        equipes_ok = normalizar_equipes(equipes, qtd, tipo)
    except ValueError as exc:
        return _json_error("validation_error", str(exc), status=422, fields={"equipes": str(exc)})

    if precisa_local(equipes_ok):
        loc_fields = {}
        if len(uf) != 2:
            loc_fields["uf"] = "Obrigatório."
        if not cidade:
            loc_fields["cidade"] = "Obrigatório."
        if not bairro:
            loc_fields["bairro"] = "Obrigatório."
        if loc_fields:
            return _json_error("validation_error", "Informe o local da rota.", status=422, fields=loc_fields)

    dfv_resumo = None
    if precisa_local(equipes_ok) and uf and cidade and bairro:
        try:
            dfv_resumo = consultar_agregado_por_bairro(uf, cidade, bairro)
        except DfvPowerBiTimeout:
            return _json_error(
                "dfv_timeout",
                "Não foi possível consultar o DFV a tempo. Tente novamente.",
                status=504,
            )
        except DfvPowerBiDisabled:
            dfv_resumo = None
        except DfvPowerBiError as exc:
            logger.warning("[ROTA] checkin DFV: %s", exc)
            dfv_resumo = None

    try:
        checkin = salvar_checkin(
            parceiro=parceiro,
            contato=contato,
            user=request.user if tem_acesso_interno(request.user) else None,
            tipo_rota=tipo,
            qtd_vendedores=qtd,
            uf=uf,
            cidade=cidade,
            bairro=bairro,
            vendas_planejadas_semana=vendas_int,
            dfv_resumo=dfv_resumo,
            dia=dia,
            equipes=equipes_ok,
            qtd_contratacoes=contratacoes,
            qtd_desligamentos=desligamentos,
            planejamento_vb_dia=vb_dia,
        )
    except ValueError as exc:
        return _json_error("validation_error", str(exc), status=422)

    created = checkin.criado_em == checkin.atualizado_em
    data = serializar_checkin(checkin) or {}
    data["semana"] = resumo_semana(parceiro, hoje)
    return _json_ok(data, status=201 if created else 200)
