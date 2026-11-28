"""Relatório de evolução mensal de tickets (visão especialista / gerência / geral)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .acesso import gerencia_de, ids_parceiros_da_gerencia, tem_acesso_interno
from .models import StatusTicket, Ticket, TipoDemanda


def _qs_sem_duplicados():
    return Ticket.objects.exclude(
        status=StatusTicket.CANCELADO,
        resultado_status__iexact="DUPLICADO",
    )


def _qs_especialista(user):
    return _qs_sem_duplicados().filter(parceiro__especialista=user)


def _qs_gerencia(user):
    gerencia = gerencia_de(user)
    if not gerencia:
        return _qs_especialista(user)
    return _qs_sem_duplicados().filter(parceiro__in=ids_parceiros_da_gerencia(gerencia))


def _qs_geral():
    return _qs_sem_duplicados()


def _rotulo_mes(dt: date | None) -> str:
    if not dt:
        return ""
    return f"{dt.month:02d}/{dt.year}"


def _tipo_label(codigo: str) -> str:
    try:
        return TipoDemanda(codigo).label
    except ValueError:
        return codigo or "—"


def _agregar(qs) -> dict[str, Any]:
    """Monta matriz mês × tipo + KPIs no estilo do Excel de evolução."""
    qs = qs.exclude(criado_em=None)
    rows = (
        qs.annotate(mes=TruncMonth("criado_em"))
        .values("mes", "tipo")
        .annotate(n=Count("id"))
        .order_by("mes", "tipo")
    )

    por_mes_tipo: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totais_mes: dict[date, int] = defaultdict(int)
    totais_tipo: dict[str, int] = defaultdict(int)

    for row in rows:
        mes = row["mes"]
        if timezone.is_aware(mes):
            mes = timezone.localtime(mes).date().replace(day=1)
        else:
            mes = mes.date().replace(day=1) if hasattr(mes, "date") else mes
        tipo = row["tipo"] or ""
        n = int(row["n"] or 0)
        por_mes_tipo[mes][tipo] += n
        totais_mes[mes] += n
        totais_tipo[tipo] += n

    meses = sorted(totais_mes.keys())
    # Limita aos últimos 6 meses na UI (mantém o Excel-like compacto)
    if len(meses) > 6:
        meses = meses[-6:]

    tipos_ordenados = [
        t for t, _ in sorted(totais_tipo.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    # Colunas principais: top 10 tipos no período exibido
    tipos_periodo: dict[str, int] = defaultdict(int)
    for mes in meses:
        for t, n in por_mes_tipo[mes].items():
            tipos_periodo[t] += n
    tipos_cols = [
        t for t, _ in sorted(tipos_periodo.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:10]

    matriz = []
    for mes in meses:
        celulas = []
        for tipo in tipos_cols:
            celulas.append(
                {
                    "tipo": tipo,
                    "label": _tipo_label(tipo),
                    "n": por_mes_tipo[mes].get(tipo, 0),
                }
            )
        matriz.append(
            {
                "mes": mes,
                "mes_label": _rotulo_mes(mes),
                "total": totais_mes.get(mes, 0),
                "celulas": celulas,
            }
        )

    ultimo = meses[-1] if meses else None
    anterior = meses[-2] if len(meses) >= 2 else None
    tickets_ultimo = totais_mes.get(ultimo, 0) if ultimo else 0
    tickets_anterior = totais_mes.get(anterior, 0) if anterior else 0
    if tickets_anterior:
        variacao_pct = round(
            100.0 * (tickets_ultimo - tickets_anterior) / tickets_anterior, 1
        )
    else:
        variacao_pct = None

    ranking_ultimo = []
    if ultimo:
        ranking_ultimo = sorted(
            (
                {
                    "tipo": t,
                    "label": _tipo_label(t),
                    "n": n,
                }
                for t, n in por_mes_tipo[ultimo].items()
                if n
            ),
            key=lambda x: (-x["n"], x["label"]),
        )[:8]

    serie_total = [
        {"mes_label": _rotulo_mes(m), "total": totais_mes.get(m, 0)} for m in meses
    ]

    return {
        "meses": [_rotulo_mes(m) for m in meses],
        "tipos_cols": [{"tipo": t, "label": _tipo_label(t)} for t in tipos_cols],
        "matriz": matriz,
        "serie_total": serie_total,
        "ranking_ultimo": ranking_ultimo,
        "kpis": {
            "periodo": (
                f"{_rotulo_mes(meses[0])} a {_rotulo_mes(meses[-1])}" if meses else "—"
            ),
            "tickets_ultimo_mes": tickets_ultimo,
            "mes_ultimo_label": _rotulo_mes(ultimo) if ultimo else "—",
            "variacao_pct": variacao_pct,
            "tipos_distintos": len(tipos_periodo),
            "total_periodo": sum(totais_mes.get(m, 0) for m in meses),
        },
    }


def montar_relatorio_evolucao(user) -> dict[str, Any] | None:
    """Três visões: meu, gerência e geral. Só para equipe interna."""
    if not tem_acesso_interno(user):
        return None

    gerencia = gerencia_de(user) or ""
    meu = _agregar(_qs_especialista(user))
    ger = _agregar(_qs_gerencia(user))
    geral = _agregar(_qs_geral())

    nome = (user.get_full_name() or user.get_username() or "").strip()
    return {
        "usuario_id": user.pk,
        "usuario_nome": nome,
        "gerencia": gerencia,
        "visoes": {
            "meu": {
                "id": "meu",
                "titulo": "Meu",
                "subtitulo": f"Carteira de {nome}" if nome else "Minha carteira",
                "dados": meu,
            },
            "gerencia": {
                "id": "gerencia",
                "titulo": "Gerência",
                "subtitulo": gerencia or "Sem gerência no perfil (usa sua carteira)",
                "dados": ger,
            },
            "geral": {
                "id": "geral",
                "titulo": "Geral",
                "subtitulo": "Todos os tickets da plataforma",
                "dados": geral,
            },
        },
        "gerado_em": timezone.localtime(),
        "exclui_duplicados": True,
    }
