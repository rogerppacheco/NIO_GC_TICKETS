from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet

from tickets.models import Parceiro

from ..models import Destinatario, EnvioWhatsApp, HistoricoChurn, HistoricoOSAB, RelatorioFPD
from ..periodo import periodo_ativo
from ..relatorios import montar_mascara_pdv, resumo_geral
from .syncwa import SyncWAResult, enviar_texto, modo_teste_ativo, syncwa_configurado


@dataclass
class ResumoEnvio:
    enviados: int = 0
    erros: int = 0
    ignorados: int = 0
    detalhes: list[str] | None = None

    def __post_init__(self):
        if self.detalhes is None:
            self.detalhes = []


def destinatarios_para(
    flag: str,
    parceiro: Parceiro | None = None,
    *,
    somente_grupos: bool = False,
) -> QuerySet[Destinatario]:
    qs = Destinatario.objects.filter(ativo=True).select_related("parceiro")
    if parceiro is not None:
        qs = qs.filter(parceiro=parceiro)
    qs = qs.filter(**{flag: True})
    if somente_grupos:
        qs = qs.filter(tipo=Destinatario.TipoDestino.GRUPO)
    return qs.order_by("prioridade", "id")


def _registrar(
    *,
    tipo: str,
    mensagem: str,
    destinatario: Destinatario | None,
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
    result: SyncWAResult,
    modo_teste: bool,
) -> EnvioWhatsApp:
    if result.ok:
        status = EnvioWhatsApp.Status.ENVIADO
        erro = ""
    else:
        status = EnvioWhatsApp.Status.ERRO
        erro = result.error
    return EnvioWhatsApp.objects.create(
        tipo=tipo,
        status=status,
        parceiro=parceiro,
        destinatario=destinatario,
        destino_jid=result.destino or (destinatario.jid if destinatario else ""),
        destino_nome=(destinatario.nome if destinatario else "") or "",
        mensagem=mensagem,
        modo_teste=modo_teste,
        syncwa_message_id=result.message_log_id,
        syncwa_status=result.status,
        erro=erro,
        criado_por=user,
    )


def _enviar_para_lista(
    *,
    tipo: str,
    mensagem: str,
    destinos: list[Destinatario],
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
) -> ResumoEnvio:
    resumo = ResumoEnvio()
    if not mensagem.strip():
        resumo.ignorados += 1
        resumo.detalhes.append("Mensagem vazia — nada enviado.")
        return resumo
    if not syncwa_configurado():
        resumo.erros += 1
        resumo.detalhes.append("SyncWA não configurado.")
        return resumo
    if not destinos:
        resumo.ignorados += 1
        resumo.detalhes.append("Nenhum destinatário ativo para este envio.")
        return resumo

    teste = modo_teste_ativo()
    for dest in destinos:
        result = enviar_texto(dest.jid, mensagem)
        _registrar(
            tipo=tipo,
            mensagem=mensagem,
            destinatario=dest,
            parceiro=parceiro or dest.parceiro,
            user=user,
            result=result,
            modo_teste=teste,
        )
        if result.ok:
            resumo.enviados += 1
            resumo.detalhes.append(f"OK → {dest.nome}")
        else:
            resumo.erros += 1
            resumo.detalhes.append(f"ERRO → {dest.nome}: {result.error}")
    return resumo


def enviar_teste(user: AbstractBaseUser | None = None) -> ResumoEnvio:
    texto = (
        "*NIO GC Tickets — teste SyncWA*\n\n"
        "Se você recebeu esta mensagem, a integração está ok."
    )
    from django.conf import settings

    jid = (getattr(settings, "SYNCWA_TEST_JID", "") or "").strip()
    if not jid and not modo_teste_ativo():
        # Sem JID de teste e sem modo teste: tenta o primeiro destinatário ativo
        dest = Destinatario.objects.filter(ativo=True).order_by("prioridade").first()
        if not dest:
            return ResumoEnvio(erros=1, detalhes=["Cadastre um destinatário ou defina SYNCWA_TEST_JID."])
        return _enviar_para_lista(
            tipo=EnvioWhatsApp.Tipo.TESTE,
            mensagem=texto,
            destinos=[dest],
            parceiro=dest.parceiro,
            user=user,
        )
    # Força envio direto ao JID de teste (mesmo sem Destinatario)
    resumo = ResumoEnvio()
    if not syncwa_configurado():
        return ResumoEnvio(erros=1, detalhes=["SyncWA não configurado."])
    result = enviar_texto(jid or settings.SYNCWA_TEST_JID, texto)
    _registrar(
        tipo=EnvioWhatsApp.Tipo.TESTE,
        mensagem=texto,
        destinatario=None,
        parceiro=None,
        user=user,
        result=result,
        modo_teste=modo_teste_ativo(),
    )
    if result.ok:
        resumo.enviados = 1
        resumo.detalhes.append(f"OK → {result.destino}")
    else:
        resumo.erros = 1
        resumo.detalhes.append(result.error)
    return resumo


def enviar_capilaridade_pdv(
    parceiro: Parceiro,
    user: AbstractBaseUser | None = None,
) -> ResumoEnvio:
    ano, mes = periodo_ativo()
    mensagem = montar_mascara_pdv(parceiro, ano, mes)
    destinos = list(destinatarios_para("envio_capilaridade", parceiro))
    return _enviar_para_lista(
        tipo=EnvioWhatsApp.Tipo.CAPILARIDADE,
        mensagem=mensagem,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
    )


def enviar_resumo_capilaridade(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
) -> ResumoEnvio:
    """Envia o resumo geral para grupos com flag capilaridade (JID único)."""
    ano, mes = periodo_ativo()
    msg = resumo_geral(parceiros, ano, mes)
    destinos = list(
        destinatarios_para("envio_capilaridade", somente_grupos=True)
    )
    vistos: set[str] = set()
    unicos: list[Destinatario] = []
    for d in destinos:
        chave = d.jid.strip().lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(d)
    return _enviar_para_lista(
        tipo=EnvioWhatsApp.Tipo.RESUMO,
        mensagem=msg,
        destinos=unicos,
        parceiro=None,
        user=user,
    )


def enviar_capilaridade_todos(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
    *,
    incluir_resumo: bool = False,
) -> ResumoEnvio:
    total = ResumoEnvio()
    if incluir_resumo:
        parte = enviar_resumo_capilaridade(parceiros, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.extend(parte.detalhes)

    for p in parceiros:
        parte = enviar_capilaridade_pdv(p, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.append(f"— {p.nome}: {parte.enviados} ok / {parte.erros} erro")
    return total


def enviar_osab_pdv(parceiro: Parceiro, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    hist = (
        HistoricoOSAB.objects.filter(parceiro=parceiro)
        .exclude(mensagem="")
        .order_by("-data_processamento")
        .first()
    )
    if not hist or not hist.mensagem.strip():
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem relatório OSAB."])
    destinos = list(destinatarios_para("envio_osab", parceiro))
    return _enviar_para_lista(
        tipo=EnvioWhatsApp.Tipo.OSAB,
        mensagem=hist.mensagem,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
    )


def enviar_fpd_pdv(parceiro: Parceiro, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    rel = RelatorioFPD.objects.filter(parceiro=parceiro).order_by("-criado_em").first()
    if not rel or not rel.mensagem.strip():
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem relatório FPD."])
    destinos = list(destinatarios_para("envio_fpd", parceiro))
    resumo = _enviar_para_lista(
        tipo=EnvioWhatsApp.Tipo.FPD,
        mensagem=rel.mensagem,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
    )
    # Alerta crítico global
    from django.conf import settings

    limite = float(getattr(settings, "FPD_PERCENTUAL_CRITICO", 30))
    if rel.percentual >= limite:
        criticos = list(destinatarios_para("envio_fpd_critico"))
        if criticos:
            alerta = (
                f"*Alerta FPD crítico — {rel.pdv_nome}*\n"
                f"Percentual FPD: *{rel.percentual:.2f}%* (limite {limite:.2f}%)\n\n"
                f"{rel.mensagem}"
            )
            parte = _enviar_para_lista(
                tipo=EnvioWhatsApp.Tipo.FPD_CRITICO,
                mensagem=alerta,
                destinos=criticos,
                parceiro=parceiro,
                user=user,
            )
            resumo.enviados += parte.enviados
            resumo.erros += parte.erros
            resumo.detalhes.extend(parte.detalhes)
    return resumo


def enviar_churn_pdv(parceiro: Parceiro, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    row = (
        HistoricoChurn.objects.filter(parceiro=parceiro)
        .exclude(mensagem="")
        .order_by("-data_analise", "-id")
        .first()
    )
    if not row or not row.mensagem.strip():
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem relatório Churn."])
    destinos = list(destinatarios_para("envio_churn", parceiro))
    return _enviar_para_lista(
        tipo=EnvioWhatsApp.Tipo.CHURN,
        mensagem=row.mensagem,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
    )
