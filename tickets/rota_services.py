# -*- coding: utf-8 -*-
"""Regras de negócio do card Rota (check-in diário / planejamento semanal)."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tickets.acesso import parceiros_visiveis
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
ATUACOES_EQUIPE = frozenset({"PAP", "DIGITAL", "MISTO"})
MAX_EQUIPES = 12
MAX_PESSOAS_EQUIPE = 80


def hoje_local() -> date:
    return timezone.localdate()


def segunda_da_semana(dia: date | None = None) -> date:
    ref = dia or hoje_local()
    return ref - timedelta(days=ref.weekday())


def eh_segunda(dia: date | None = None) -> bool:
    return (dia or hoje_local()).weekday() == 0


def domingo_da_semana(dia: date | None = None) -> date:
    return segunda_da_semana(dia) + timedelta(days=6)


def data_na_semana_atual(dia: date, ref: date | None = None) -> bool:
    ancora = ref or hoje_local()
    return segunda_da_semana(ancora) <= dia <= domingo_da_semana(ancora)


def dias_da_semana(ref: date | None = None) -> list[dict[str, Any]]:
    ini = segunda_da_semana(ref)
    hoje = hoje_local()
    labels = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
    saida = []
    for i, label in enumerate(labels):
        dia = ini + timedelta(days=i)
        saida.append(
            {
                "data": dia.isoformat(),
                "label": label,
                "weekday": i,
                "eh_hoje": dia == hoje,
                "eh_segunda": i == 0,
            }
        )
    return saida


def tipo_para_atuacao(tipo_rota: str) -> str:
    tipo = (tipo_rota or "").strip().upper()
    if tipo == CheckinRotaDiaria.TipoRota.DIGITAL:
        return CheckinRotaDiaria.AtuacaoEquipe.DIGITAL
    if tipo == CheckinRotaDiaria.TipoRota.MISTO:
        return CheckinRotaDiaria.AtuacaoEquipe.MISTO
    return CheckinRotaDiaria.AtuacaoEquipe.PAP


def normalizar_equipes(
    equipes: Any,
    qtd_vendedores: int | None = None,
    tipo_rota: str = "",
) -> list[dict[str, Any]]:
    limpos: list[dict[str, Any]] = []
    if isinstance(equipes, list):
        for raw in equipes:
            if not isinstance(raw, dict):
                continue
            atuacao = str(raw.get("atuacao") or "").strip().upper()
            if atuacao not in ATUACOES_EQUIPE:
                continue
            try:
                pessoas = int(raw.get("pessoas"))
            except (TypeError, ValueError):
                continue
            if pessoas < 1:
                continue
            limpos.append(
                {
                    "ordem": len(limpos) + 1,
                    "atuacao": atuacao,
                    "pessoas": min(pessoas, MAX_PESSOAS_EQUIPE),
                }
            )
            if len(limpos) >= MAX_EQUIPES:
                break
    if limpos:
        return limpos
    pessoas = int(qtd_vendedores or 0)
    if pessoas < 1:
        raise ValueError("Informe quantas pessoas atuam em cada equipe.")
    return [
        {
            "ordem": 1,
            "atuacao": tipo_para_atuacao(tipo_rota),
            "pessoas": min(pessoas, MAX_PESSOAS_EQUIPE),
        }
    ]


def derivar_tipo_rota(equipes: list[dict[str, Any]]) -> str:
    modos = {e["atuacao"] for e in equipes}
    if modos == {CheckinRotaDiaria.AtuacaoEquipe.DIGITAL}:
        return CheckinRotaDiaria.TipoRota.DIGITAL
    if modos == {CheckinRotaDiaria.AtuacaoEquipe.PAP}:
        return CheckinRotaDiaria.TipoRota.PAP
    return CheckinRotaDiaria.TipoRota.MISTO


def precisa_local(equipes: list[dict[str, Any]]) -> bool:
    return any(e["atuacao"] != CheckinRotaDiaria.AtuacaoEquipe.DIGITAL for e in equipes)


def equipes_do_checkin(checkin: CheckinRotaDiaria) -> list[dict[str, Any]]:
    if checkin.equipes:
        return checkin.equipes
    return [
        {
            "ordem": 1,
            "atuacao": tipo_para_atuacao(checkin.tipo_rota),
            "pessoas": checkin.qtd_vendedores,
        }
    ]


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
    equipes = equipes_do_checkin(checkin)
    total_campo = sum(int(e.get("pessoas") or 0) for e in equipes)
    return {
        "id": checkin.id,
        "data": checkin.data.isoformat(),
        "tipo_rota": checkin.tipo_rota,
        "qtd_vendedores": checkin.qtd_vendedores,
        "qtd_equipes": checkin.qtd_equipes or len(equipes),
        "equipes": equipes,
        "total_campo": total_campo,
        "qtd_contratacoes": checkin.qtd_contratacoes,
        "qtd_desligamentos": checkin.qtd_desligamentos,
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


def resumo_semana(parceiro: Parceiro, ref: date | None = None) -> dict[str, Any]:
    ini = segunda_da_semana(ref)
    fim = domingo_da_semana(ref)
    por_dia = {
        item.data: item
        for item in CheckinRotaDiaria.objects.filter(parceiro=parceiro, data__range=(ini, fim))
    }
    dias = []
    for slot in dias_da_semana(ref):
        ck = por_dia.get(date.fromisoformat(slot["data"]))
        item = {**slot, "preenchido": bool(ck)}
        if ck:
            item["qtd_equipes"] = ck.qtd_equipes or 1
            item["qtd_vendedores"] = ck.qtd_vendedores
            item["tipo_rota"] = ck.tipo_rota
        dias.append(item)
    return {
        "semana_inicio": ini.isoformat(),
        "semana_fim": fim.isoformat(),
        "dias": dias,
    }


def agendas_equipe(user, q: str = "") -> dict[str, Any]:
    qs = parceiros_visiveis(user).filter(ativo=True)
    termo = (q or "").strip()
    if termo:
        qs = qs.filter(Q(codigo_pdv__icontains=termo) | Q(nome__icontains=termo))
    pdvs = list(qs.order_by("nome", "codigo_pdv")[:80])
    ini = segunda_da_semana()
    fim = domingo_da_semana()
    checkins = CheckinRotaDiaria.objects.filter(
        parceiro_id__in=[p.id for p in pdvs], data__range=(ini, fim)
    )
    por_pdv: dict[int, dict[str, dict[str, Any]]] = {}
    for ck in checkins:
        por_pdv.setdefault(ck.parceiro_id, {})[ck.data.isoformat()] = {
            "qtd_equipes": ck.qtd_equipes or 1,
            "qtd_vendedores": ck.qtd_vendedores,
            "tipo_rota": ck.tipo_rota,
        }
    items = []
    for pdv in pdvs:
        mapa = por_pdv.get(pdv.id, {})
        items.append(
            {
                "id": pdv.id,
                "codigo_pdv": pdv.codigo_pdv,
                "nome": pdv.nome,
                "dias": mapa,
                "preenchidos": len(mapa),
            }
        )
    return {
        "semana_inicio": ini.isoformat(),
        "semana_fim": fim.isoformat(),
        "total": len(items),
        "items": items,
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
    seen: set[str] = set()
    items: list[dict[str, str]] = []

    def _add(uf_raw: str, origem: str) -> None:
        uf = (uf_raw or "").strip().upper()[:2]
        if len(uf) != 2 or uf in seen:
            return
        seen.add(uf)
        items.append({"uf": uf, "origem": origem})

    for u in ParceiroPraca.objects.filter(parceiro=parceiro, ativo=True).values_list(
        "uf", flat=True
    ):
        _add(u, "praca_parceiro")

    if items:
        return sorted(items, key=lambda x: x["uf"])

    # Fallback: UFs com praça BTU
    try:
        from gestao.models import PracaBTU

        for u in PracaBTU.objects.filter(ativo=True).exclude(uf="").values_list(
            "uf", flat=True
        ):
            _add(u, "catalogo")
    except Exception:
        pass
    return sorted(items, key=lambda x: x["uf"])


def listar_cidades(parceiro: Parceiro, uf: str) -> list[dict[str, str]]:
    uf_limpo = (uf or "").strip().upper()[:2]
    if not uf_limpo:
        return []
    seen: set[str] = set()
    items: list[dict[str, str]] = []

    def _add(cidade_raw: str, origem: str) -> None:
        cidade = (cidade_raw or "").strip()
        if not cidade:
            return
        key = cidade.casefold()
        if key in seen:
            return
        seen.add(key)
        items.append({"cidade": cidade, "origem": origem})

    for c in ParceiroPraca.objects.filter(
        parceiro=parceiro, ativo=True, uf=uf_limpo
    ).values_list("cidade", flat=True):
        _add(c, "praca_parceiro")

    if items:
        return sorted(items, key=lambda x: x["cidade"].upper())

    try:
        from gestao.models import PracaBTU

        for c in PracaBTU.objects.filter(ativo=True, uf=uf_limpo).values_list(
            "nome", flat=True
        ):
            _add(c, "catalogo")
    except Exception:
        pass
    return sorted(items, key=lambda x: x["cidade"].upper())


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
    contato: ContatoParceiro | None = None,
    user=None,
    tipo_rota: str = "",
    qtd_vendedores: int = 0,
    uf: str = "",
    cidade: str = "",
    bairro: str = "",
    vendas_planejadas_semana: Optional[int] = None,
    dfv_resumo: Optional[dict[str, Any]] = None,
    dia: date | None = None,
    equipes: Any = None,
    qtd_contratacoes: int = 0,
    qtd_desligamentos: int = 0,
) -> CheckinRotaDiaria:
    ref = dia or hoje_local()
    if not data_na_semana_atual(ref):
        raise ValueError("Só é possível registrar a semana atual (segunda a domingo).")

    equipes_ok = normalizar_equipes(equipes, qtd_vendedores, tipo_rota)
    tipo = derivar_tipo_rota(equipes_ok)
    pessoas = sum(int(e["pessoas"]) for e in equipes_ok)
    if pessoas < 1:
        raise ValueError("Informe quantas pessoas atuam em cada equipe.")
    if int(qtd_contratacoes) < 0 or int(qtd_desligamentos) < 0:
        raise ValueError("Contratações e desligamentos não podem ser negativos.")

    uf_limpo = (uf or "").strip().upper()[:2]
    cidade_txt = (cidade or "").strip()
    bairro_txt = (bairro or "").strip()

    if precisa_local(equipes_ok):
        if not uf_limpo or not cidade_txt or not bairro_txt:
            raise ValueError("UF, cidade e bairro são obrigatórios quando há equipe PAP ou mista.")

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

    defaults = {
        "tipo_rota": tipo,
        "qtd_vendedores": pessoas,
        "qtd_equipes": len(equipes_ok),
        "equipes": equipes_ok,
        "qtd_contratacoes": int(qtd_contratacoes),
        "qtd_desligamentos": int(qtd_desligamentos),
        "uf": uf_limpo,
        "cidade": cidade_txt,
        "bairro": bairro_txt,
        "hp_livres": hp_livres,
        "faixa_credito": faixa,
        "alerta_dfv": alerta,
        "dfv_payload": payload,
        "planejamento": planejamento,
        "criado_por": contato,
    }
    if user is not None:
        defaults["criado_por_user"] = user

    checkin, _created = CheckinRotaDiaria.objects.update_or_create(
        parceiro=parceiro,
        data=ref,
        defaults=defaults,
    )
    return checkin
