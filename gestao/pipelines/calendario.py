from __future__ import annotations

import calendar as calmod
import json
from calendar import monthrange
from datetime import date, timedelta

from ..models import ConfiguracaoOSAB, DiaFiscal

FERIADOS_NACIONAIS = {
    (1, 1): "Ano Novo",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Consciência Negra",
    (12, 25): "Natal",
}

FERIADOS_MOVEIS_2026 = {
    date(2026, 2, 16): "Carnaval (segunda)",
    date(2026, 2, 17): "Carnaval (terça)",
    date(2026, 4, 3): "Sexta-feira Santa",
    date(2026, 6, 4): "Corpus Christi",
}


def pesos_padrao_weekday(dia: date) -> tuple[float, float]:
    """Domingo 0/0; sábado 0,5 VL e 0 Gross; dias úteis 1/1."""
    wd = dia.weekday()
    if wd == 6:
        return 0.0, 0.0
    if wd == 5:
        return 0.5, 0.0
    return 1.0, 1.0


def _feriado_nacional(dia: date) -> str:
    if dia in FERIADOS_MOVEIS_2026:
        return FERIADOS_MOVEIS_2026[dia]
    return FERIADOS_NACIONAIS.get((dia.month, dia.day), "")


def garantir_mes(ano: int, mes: int) -> list[DiaFiscal]:
    ultimo = monthrange(ano, mes)[1]
    existentes = {
        d.data: d
        for d in DiaFiscal.objects.filter(data__range=(date(ano, mes, 1), date(ano, mes, ultimo)))
    }
    out: list[DiaFiscal] = []
    for n in range(1, ultimo + 1):
        atual = date(ano, mes, n)
        if atual in existentes:
            out.append(existentes[atual])
            continue
        nome = _feriado_nacional(atual)
        if nome:
            p_vl, p_gr = 0.0, 0.0
        else:
            p_vl, p_gr = pesos_padrao_weekday(atual)
        obj, _ = DiaFiscal.objects.get_or_create(
            data=atual,
            defaults={
                "peso_vl": p_vl,
                "peso_gross": p_gr,
                "feriado": bool(nome),
                "observacao": nome,
            },
        )
        out.append(obj)
    return out


def estrutura_calendario(ano: int, mes: int) -> list[list[DiaFiscal | None]]:
    dias = {d.data.day: d for d in garantir_mes(ano, mes)}
    grade = []
    for semana in calmod.Calendar(firstweekday=6).monthdayscalendar(ano, mes):
        grade.append([dias.get(n) if n else None for n in semana])
    return grade


def totais_mes(ano: int, mes: int) -> dict:
    garantir_mes(ano, mes)
    ultimo = monthrange(ano, mes)[1]
    qs = DiaFiscal.objects.filter(data__range=(date(ano, mes, 1), date(ano, mes, ultimo)))
    du_vl = round(sum(d.peso_vl for d in qs), 4)
    du_gross = round(sum(d.peso_gross for d in qs), 4)
    return {"du_vl": du_vl, "du_gross": du_gross, "dias": qs.count()}


def pesos_do_mes(ano: int, mes: int) -> dict | None:
    ultimo = monthrange(ano, mes)[1]
    qs = list(DiaFiscal.objects.filter(data__range=(date(ano, mes, 1), date(ano, mes, ultimo))))
    if not qs:
        return None
    vl = {str(d.data.day): float(d.peso_vl) for d in qs}
    gr = {str(d.data.day): float(d.peso_gross) for d in qs}
    for n in range(1, ultimo + 1):
        vl.setdefault(str(n), 0.0)
        gr.setdefault(str(n), 0.0)
    return {
        "vl": vl,
        "gross": gr,
        "du_vl": round(sum(vl.values()), 4),
        "du_gross": round(sum(gr.values()), 4),
        "pesos_diarios_vl": json.dumps({str(d): round(vl.get(str(d), 0.0), 6) for d in range(1, ultimo + 1)}),
        "pesos_diarios_gross": json.dumps({str(d): round(gr.get(str(d), 0.0), 6) for d in range(1, ultimo + 1)}),
    }


def defaults_osab(ano: int, mes: int) -> dict:
    pesos = pesos_do_mes(ano, mes)
    if not pesos:
        return {}
    return {
        "du_vl": pesos["du_vl"],
        "du_gross": pesos["du_gross"],
        "pesos_diarios_vl": pesos["pesos_diarios_vl"],
        "pesos_diarios_gross": pesos["pesos_diarios_gross"],
    }


def aplicar_nos_pdvs(ano: int, mes: int) -> int:
    du = defaults_osab(ano, mes)
    if not du:
        return 0
    n = 0
    for cfg in ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes):
        cfg.du_vl = du["du_vl"]
        cfg.du_gross = du["du_gross"]
        cfg.pesos_diarios_vl = du["pesos_diarios_vl"]
        cfg.pesos_diarios_gross = du["pesos_diarios_gross"]
        cfg.save(update_fields=["du_vl", "du_gross", "pesos_diarios_vl", "pesos_diarios_gross"])
        n += 1
    return n


def salvar_lote(dias_ids: list[str], pesos_vl: list[str], pesos_gr: list[str], obs: list[str]) -> None:
    for i, raw_id in enumerate(dias_ids):
        try:
            dia = DiaFiscal.objects.get(pk=int(raw_id))
            p_vl = (pesos_vl[i] or "").replace(",", ".")
            p_gr = (pesos_gr[i] or "").replace(",", ".")
            dia.peso_vl = float(p_vl) if p_vl else 0.0
            dia.peso_gross = float(p_gr) if p_gr else 0.0
            dia.observacao = (obs[i] or "").strip()
            util = dia.data.weekday() < 5
            if dia.peso_vl == 0 and dia.peso_gross == 0 and util:
                dia.feriado = True
            elif dia.peso_vl or dia.peso_gross:
                dia.feriado = False
            dia.save()
        except (ValueError, DiaFiscal.DoesNotExist, IndexError):
            continue


def marcar_feriado(dia: date, descricao: str) -> DiaFiscal:
    p_vl, p_gr = 0.0, 0.0
    obj, _ = DiaFiscal.objects.update_or_create(
        data=dia,
        defaults={
            "peso_vl": p_vl,
            "peso_gross": p_gr,
            "feriado": True,
            "observacao": (descricao or "Feriado").strip()[:100],
        },
    )
    return obj


def desmarcar_feriado(pk: int) -> None:
    dia = DiaFiscal.objects.filter(pk=pk).first()
    if not dia:
        return
    p_vl, p_gr = pesos_padrao_weekday(dia.data)
    dia.peso_vl = p_vl
    dia.peso_gross = p_gr
    dia.feriado = False
    dia.observacao = ""
    dia.save()


def persistir_de_acompanhamento(ano: int, mes: int, du: dict) -> None:
    pesos_vl = json.loads(du.get("pesos_diarios_vl") or "{}")
    pesos_gr = json.loads(du.get("pesos_diarios_gross") or "{}")
    if not pesos_vl:
        return
    ultimo = monthrange(ano, mes)[1]
    for n in range(1, ultimo + 1):
        atual = date(ano, mes, n)
        p_vl = float(pesos_vl.get(str(n), 0) or 0)
        p_gr = float(pesos_gr.get(str(n), 0) or 0)
        padrao_vl, padrao_gr = pesos_padrao_weekday(atual)
        eh_feriado = p_vl == 0 and p_gr == 0 and padrao_vl > 0
        DiaFiscal.objects.update_or_create(
            data=atual,
            defaults={
                "peso_vl": p_vl,
                "peso_gross": p_gr,
                "feriado": eh_feriado,
                "observacao": "Feriado" if eh_feriado else "",
            },
        )


def feriados_do_mes(ano: int, mes: int) -> list[DiaFiscal]:
    garantir_mes(ano, mes)
    ultimo = monthrange(ano, mes)[1]
    return list(
        DiaFiscal.objects.filter(
            data__range=(date(ano, mes, 1), date(ano, mes, ultimo)),
            feriado=True,
        )
    )


def navegacao(ano: int, mes: int) -> dict:
    ant = date(ano, mes, 1) - timedelta(days=1)
    prox = (date(ano, mes, 1) + timedelta(days=32)).replace(day=1)
    return {"ant": ant, "prox": prox}
