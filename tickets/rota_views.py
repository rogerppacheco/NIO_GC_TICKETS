# -*- coding: utf-8 -*-
"""Views do card Rota (portal parceiro)."""
from __future__ import annotations

import json
import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from tickets.consultas.dfv_powerbi_service import (
    DfvPowerBiDisabled,
    DfvPowerBiError,
    DfvPowerBiTimeout,
    consultar_agregado_por_bairro,
    listar_bairros_dfv,
)
from tickets.models import CheckinRotaDiaria
from tickets.rota_services import (
    classificar_alerta,
    defaults_localizacao,
    eh_segunda,
    hoje_local,
    listar_bairros_parceiro,
    listar_cidades,
    listar_ufs,
    meta_semana_parceiro,
    salvar_checkin,
    serializar_checkin,
    serializar_planejamento,
    segunda_da_semana,
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


def _exige_portal(request: HttpRequest):
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return None, None, _json_error(
            "unauthenticated",
            "Identifique o PDV e o contato para usar a Rota.",
            status=401,
        )
    return parceiro, contato, None


def _parse_json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@login_required
def rota_portal(request: HttpRequest) -> HttpResponse:
    """Página do check-in diário de rota."""
    parceiro, contato = _portal_sessao(request)
    if not parceiro or not contato:
        return redirect(f"{reverse('portal_contato')}?next=rota")
    return render(
        request,
        "tickets/rota_portal.html",
        {
            "parceiro": parceiro,
            "contato": contato,
        },
    )


@login_required
@require_GET
def rota_api_hoje(request: HttpRequest) -> JsonResponse:
    parceiro, contato, err = _exige_portal(request)
    if err:
        return err

    hoje = hoje_local()
    checkin = CheckinRotaDiaria.objects.filter(parceiro=parceiro, data=hoje).select_related(
        "planejamento"
    ).first()
    from tickets.models import PlanejamentoSemanalRota

    plan = PlanejamentoSemanalRota.objects.filter(
        parceiro=parceiro, semana_inicio=segunda_da_semana(hoje)
    ).first()
    if checkin and checkin.planejamento_id:
        plan = checkin.planejamento

    return _json_ok(
        {
            "data": hoje.isoformat(),
            "eh_segunda": eh_segunda(hoje),
            "checkin": serializar_checkin(checkin),
            "planejamento_semana": serializar_planejamento(plan),
            "defaults": defaults_localizacao(parceiro),
            "meta_semana": meta_semana_parceiro(parceiro, hoje),
            "permissoes": {
                "pode_registrar": True,
                "pode_editar": True,
            },
        }
    )


@login_required
@require_GET
def rota_api_ufs(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_portal(request)
    if err:
        return err
    return _json_ok({"items": listar_ufs(parceiro)})


@login_required
@require_GET
def rota_api_cidades(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_portal(request)
    if err:
        return err
    uf = (request.GET.get("uf") or "").strip().upper()
    if len(uf) != 2:
        return _json_error("validation_error", "Informe a UF.", fields={"uf": "Obrigatório."})
    return _json_ok({"uf": uf, "items": listar_cidades(parceiro, uf)})


@login_required
@require_GET
def rota_api_bairros(request: HttpRequest) -> JsonResponse:
    parceiro, _contato, err = _exige_portal(request)
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
            # UI ainda permite digitar bairro manualmente
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
    _parceiro, _contato, err = _exige_portal(request)
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
    parceiro, _contato, err = _exige_portal(request)
    if err:
        return err
    body = _parse_json(request)
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
    parceiro, contato, err = _exige_portal(request)
    if err:
        return err

    body = _parse_json(request)
    fields: dict[str, str] = {}

    tipo = str(body.get("tipo_rota") or "").strip().upper()
    if tipo not in CheckinRotaDiaria.TipoRota.values:
        fields["tipo_rota"] = "Informe Presencial ou Digital."

    try:
        qtd = int(body.get("qtd_vendedores"))
        if qtd < 1:
            fields["qtd_vendedores"] = "Informe um número maior que zero."
    except (TypeError, ValueError):
        qtd = 0
        fields["qtd_vendedores"] = "Informe um número maior que zero."

    uf = str(body.get("uf") or "").strip().upper()[:2]
    cidade = str(body.get("cidade") or "").strip()
    bairro = str(body.get("bairro") or "").strip()

    if tipo == CheckinRotaDiaria.TipoRota.PRESENCIAL:
        if len(uf) != 2:
            fields["uf"] = "Obrigatório."
        if not cidade:
            fields["cidade"] = "Obrigatório."
        if not bairro:
            fields["bairro"] = "Obrigatório."

    vendas_semana = body.get("vendas_planejadas_semana", None)
    if eh_segunda():
        if vendas_semana is None or str(vendas_semana).strip() == "":
            fields["vendas_planejadas_semana"] = "Obrigatório às segundas-feiras."
            vendas_int = None
        else:
            try:
                vendas_int = int(vendas_semana)
                if vendas_int < 0:
                    fields["vendas_planejadas_semana"] = "Deve ser >= 0."
            except (TypeError, ValueError):
                fields["vendas_planejadas_semana"] = "Número inválido."
                vendas_int = None
    else:
        vendas_int = None

    if fields:
        return _json_error(
            "validation_error",
            "Dados inválidos.",
            status=422,
            fields=fields,
        )

    dfv_resumo = None
    if tipo == CheckinRotaDiaria.TipoRota.PRESENCIAL and uf and cidade and bairro:
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
            # Permite salvar sem snapshot se DFV falhar (alerta no payload vazio)
            dfv_resumo = None

    try:
        checkin = salvar_checkin(
            parceiro=parceiro,
            contato=contato,
            tipo_rota=tipo,
            qtd_vendedores=qtd,
            uf=uf,
            cidade=cidade,
            bairro=bairro,
            vendas_planejadas_semana=vendas_int,
            dfv_resumo=dfv_resumo,
        )
    except ValueError as exc:
        return _json_error("validation_error", str(exc), status=422)

    created = checkin.criado_em == checkin.atualizado_em
    return _json_ok(serializar_checkin(checkin), status=201 if created else 200)
