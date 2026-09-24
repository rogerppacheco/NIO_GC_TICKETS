# -*- coding: utf-8 -*-
"""Regras do Projeto Vertical (port do Record Vertical / CDOI)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.db.models import Q, QuerySet, Sum
from django.http import HttpRequest

from tickets.acesso import eh_gerencia, eh_gestor, parceiro_de
from tickets.models import BlocoVertical, SolicitacaoVertical

logger = logging.getLogger(__name__)

CHAVE_DESTINOS = "vertical_resumo_destinos"
CHAVE_ATIVO = "vertical_resumo_ativo"

STATUS_LABEL = dict(SolicitacaoVertical.Status.choices)


def pode_gestao_vertical(user) -> bool:
    return eh_gestor(user) or eh_gerencia(user)


def qs_solicitacoes(user) -> QuerySet[SolicitacaoVertical]:
    qs = SolicitacaoVertical.objects.select_related(
        "criado_por",
        "parceiro",
        "parceiro__especialista",
        "contato",
        "contato__parceiro",
    ).prefetch_related("blocos")
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if pode_gestao_vertical(user):
        return qs
    pdv = parceiro_de(user)
    if pdv:
        return qs.filter(
            Q(parceiro=pdv) | Q(contato__parceiro=pdv) | Q(criado_por=user)
        ).distinct()
    # Especialista: o que ele criou + pedidos dos PDVs da carteira dele.
    return qs.filter(
        Q(criado_por=user)
        | Q(parceiro__especialista=user)
        | Q(contato__parceiro__especialista=user)
        | Q(criado_por__parceiro_conta__especialista=user)
    ).distinct()


def _int(valor: Any, default: int = 0) -> int:
    if valor is None or valor == "":
        return default
    try:
        return int(valor)
    except (TypeError, ValueError):
        return default


def _texto(valor: Any, limite: int = 255) -> str:
    return str(valor or "").strip()[:limite]


def _bool_form(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor or "").strip().lower() in {"1", "true", "on", "sim", "yes"}


def _arquivo_url(request: HttpRequest | None, campo) -> str:
    if not campo:
        return ""
    try:
        url = campo.url
    except ValueError:
        return ""
    if request:
        return request.build_absolute_uri(url)
    return url


def nome_usuario(user) -> str:
    if not user:
        return "—"
    nome = (user.get_full_name() or "").strip()
    return nome or user.get_username()


def nome_acionado(item: SolicitacaoVertical) -> str:
    if item.contato_id and item.contato:
        return item.contato.nome
    return nome_usuario(item.criado_por)


def serializar_bloco(bloco: BlocoVertical) -> dict[str, Any]:
    return {
        "nome": bloco.nome_bloco,
        "andares": bloco.andares,
        "aptos": bloco.unidades_por_andar,
        "total": bloco.total_hps_bloco,
    }


def serializar_solicitacao(
    item: SolicitacaoVertical,
    request: HttpRequest | None = None,
    *,
    can_edit: bool = False,
    detalhe: bool = False,
) -> dict[str, Any]:
    carta = _arquivo_url(request, item.arquivo_carta)
    fachada = _arquivo_url(request, item.arquivo_fachada)
    data: dict[str, Any] = {
        "id": item.id,
        "nome": item.nome_condominio,
        "nome_condominio": item.nome_condominio,
        "cidade": item.cidade,
        "cidade_uf": f"{item.cidade}-{item.uf}".strip("-"),
        "logradouro": item.logradouro,
        "numero": item.numero,
        "bairro": item.bairro,
        "cep": item.cep,
        "uf": item.uf,
        "nome_sindico": item.nome_sindico,
        "contato": item.contato_sindico,
        "total_hps": item.total_hps,
        "prevenda": item.pre_venda_minima,
        "status": item.get_status_display(),
        "status_cod": item.status,
        "observacao": item.observacao or "",
        "data": item.data_criacao.strftime("%d/%m/%Y"),
        "link_fotos_fachada": fachada,
        "link_carta_sindico": carta,
        "can_edit": can_edit,
        "criado_por_id": item.criado_por_id,
        "criado_por_nome": nome_acionado(item),
        "parceiro_id": item.parceiro_id,
        "parceiro_nome": (item.parceiro.nome if item.parceiro_id and item.parceiro else ""),
    }
    if detalhe:
        data.update(
            {
                "latitude": item.latitude or "",
                "longitude": item.longitude or "",
                "infraestrutura": item.infraestrutura_tipo,
                "possui_shaft": item.possui_shaft_dg,
                "blocos": [serializar_bloco(b) for b in item.blocos.all()],
            }
        )
    return data


def parse_blocos(bruto: Any) -> list[dict[str, Any]]:
    if not bruto:
        return []
    if isinstance(bruto, list):
        itens = bruto
    else:
        try:
            itens = json.loads(str(bruto))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(itens, list):
            return []
    saida: list[dict[str, Any]] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        nome = _texto(item.get("nome") or item.get("nome_bloco"), 100)
        andares = _int(item.get("andares"))
        aptos = _int(item.get("aptos") or item.get("unidades_por_andar"))
        total = _int(item.get("total") or item.get("total_hps_bloco"), andares * aptos)
        if not nome or andares <= 0:
            continue
        saida.append(
            {
                "nome": nome,
                "andares": andares,
                "aptos": aptos,
                "total": total if total > 0 else andares * aptos,
            }
        )
    return saida


def gravar_blocos(solicitacao: SolicitacaoVertical, blocos: list[dict[str, Any]]) -> None:
    solicitacao.blocos.all().delete()
    for bloco in blocos:
        BlocoVertical.objects.create(
            solicitacao=solicitacao,
            nome_bloco=bloco["nome"],
            andares=bloco["andares"],
            unidades_por_andar=bloco["aptos"],
            total_hps_bloco=bloco["total"],
        )
    total = sum(b["total"] for b in blocos)
    solicitacao.total_hps = total
    solicitacao.pre_venda_minima = max(0, -(-total // 10)) if total else 0
    solicitacao.save(update_fields=["total_hps", "pre_venda_minima", "atualizado_em"])


def payload_criar(data: dict[str, Any]) -> dict[str, Any]:
    infra = _texto(data.get("infraestrutura") or data.get("infraestrutura_tipo"), 50)
    if infra not in SolicitacaoVertical.Infraestrutura.values:
        infra = SolicitacaoVertical.Infraestrutura.SUBTERRANEA
    blocos = parse_blocos(data.get("dados_blocos_json") or data.get("input_blocos_json"))
    total_hps = _int(data.get("total_hps_final"), sum(b["total"] for b in blocos))
    prevenda = _int(data.get("prevenda_final"), max(0, -(-total_hps // 10)) if total_hps else 0)
    return {
        "nome_condominio": _texto(data.get("nome_condominio") or data.get("cliente")),
        "nome_sindico": _texto(data.get("nome_sindico")),
        "contato_sindico": re.sub(r"\D", "", _texto(data.get("contato") or data.get("contato_sindico"), 20)),
        "cep": _texto(data.get("cep"), 9),
        "logradouro": _texto(data.get("logradouro")),
        "numero": _texto(data.get("numero"), 20),
        "bairro": _texto(data.get("bairro"), 100),
        "cidade": _texto(data.get("cidade"), 100),
        "uf": _texto(data.get("uf"), 2).upper(),
        "latitude": _texto(data.get("latitude"), 50),
        "longitude": _texto(data.get("longitude"), 50),
        "infraestrutura_tipo": infra,
        "possui_shaft_dg": _bool_form(data.get("possui_shaft") or data.get("possui_shaft_dg")),
        "observacao": _texto(data.get("observacao_form") or data.get("observacao"), 4000),
        "total_hps": total_hps,
        "pre_venda_minima": prevenda,
        "_blocos": blocos,
    }


def montar_resumo(item: SolicitacaoVertical) -> str:
    return (
        f"✅ *Resumo Projeto Vertical*\n"
        f"ID: {item.id}\n"
        f"Condomínio: {item.nome_condominio}\n"
        f"CEP: {item.cep}\n"
        f"Endereço: {item.logradouro}, {item.numero} - {item.bairro}\n"
        f"Cidade/UF: {item.cidade}-{item.uf}\n"
        f"Infraestrutura: {item.get_infraestrutura_tipo_display()}\n"
        f"Shaft/DG: {'Sim' if item.possui_shaft_dg else 'Não'}\n"
        f"Total HPs: {item.total_hps}\n"
        f"Pré-venda (10%): {item.pre_venda_minima}\n"
        f"Síndico: {item.nome_sindico}\n"
        f"Contato: {item.contato_sindico}\n"
        f"Latitude: {item.latitude or '-'}\n"
        f"Longitude: {item.longitude or '-'}"
    )


def _config_valor(chave: str, padrao: str = "") -> str:
    from gestao.models import GestaoConfig

    row = GestaoConfig.objects.filter(chave=chave).first()
    return (row.valor if row else "") or padrao


def salvar_config_resumo(destinatarios: str, ativo: bool) -> dict[str, Any]:
    from gestao.models import GestaoConfig

    dest = _texto(destinatarios, 500)
    GestaoConfig.objects.update_or_create(chave=CHAVE_DESTINOS, defaults={"valor": dest})
    GestaoConfig.objects.update_or_create(
        chave=CHAVE_ATIVO, defaults={"valor": "1" if ativo else "0"}
    )
    return {"destinatarios": dest, "ativo": ativo}


def ler_config_resumo() -> dict[str, Any]:
    dest = _config_valor(CHAVE_DESTINOS)
    ativo = _config_valor(CHAVE_ATIVO, "1") != "0"
    return {"destinatarios": dest, "ativo": ativo}


def _numeros(texto: str) -> list[str]:
    saida: list[str] = []
    for parte in re.split(r"[,\n;]+", texto or ""):
        num = re.sub(r"\D", "", parte)
        if len(num) >= 10:
            saida.append(num)
    return saida


def enviar_whatsapp_criacao(item: SolicitacaoVertical) -> str:
    resumo = montar_resumo(item)
    try:
        from gestao.messaging.syncwa import enviar_texto, syncwa_configurado
    except Exception:
        return resumo
    if not syncwa_configurado():
        return resumo
    try:
        if item.contato_sindico:
            enviar_texto(
                item.contato_sindico,
                (
                    f"Olá, sua solicitação de Projeto Vertical para *{item.nome_condominio}* "
                    f"foi recebida com sucesso! ID: {item.id}. Status: Sem Tratamento."
                ),
            )
    except Exception:
        logger.exception("Falha ao avisar síndico no Projeto Vertical %s", item.id)
    cfg = ler_config_resumo()
    destinos = _numeros(item.destinatarios_resumo or "")
    if cfg["ativo"]:
        destinos.extend(_numeros(cfg["destinatarios"]))
    vistos: set[str] = set()
    for numero in destinos:
        if numero in vistos:
            continue
        vistos.add(numero)
        try:
            enviar_texto(numero, resumo)
        except Exception:
            logger.exception("Falha no resumo WhatsApp Vertical %s → %s", item.id, numero)
    return resumo

def enviar_email_criacao_vertical(item: SolicitacaoVertical) -> None:
    parceiro = item.parceiro
    if not parceiro or not parceiro.especialista:
        return
    email_especialista = parceiro.especialista.email
    if not email_especialista:
        return

    from gestao.messaging.email_smtp import enviar_email_com_anexos
    resumo = montar_resumo(item)
    
    anexos = []
    if item.arquivo_carta:
        try:
            with item.arquivo_carta.open("rb") as f:
                anexos.append((item.arquivo_carta.name.split("/")[-1] or "carta.pdf", f.read(), "application/octet-stream"))
        except Exception:
            pass
    if item.arquivo_fachada:
        try:
            with item.arquivo_fachada.open("rb") as f:
                anexos.append((item.arquivo_fachada.name.split("/")[-1] or "fachada.jpg", f.read(), "application/octet-stream"))
        except Exception:
            pass

    enviar_email_com_anexos(
        [email_especialista],
        assunto=f"Novo Projeto Vertical - {item.nome_condominio}",
        corpo_texto=resumo,
        anexos=anexos,
    )


def contar_vendas_cep_fachada(qs: QuerySet[SolicitacaoVertical]) -> int:
    """Record cruza CEP+número com Venda; no NIO o OSAB não tem fachada — retorna 0."""
    _ = qs
    return 0


def dashboard(qs: QuerySet[SolicitacaoVertical]) -> dict[str, Any]:
    from django.db.models import Count

    total_acionamentos = qs.count()
    total_hps = qs.aggregate(total=Sum("total_hps")).get("total") or 0
    total_prevenda = qs.aggregate(total=Sum("pre_venda_minima")).get("total") or 0
    por_status = list(
        qs.values("status").annotate(qtd=Count("id")).order_by("-qtd")
    )
    for linha in por_status:
        linha["label"] = STATUS_LABEL.get(linha["status"], linha["status"])
    return {
        "total_acionamentos": total_acionamentos,
        "total_hps": total_hps,
        "total_prevenda": total_prevenda,
        "vendas_realizadas": contar_vendas_cep_fachada(qs),
        "por_status": por_status,
    }


def consultar_viacep(cep: str) -> dict[str, Any]:
    cep_limpo = re.sub(r"\D", "", cep or "")
    if len(cep_limpo) != 8:
        return {"ok": False, "code": "invalid", "message": "CEP inválido. Informe 8 dígitos."}
    url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
    req = urllib.request.Request(url, headers={"User-Agent": "NIO-GC-Tickets/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("ViaCEP indisponível para %s: %s", cep_limpo, exc)
        return {
            "ok": False,
            "code": "unavailable",
            "message": "Serviço de CEP temporariamente indisponível. Preencha manualmente.",
        }
    if data.get("erro"):
        return {
            "ok": False,
            "code": "not_found",
            "message": "CEP não encontrado na base dos Correios.",
        }
    return {
        "ok": True,
        "data": {
            "logradouro": data.get("logradouro") or "",
            "bairro": data.get("bairro") or "",
            "cidade": data.get("localidade") or "",
            "uf": (data.get("uf") or "").upper(),
            "cep": data.get("cep") or cep_limpo,
        },
    }


def consultar_nominatim(q: str = "", postalcode: str = "") -> list[dict[str, Any]]:
    if not q and not postalcode:
        return []
    params = {"format": "json", "limit": "1", "countrycodes": "br"}
    if q:
        params["q"] = q
    if postalcode:
        params["postalcode"] = re.sub(r"\D", "", postalcode)
    url = f"https://nominatim.openstreetmap.org/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "NIO-GC-Tickets/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Nominatim indisponível: %s", exc)
        return []
    return data if isinstance(data, list) else []


def parceiro_do_pedido(request) -> Any:
    return parceiro_de(request.user) if getattr(request, "user", None) else None
