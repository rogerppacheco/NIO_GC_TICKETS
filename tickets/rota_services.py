# -*- coding: utf-8 -*-
"""Regras de negócio do card Rota (check-in diário / planejamento semanal)."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from tickets.models import (
    CheckinRotaDiaria,
    ContatoParceiro,
    Parceiro,
    ParceiroPraca,
    PlanejamentoSemanalRota,
)

# Limiares de alerta vs meta semanal (desvio negativo).
ALERTA_ABAIXO_PCT = -10.0  # até -10% = ok; abaixo disso = abaixo
ALERTA_CRITICO_PCT = -30.0  # < -30% = crítico


def hoje_local() -> date:
    return timezone.localdate()


def segunda_da_semana(dia: date | None = None) -> date:
    ref = dia or hoje_local()
    return ref - timedelta(days=ref.weekday())


def eh_segunda(dia: date | None = None) -> bool:
    return (dia or hoje_local()).weekday() == 0


def meta_semana_parceiro(parceiro: Parceiro, dia: date | None = None) -> dict[str, Any]:
    """
    Meta semanal de referência.
    Default: meta_vl mensal / 4 (sem FCAST persistido).
    """
    ref = dia or hoje_local()
    from gestao.models import ConfiguracaoOSAB, MetaCapilaridade

    cfg = ConfiguracaoOSAB.objects.filter(
        parceiro=parceiro, ano=ref.year, mes=ref.month
    ).first()
    cap = MetaCapilaridade.objects.filter(
        parceiro=parceiro, ano=ref.year, mes=ref.month
    ).first()

    meta_vl = int(cfg.meta_vl) if cfg else 0
    plano_dia = float(cfg.plano_dia) if cfg else 0.0
    meta_vendedores = int(cap.meta_vendedores) if cap else 0
    valor = int(math.ceil(meta_vl / 4.0)) if meta_vl else 0

    return {
        "fonte": "derivada_meta_vl",
        "valor": valor,
        "meta_mensal_vl": meta_vl,
        "plano_dia": plano_dia,
        "meta_vendedores": meta_vendedores,
    }


def classificar_alerta(vendas_planejadas: int, meta_referencia: int) -> tuple[str, float | None, str]:
    if not meta_referencia:
        return (
            PlanejamentoSemanalRota.StatusAlerta.OK,
            None,
            "Sem meta semanal de referência cadastrada para o período.",
        )
    desvio = round(100.0 * (vendas_planejadas - meta_referencia) / meta_referencia, 1)
    if desvio <= ALERTA_CRITICO_PCT:
        status = PlanejamentoSemanalRota.StatusAlerta.CRITICO
        msg = f"Planejado {abs(desvio):.0f}% abaixo da meta semanal de referência."
    elif desvio <= ALERTA_ABAIXO_PCT:
        status = PlanejamentoSemanalRota.StatusAlerta.ABAIXO
        msg = f"Planejado {abs(desvio):.0f}% abaixo da meta semanal de referência."
    else:
        status = PlanejamentoSemanalRota.StatusAlerta.OK
        if desvio >= 0:
            msg = "Planejamento alinhado ou acima da meta semanal."
        else:
            msg = "Planejamento dentro da faixa aceitável da meta semanal."
    return status, desvio, msg


def serializar_planejamento(plan: PlanejamentoSemanalRota | None) -> dict[str, Any] | None:
    if not plan:
        return None
    status, desvio, msg = classificar_alerta(plan.vendas_planejadas, plan.meta_referencia)
    # Prefer valores persistidos; recalcula mensagem se status divergir
    desvio = plan.desvio_pct if plan.desvio_pct is not None else desvio
    return {
        "semana_inicio": plan.semana_inicio.isoformat(),
        "vendas_planejadas": plan.vendas_planejadas,
        "meta_referencia": plan.meta_referencia,
        "desvio_pct": desvio,
        "status_alerta": plan.status_alerta or status,
        "mensagem": msg,
    }


def serializar_checkin(checkin: CheckinRotaDiaria | None) -> dict[str, Any] | None:
    if not checkin:
        return None
    return {
        "id": checkin.id,
        "data": checkin.data.isoformat(),
        "tipo_rota": checkin.tipo_rota,
        "qtd_vendedores": checkin.qtd_vendedores,
        "local": {
            "uf": checkin.uf,
            "cidade": checkin.cidade,
            "bairro": checkin.bairro,
        },
        "dfv_snapshot": {
            "hp_livre": checkin.hp_livres,
            "faixa_predominante": checkin.faixa_credito or "—",
            "alertas": (checkin.dfv_payload or {}).get("alertas_codigos")
            or (
                [checkin.alerta_dfv]
                if checkin.alerta_dfv
                else []
            ),
        },
        "planejamento_semana": serializar_planejamento(checkin.planejamento),
        "criado_em": timezone.localtime(checkin.criado_em).isoformat(),
        "atualizado_em": timezone.localtime(checkin.atualizado_em).isoformat(),
    }


def defaults_localizacao(parceiro: Parceiro) -> dict[str, Any]:
    pracas = list(
        ParceiroPraca.objects.filter(parceiro=parceiro, ativo=True).order_by(
            "uf", "cidade", "bairro"
        )
    )
    items = [
        {"uf": p.uf, "cidade": p.cidade, "bairro": p.bairro}
        for p in pracas
    ]
    uf = items[0]["uf"] if items else ""
    cidade = items[0]["cidade"] if items else ""
    # Último check-in presencial como fallback
    if not uf:
        ultimo = (
            CheckinRotaDiaria.objects.filter(parceiro=parceiro)
            .exclude(uf="")
            .order_by("-data")
            .first()
        )
        if ultimo:
            uf = ultimo.uf
            cidade = ultimo.cidade
            items = [{"uf": ultimo.uf, "cidade": ultimo.cidade, "bairro": ultimo.bairro}]
    return {
        "uf": uf,
        "cidade": cidade,
        "pracas": [{"uf": i["uf"], "cidade": i["cidade"]} for i in items],
    }


def listar_ufs(parceiro: Parceiro) -> list[dict[str, str]]:
    pracas = (
        ParceiroPraca.objects.filter(parceiro=parceiro, ativo=True)
        .values_list("uf", flat=True)
        .distinct()
    )
    items = [{"uf": u.upper(), "origem": "praca_parceiro"} for u in pracas if u]
    if items:
        return sorted(items, key=lambda x: x["uf"])

    # Fallback: UFs com praça BTU
    try:
        from gestao.models import PracaBTU

        ufs = (
            PracaBTU.objects.filter(ativo=True)
            .exclude(uf="")
            .values_list("uf", flat=True)
            .distinct()
        )
        return sorted(
            ({"uf": u.upper(), "origem": "catalogo"} for u in ufs if u),
            key=lambda x: x["uf"],
        )
    except Exception:
        return []


def listar_cidades(parceiro: Parceiro, uf: str) -> list[dict[str, str]]:
    uf_limpo = (uf or "").strip().upper()[:2]
    if not uf_limpo:
        return []
    pracas = (
        ParceiroPraca.objects.filter(parceiro=parceiro, ativo=True, uf=uf_limpo)
        .values_list("cidade", flat=True)
        .distinct()
    )
    items = [
        {"cidade": c, "origem": "praca_parceiro"}
        for c in pracas
        if (c or "").strip()
    ]
    if items:
        return sorted(items, key=lambda x: x["cidade"].upper())

    try:
        from gestao.models import PracaBTU

        cidades = (
            PracaBTU.objects.filter(ativo=True, uf=uf_limpo)
            .values_list("nome", flat=True)
            .distinct()
        )
        return sorted(
            ({"cidade": c, "origem": "catalogo"} for c in cidades if c),
            key=lambda x: x["cidade"].upper(),
        )
    except Exception:
        return []


def listar_bairros_parceiro(parceiro: Parceiro, uf: str, cidade: str) -> list[dict[str, str]]:
    uf_limpo = (uf or "").strip().upper()[:2]
    cidade_txt = (cidade or "").strip()
    if not uf_limpo or not cidade_txt:
        return []
    qs = ParceiroPraca.objects.filter(
        parceiro=parceiro, ativo=True, uf=uf_limpo, cidade__iexact=cidade_txt
    ).exclude(bairro="")
    return sorted(
        ({"bairro": b, "origem": "praca_parceiro"} for b in qs.values_list("bairro", flat=True) if b),
        key=lambda x: x["bairro"].upper(),
    )


@transaction.atomic
def salvar_checkin(
    *,
    parceiro: Parceiro,
    contato: ContatoParceiro,
    tipo_rota: str,
    qtd_vendedores: int,
    uf: str = "",
    cidade: str = "",
    bairro: str = "",
    vendas_planejadas_semana: Optional[int] = None,
    dfv_resumo: Optional[dict[str, Any]] = None,
    dia: date | None = None,
) -> CheckinRotaDiaria:
    ref = dia or hoje_local()
    tipo = (tipo_rota or "").strip().upper()
    if tipo not in CheckinRotaDiaria.TipoRota.values:
        raise ValueError("tipo_rota inválido.")
    if qtd_vendedores < 1:
        raise ValueError("qtd_vendedores deve ser >= 1.")

    uf_limpo = (uf or "").strip().upper()[:2]
    cidade_txt = (cidade or "").strip()
    bairro_txt = (bairro or "").strip()

    if tipo == CheckinRotaDiaria.TipoRota.PRESENCIAL:
        if not uf_limpo or not cidade_txt or not bairro_txt:
            raise ValueError("UF, cidade e bairro são obrigatórios para rota presencial.")

    planejamento = None
    if eh_segunda(ref):
        if vendas_planejadas_semana is None:
            raise ValueError("vendas_planejadas_semana é obrigatório às segundas-feiras.")
        if int(vendas_planejadas_semana) < 0:
            raise ValueError("vendas_planejadas_semana inválido.")
        meta = meta_semana_parceiro(parceiro, ref)
        meta_ref = int(meta["valor"] or 0)
        status, _desvio, _msg = classificar_alerta(int(vendas_planejadas_semana), meta_ref)
        planejamento, _ = PlanejamentoSemanalRota.objects.update_or_create(
            parceiro=parceiro,
            semana_inicio=segunda_da_semana(ref),
            defaults={
                "vendas_planejadas": int(vendas_planejadas_semana),
                "meta_referencia": meta_ref,
                "status_alerta": status,
                "criado_por": contato,
            },
        )
    else:
        planejamento = PlanejamentoSemanalRota.objects.filter(
            parceiro=parceiro, semana_inicio=segunda_da_semana(ref)
        ).first()

    hp_livres = None
    faixa = ""
    alerta = ""
    payload: dict[str, Any] = {}
    if dfv_resumo:
        ind = dfv_resumo.get("indicadores") or {}
        cred = dfv_resumo.get("credito") or {}
        alertas = dfv_resumo.get("alertas") or []
        hp_livres = ind.get("hp_livre")
        faixa = str(cred.get("faixa_predominante") or "")[:80]
        alerta = ", ".join(
            a.get("codigo") for a in alertas if isinstance(a, dict) and a.get("codigo")
        )[:255]
        payload = {
            "indicadores": ind,
            "credito": cred,
            "perfil": dfv_resumo.get("perfil") or {},
            "alertas_codigos": [
                a.get("codigo") for a in alertas if isinstance(a, dict) and a.get("codigo")
            ],
            "meta": dfv_resumo.get("meta") or {},
        }

    checkin, _created = CheckinRotaDiaria.objects.update_or_create(
        parceiro=parceiro,
        data=ref,
        defaults={
            "tipo_rota": tipo,
            "qtd_vendedores": int(qtd_vendedores),
            "uf": uf_limpo,
            "cidade": cidade_txt,
            "bairro": bairro_txt,
            "hp_livres": hp_livres,
            "faixa_credito": faixa,
            "alerta_dfv": alerta,
            "dfv_payload": payload,
            "planejamento": planejamento,
            "criado_por": contato,
        },
    )
    return checkin
