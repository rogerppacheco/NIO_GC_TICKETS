from __future__ import annotations

import unicodedata
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Iterable

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from tickets.models import Parceiro

from ..models import CadastroTerceiro, ConfiguracaoOSAB, PracaBTU, VendaOSAB
from ..periodo import hoje, periodo_ativo
from .osab import STATUS_IGNORADOS

RANKING_INICIO = date(2026, 9, 2)
PONTOS_PADRAO = 1.0
PONTOS_BTU = 0.5
GRUPO_REGULAR = "regular"
GRUPO_INICIANTE = "iniciante"
GRUPO_SEM_CADASTRO = "sem_cadastro"


def normalizar_praca(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.upper().split())


def data_local(valor) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        if timezone.is_aware(valor):
            return timezone.localtime(valor).date()
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def venda_vb_valida(venda: VendaOSAB) -> bool:
    situacao = (venda.situacao or "").strip()
    if not situacao:
        return False
    if situacao in STATUS_IGNORADOS:
        return False
    if situacao.lower().startswith("draft"):
        return False
    return True


def venda_gross_valida(venda: VendaOSAB) -> bool:
    return (venda.situacao or "").strip().lower() in {"concluído", "concluido"}


def _qs_parceiros(parceiros: Iterable[Parceiro]):
    ids = [p.pk for p in parceiros]
    return VendaOSAB.objects.filter(parceiro_id__in=ids)


def datas_d0_d1(
    ano: int,
    mes: int,
    parceiros: Iterable[Parceiro],
    *,
    data_ref: date | None = None,
) -> tuple[date | None, date | None]:
    """D0 = último dia do mês (até hoje) com VB; D-1 = dia civil anterior, se ainda no mês."""
    corte = data_ref or hoje()
    ultimo = date(ano, mes, monthrange(ano, mes)[1])
    limite = min(corte, ultimo)
    dias: set[date] = set()
    for venda in _qs_parceiros(parceiros).filter(
        data_abertura__year=ano, data_abertura__month=mes
    ):
        if not venda_vb_valida(venda):
            continue
        dia = data_local(venda.data_abertura)
        if dia and dia.year == ano and dia.month == mes and dia <= limite:
            dias.add(dia)
    if not dias:
        return None, None
    d0 = max(dias)
    d1 = d0 - timedelta(days=1)
    if d1.year != ano or d1.month != mes:
        return d0, None
    return d0, d1


def _contar_dia(vendas: list[VendaOSAB], dia: date | None, *, gross: bool = False) -> int:
    if dia is None:
        return 0
    total = 0
    for venda in vendas:
        if gross:
            if not venda_gross_valida(venda):
                continue
            marca = data_local(venda.data_fechamento)
        else:
            if not venda_vb_valida(venda):
                continue
            marca = data_local(venda.data_abertura)
        if marca == dia:
            total += 1
    return total


def linhas_acumulado(
    parceiros: Iterable[Parceiro],
    ano: int,
    mes: int,
    *,
    data_ref: date | None = None,
) -> dict:
    lista = list(parceiros)
    d0, d1 = datas_d0_d1(ano, mes, lista, data_ref=data_ref)
    configs = {
        (c.parceiro_id): c
        for c in ConfiguracaoOSAB.objects.filter(
            parceiro__in=lista, ano=ano, mes=mes
        )
    }
    vendas_ab = list(
        _qs_parceiros(lista).filter(data_abertura__year=ano, data_abertura__month=mes)
    )
    vendas_fc = list(
        _qs_parceiros(lista).filter(data_fechamento__year=ano, data_fechamento__month=mes)
    )
    por_pdv_vb: dict[int, list[VendaOSAB]] = {}
    por_pdv_gr: dict[int, list[VendaOSAB]] = {}
    for venda in vendas_ab:
        if venda.parceiro_id:
            por_pdv_vb.setdefault(venda.parceiro_id, []).append(venda)
    for venda in vendas_fc:
        if venda.parceiro_id:
            por_pdv_gr.setdefault(venda.parceiro_id, []).append(venda)

    linhas = []
    for parceiro in sorted(lista, key=lambda p: (p.nome or "").upper()):
        vbs = por_pdv_vb.get(parceiro.id, [])
        gross = por_pdv_gr.get(parceiro.id, [])
        realizado_vb = sum(1 for v in vbs if venda_vb_valida(v))
        realizado_gross = sum(1 for v in gross if venda_gross_valida(v))
        config = configs.get(parceiro.id)
        meta_vb = config.meta_vl if config else 0
        meta_gross = config.meta_gross if config else 0
        pct_vb = (realizado_vb / meta_vb * 100) if meta_vb else None
        pct_gross = (realizado_gross / meta_gross * 100) if meta_gross else None
        linhas.append(
            {
                "parceiro": parceiro,
                "pdv": parceiro.nome,
                "meta_vb": meta_vb,
                "realizado_vb": realizado_vb,
                "pct_vb": pct_vb,
                "d1_vb": _contar_dia(vbs, d1),
                "d0_vb": _contar_dia(vbs, d0),
                "meta_gross": meta_gross,
                "realizado_gross": realizado_gross,
                "pct_gross": pct_gross,
                "d1_gross": _contar_dia(gross, d1, gross=True),
                "d0_gross": _contar_dia(gross, d0, gross=True),
                "sem_meta": config is None,
            }
        )
    linhas.sort(
        key=lambda l: (
            -(l["pct_vb"] if l["pct_vb"] is not None else -1),
            -l["realizado_vb"],
            l["pdv"].upper(),
        )
    )
    return {"linhas": linhas, "d0": d0, "d1": d1, "ano": ano, "mes": mes}


def _fmt_pct(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor:.1f}%".replace(".", ",")


def mensagem_acumulado_pdv(linha: dict, *, d0: date | None, d1: date | None, ano: int, mes: int) -> str:
    partes = [
        f"📊 *Acumulado {mes:02d}/{ano} — {linha['pdv']}*",
    ]
    if d0:
        partes.append(f"Corte D0 {d0.strftime('%d/%m')} · D-1 {d1.strftime('%d/%m') if d1 else '—'}")
    partes.append(
        f"VB: *{linha['realizado_vb']}* / meta {linha['meta_vb'] or '—'} ({_fmt_pct(linha['pct_vb'])})"
    )
    partes.append(f"D-1: {linha['d1_vb']} · D0: {linha['d0_vb']}")
    partes.append(
        f"Gross: *{linha['realizado_gross']}* / meta {linha['meta_gross'] or '—'} ({_fmt_pct(linha['pct_gross'])})"
    )
    partes.append(f"Gross D-1: {linha['d1_gross']} · D0: {linha['d0_gross']}")
    if linha.get("sem_meta"):
        partes.append("_Cadastre a meta OSAB deste PDV em Metas._")
    return "\n".join(partes)


def mensagem_acumulado_consolidada(resumo: dict) -> str:
    d0, d1 = resumo["d0"], resumo["d1"]
    ano, mes = resumo["ano"], resumo["mes"]
    partes = [f"📊 *Acumulado do mês {mes:02d}/{ano}*"]
    if d0:
        partes.append(f"D0 {d0.strftime('%d/%m')} · D-1 {d1.strftime('%d/%m') if d1 else '—'}")
    for i, linha in enumerate(resumo["linhas"], start=1):
        partes.append(
            f"{i}. {linha['pdv']} — VB {linha['realizado_vb']}/{linha['meta_vb'] or '—'} "
            f"({_fmt_pct(linha['pct_vb'])}) · D-1 {linha['d1_vb']} · D0 {linha['d0_vb']}"
        )
    if not resumo["linhas"]:
        partes.append("_Nenhum PDV no escopo._")
    return "\n".join(partes)


PDV_LEGENDA_GENERICO = "time"

# Frases curtas, comerciais, uma por dia (ciclo pelo calendário).
FRASES_COMERCIAIS = (
    "Quem vende cedo, puxa o mês.",
    "Meta não espera. Resultado se constrói agora.",
    "Cada VL conta. Foco no fechamento.",
    "O dia é curto. A meta não perdoa.",
    "Gross no radar: instala quem já vendeu.",
    "Ritmo de venda define o ranking.",
    "Não deixa para amanhã o pedido de hoje.",
    "Execução no PDV. Resultado no consolidado.",
    "Um pedido a mais muda o atingimento.",
    "Foco no cliente. Conversão na meta.",
    "Quem prospecta, fecha. Quem espera, fica para trás.",
    "Atingimento se ganha no campo, não na planilha.",
    "Hoje é dia de virar o jogo.",
    "Venda com urgência. Entrega com qualidade.",
    "O mês se decide nos dias comuns.",
    "Pressão boa: meta na frente, time junto.",
    "Menos desculpa. Mais pedido no sistema.",
    "BTU ou padrão: o que importa é converter.",
    "Fecha cedo, projeta alto.",
    "Resultado comercial não negocia com o relógio.",
    "A meta do mês começa neste turno.",
    "Quem acelera agora, comemora no fechamento.",
    "Cliente na frente. Número no bolso.",
    "Consistência vence o dia. O dia vence o mês.",
    "Sem ritmo, sem ranking. Bora vender.",
    "Gap se fecha com visita, não com discurso.",
    "Hoje vale por dois se a execução vier forte.",
    "Não é sorte. É volume com qualidade.",
    "Acompanhe o D0. Corrija no D1.",
    "Meta é compromisso. Resultado é escolha.",
    "Venda agora. Gross depois. Comissão no fim.",
    "O PDV que age, sobe no ranking.",
    "Faltam dias. Sobram oportunidades.",
    "Quem controla o pipeline, controla a meta.",
    "Parcial de hoje é o consolidado de amanhã.",
    "Energia no time. Foco no número.",
    "Cada recusa é uma nova abordagem.",
    "Fecha com argumento. Ganha no mix.",
    "Não disperse. Meta, cliente, próximo pedido.",
    "O comercial que executa, atinge.",
    "Comece pelo difícil. O fácil vem no fluxo.",
    "Resultado é a soma das visitas de hoje.",
    "Sempre tem um pedido extra no próximo contato.",
    "A meta respeita quem respeita o relógio.",
    "Bora virar o percentual. Um VL de cada vez.",
)


def saudacao_horario(hora: int) -> tuple[str, str]:
    if hora < 12:
        return "☀️", "Bom dia"
    if hora < 18:
        return "🌤️", "Boa tarde"
    return "🌙", "Boa noite"


def frase_comercial_do_dia(data: date) -> str:
    return FRASES_COMERCIAIS[data.toordinal() % len(FRASES_COMERCIAIS)]


def mensagem_parcial(
    *,
    pdv: str = PDV_LEGENDA_GENERICO,
    agora: datetime | None = None,
    ano: int | None = None,
    mes: int | None = None,
) -> str:
    """Legenda da imagem de meta do mês: saudação + frase do dia + convite."""
    agora = agora or timezone.localtime()
    data = agora.date() if isinstance(agora, datetime) else hoje()
    hora = agora.hour if isinstance(agora, datetime) else timezone.localtime().hour
    if ano is None or mes is None:
        ano_ativo, mes_ativo = periodo_ativo()
        ano = ano if ano is not None else ano_ativo
        mes = mes if mes is not None else mes_ativo
    emoji, saudacao = saudacao_horario(hora)
    nome = (pdv or PDV_LEGENDA_GENERICO).strip() or PDV_LEGENDA_GENERICO
    frase = frase_comercial_do_dia(data)
    return "\n".join(
        [
            f"{emoji} {saudacao}, *{nome}*!",
            "",
            f"🎯 *Meta do mês — {mes:02d}/{ano}*",
            "",
            f"_{frase}_",
            "",
            "Segue o acompanhamento. Foco no resultado.",
        ]
    )


def caption_parcial_envio(
    caption: str,
    parceiro,
    *,
    agora: datetime | None = None,
    ano: int | None = None,
    mes: int | None = None,
) -> str:
    """Usa a legenda editada ou gera uma; *time* vira o nome do PDV."""
    nome = (getattr(parceiro, "nome", None) or PDV_LEGENDA_GENERICO).strip() or PDV_LEGENDA_GENERICO
    texto = (caption or "").strip()
    if not texto:
        return mensagem_parcial(pdv=nome, agora=agora, ano=ano, mes=mes)
    marcador = f"*{PDV_LEGENDA_GENERICO}*"
    if marcador in texto:
        texto = texto.replace(marcador, f"*{nome}*", 1)
    return texto


def janela_dia_anterior(data_envio: date) -> tuple[date, date]:
    """Na segunda, pontuação de sexta a domingo; nos demais dias, só D-1."""
    ontem = data_envio - timedelta(days=1)
    if data_envio.weekday() == 0:
        return data_envio - timedelta(days=3), ontem
    return ontem, ontem


def inicio_ranking_mes(ano: int, mes: int) -> date:
    if ano == RANKING_INICIO.year and mes == RANKING_INICIO.month:
        return RANKING_INICIO
    return date(ano, mes, 1)


def periodo_ranking(data_ref: date | None = None) -> dict:
    """Acumulado mensal até D-1. Setembro/2026 começa no dia 02. Antes disso, prévia."""
    envio = data_ref or hoje()
    d1 = envio - timedelta(days=1)
    oficial = d1 >= RANKING_INICIO
    if oficial:
        inicio = inicio_ranking_mes(d1.year, d1.month)
        inicio = max(inicio, RANKING_INICIO)
        ano, mes = d1.year, d1.month
    else:
        inicio = date(envio.year, envio.month, 1)
        ano, mes = envio.year, envio.month
        if d1 < inicio:
            d1 = inicio
    janela_ini, janela_fim = janela_dia_anterior(envio)
    return {
        "envio": envio,
        "inicio": inicio,
        "fim": d1,
        "ano": ano,
        "mes": mes,
        "oficial": oficial,
        "janela_ini": janela_ini,
        "janela_fim": janela_fim,
    }


def _praca_btu_set() -> set[str]:
    return set(PracaBTU.objects.filter(ativo=True).values_list("nome_norm", flat=True))


def pontos_venda(municipio: str, pracas_btu: set[str]) -> float:
    norm = normalizar_praca(municipio)
    if norm and norm in pracas_btu:
        return PONTOS_BTU
    return PONTOS_PADRAO


def classificar_grupo_parceiro(parceiro: Parceiro | None, data_corte: date) -> str:
    if parceiro is None or not parceiro.data_credenciamento:
        return GRUPO_SEM_CADASTRO
    cred = parceiro.data_credenciamento
    if cred.year <= 1901:
        return GRUPO_REGULAR
    limite = cred + relativedelta(months=6)
    if data_corte > limite:
        return GRUPO_REGULAR
    return GRUPO_INICIANTE


def classificar_grupo(terceiro: CadastroTerceiro | None, data_corte: date) -> str:
    """Legado Sysmap — preferir classificar_grupo_parceiro."""
    if terceiro is None or not terceiro.data_alocacao:
        return GRUPO_SEM_CADASTRO
    limite = terceiro.data_alocacao + relativedelta(months=6)
    if data_corte > limite:
        return GRUPO_REGULAR
    return GRUPO_INICIANTE


def _primeiro_nome_pessoa(nome: str) -> str:
    partes = (nome or "").strip().split()
    return partes[0] if partes else "—"


def _dados_especialista(parceiro: Parceiro | None) -> tuple[str, str]:
    if parceiro is None or not parceiro.especialista:
        return "—", "—"
    user = parceiro.especialista
    completo = (user.get_full_name() or user.username or "—").strip().upper()
    curto = _primeiro_nome_pessoa(completo).upper()
    return completo, curto


def montar_ranking(
    parceiros: Iterable[Parceiro],
    *,
    data_ref: date | None = None,
) -> dict:
    """Ranking por PDV (formato RKG_2): pontos acumulados até D-1 + janela do dia anterior."""
    periodo = periodo_ranking(data_ref)
    lista = list(parceiros)
    ids = [p.pk for p in lista]
    mapa_parceiros = {p.pk: p for p in lista}
    pracas_btu = _praca_btu_set()
    vendas = VendaOSAB.objects.filter(
        parceiro_id__in=ids,
        data_abertura__date__gte=periodo["inicio"],
        data_abertura__date__lte=periodo["fim"],
    )
    agregados: dict[int, dict] = {}
    sem_municipio = 0
    for venda in vendas:
        if not venda_vb_valida(venda):
            continue
        pid = venda.parceiro_id
        if pid is None:
            continue
        dia = data_local(venda.data_abertura)
        if dia is None:
            continue
        pts = pontos_venda(venda.municipio, pracas_btu)
        if not (venda.municipio or "").strip():
            sem_municipio += 1
        parceiro = mapa_parceiros.get(pid)
        esp_completo, esp_curto = _dados_especialista(parceiro)
        item = agregados.setdefault(
            pid,
            {
                "parceiro_id": pid,
                "pdv": (parceiro.nome if parceiro else venda.pdv_nome or "—").strip(),
                "especialista": esp_completo,
                "especialista_curto": esp_curto,
                "pontos": 0.0,
                "pontos_dia": 0.0,
                "vb": 0,
                "vb_btu": 0,
                "vb_padrao": 0,
                "sem_municipio": 0,
            },
        )
        item["pontos"] += pts
        item["vb"] += 1
        if pts == PONTOS_BTU:
            item["vb_btu"] += 1
        if not (venda.municipio or "").strip():
            item["sem_municipio"] += 1
        if periodo["janela_ini"] <= dia <= periodo["janela_fim"]:
            item["pontos_dia"] += pts

    grupos = {GRUPO_REGULAR: [], GRUPO_INICIANTE: [], GRUPO_SEM_CADASTRO: []}
    pdvs_sem_classificacao = 0
    for pid, item in agregados.items():
        item["vb_padrao"] = item["vb"] - item["vb_btu"]
        parceiro = mapa_parceiros.get(pid)
        grupo = classificar_grupo_parceiro(parceiro, periodo["fim"])
        item["grupo"] = grupo
        item["data_credenciamento"] = parceiro.data_credenciamento if parceiro else None
        if grupo == GRUPO_SEM_CADASTRO:
            pdvs_sem_classificacao += 1
        grupos[grupo].append(item)

    def _ordem(item: dict) -> tuple:
        return (-item["pontos"], -item["pontos_dia"], item["pdv"].upper())

    for grupo in grupos.values():
        grupo.sort(key=_ordem)
        for i, item in enumerate(grupo, start=1):
            item["posicao"] = i

    return {
        "periodo": periodo,
        "grupos": grupos,
        "pracas_btu": sorted(pracas_btu),
        "qtd_btu": len(pracas_btu),
        "sem_municipio": sem_municipio,
        "tts_sem_data": pdvs_sem_classificacao,
        "total_tts": len(agregados),
    }


def _fmt_pts(valor: float) -> str:
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.1f}".replace(".", ",")


def mensagem_ranking(ranking: dict, *, limite: int = 40) -> str:
    periodo = ranking["periodo"]
    titulo_janela = (
        f"{periodo['janela_ini'].strftime('%d/%m')}–{periodo['janela_fim'].strftime('%d/%m')}"
        if periodo["janela_ini"] != periodo["janela_fim"]
        else periodo["janela_ini"].strftime("%d/%m")
    )
    partes = [
        f"🏆 *Ranking VB* · {periodo['inicio'].strftime('%d/%m')} a {periodo['fim'].strftime('%d/%m')}",
        f"Atualização até D-1 · pontuação do período anterior: {titulo_janela}",
        "Praça padrão = 1 pt · praça BTU = 0,5 pt",
    ]
    if not periodo["oficial"]:
        partes.append(f"_Prévia — ranking oficial começa em {RANKING_INICIO.strftime('%d/%m/%Y')}._")
    rotulos = {
        GRUPO_REGULAR: "Base Regular (>6 meses)",
        GRUPO_INICIANTE: "Iniciante (≤6 meses)",
        GRUPO_SEM_CADASTRO: "Sem data de credenciamento",
    }
    for chave in (GRUPO_REGULAR, GRUPO_INICIANTE, GRUPO_SEM_CADASTRO):
        grupo = ranking["grupos"].get(chave) or []
        if not grupo and chave == GRUPO_SEM_CADASTRO:
            continue
        partes.append("")
        partes.append(f"*{rotulos[chave]}*")
        if not grupo:
            partes.append("_Ninguém neste grupo ainda._")
            continue
        for item in grupo[:limite]:
            partes.append(
                f"{item['posicao']}. {item['pdv']} ({item['especialista_curto']}) — "
                f"*{_fmt_pts(item['pontos'])} pts* · {titulo_janela}: {_fmt_pts(item['pontos_dia'])} "
                f"(BTU {item['vb_btu']} · padrão {item['vb_padrao']})"
            )
        if len(grupo) > limite:
            partes.append(f"_… +{len(grupo) - limite} PDV(s)_")
    return "\n".join(partes)


def cadastrar_praca_btu(nome: str) -> PracaBTU:
    nome = " ".join((nome or "").split())
    norm = normalizar_praca(nome)
    if not norm:
        raise ValueError("Informe o município ou praça BTU.")
    obj, _criado = PracaBTU.objects.update_or_create(
        nome_norm=norm,
        defaults={
            "nome": nome,
            "fonte": PracaBTU.Fonte.MANUAL,
            "ativo": True,
        },
    )
    return obj


def vendas_sem_municipio(parceiros: Iterable[Parceiro], data_ref: date | None = None) -> list[VendaOSAB]:
    """VBs válidas no período do ranking sem município na OSAB."""
    periodo = periodo_ranking(data_ref)
    ids = [p.pk for p in parceiros]
    qs = (
        VendaOSAB.objects.filter(
            parceiro_id__in=ids,
            data_abertura__date__gte=periodo["inicio"],
            data_abertura__date__lte=periodo["fim"],
        )
        .select_related("parceiro")
        .order_by("-data_abertura")
    )
    out: list[VendaOSAB] = []
    for venda in qs:
        if not venda_vb_valida(venda):
            continue
        if (venda.municipio or "").strip():
            continue
        out.append(venda)
    return out


def gaps_ranking(ranking: dict) -> list[str]:
    avisos = []
    if ranking["qtd_btu"] == 0:
        avisos.append(
            "Nenhuma praça BTU ativa — todas as VBs estão valendo 1 ponto. "
            "Importe o GDP (portfólio NOVO ESPECIAL) abaixo."
        )
    if ranking["sem_municipio"]:
        avisos.append(
            f"{ranking['sem_municipio']} VB(s) sem município na OSAB. "
            "Reimporte a base com a coluna LOCALIDADE (ou MUNICIPIO/CIDADE) para aplicar 0,5 nas praças BTU."
        )
    if ranking["tts_sem_data"]:
        avisos.append(
            f"{ranking['tts_sem_data']} PDV(s) sem data de credenciamento no cadastro. "
            "Preencha em Parceiros ou importe a Carteira PP."
        )
    if not ranking["total_tts"]:
        avisos.append("Nenhuma VB válida no período do ranking (até D-1).")
    return avisos
