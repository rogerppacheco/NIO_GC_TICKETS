from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Q, QuerySet

from tickets.acesso import eh_gestor, gerencia_de
from tickets.models import Parceiro

from ..models import (
    Destinatario,
    EnvioWhatsApp,
    HistoricoChurn,
    HistoricoOSAB,
    RelatorioComissionamento,
    RelatorioFPD,
    RelatorioRecompra,
    RelatorioTarefa,
    RelatorioVendaIndevida,
)
from ..periodo import periodo_ativo
from ..planilhas import (
    bytes_arquivo_field,
    planilha_acumulado,
    planilha_capilaridade,
    planilha_churn,
    planilha_fpd,
    planilha_osab,
    planilha_ranking,
)
from ..relatorios import montar_mascara_pdv, resumo_geral
from .email_smtp import enviar_email_com_anexos, smtp_configurado
from .syncwa import SyncWAResult, enviar_documento, enviar_texto, modo_teste_ativo, syncwa_configurado

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FLAG_EMAIL = {
    "envio_osab": "email_osab",
    "envio_capilaridade": "email_capilaridade",
    "envio_fpd": "email_fpd",
    "envio_fpd_critico": "email_fpd_critico",
    "envio_churn": "email_churn",
    "envio_comissionamento": "email_comissionamento",
    "envio_tarefas": "email_tarefas",
    "envio_venda_indevida": "email_venda_indevida",
    "envio_recompra": "email_recompra",
    "envio_resultados": "email_resultados",
}


def _filtrar_lote_escopo(qs, user, parceiros=None, incluir_sem_pdv=None):
    if parceiros is None:
        return qs
    ids = [getattr(p, "pk", p) for p in parceiros]
    filtro = Q(parceiro_id__in=ids)
    if incluir_sem_pdv is None:
        incluir_sem_pdv = bool(user and eh_gestor(user) and not gerencia_de(user))
    if incluir_sem_pdv:
        filtro |= Q(parceiro__isnull=True)
    return qs.filter(filtro)


@dataclass
class ResumoEnvio:
    enviados: int = 0
    erros: int = 0
    ignorados: int = 0
    detalhes: list[str] | None = None

    def __post_init__(self):
        if self.detalhes is None:
            self.detalhes = []


@dataclass
class DestinoEnvio:
    jid: str
    nome: str
    parceiro: Parceiro | None = None
    destinatario: Destinatario | None = None


def whatsapp_do_usuario(user) -> str:
    perfil = getattr(user, "perfil_staff", None) if user else None
    return (getattr(perfil, "whatsapp", "") or "").strip()


def destinos_para_envio(
    user: AbstractBaseUser | None,
    flag: str,
    parceiro: Parceiro | None = None,
    *,
    somente_grupos: bool = False,
) -> list[DestinoEnvio]:
    """OSAB/Comissionamento: empresário do parceiro. Demais: gestor usa Destinatários; especialista, o próprio WhatsApp."""
    if flag == "envio_osab" and parceiro is not None and not somente_grupos:
        return destinos_osab(user, parceiro)
    if flag == "envio_comissionamento" and parceiro is not None and not somente_grupos:
        return destinos_comissionamento(user, parceiro)
    if user is not None and not eh_gestor(user):
        jid = whatsapp_do_usuario(user)
        if not jid:
            return []
        nome = (user.get_full_name() or user.get_username() or "Especialista").strip()
        return [DestinoEnvio(jid=jid, nome=nome, parceiro=parceiro)]
    return [
        DestinoEnvio(jid=d.jid, nome=d.nome, parceiro=d.parceiro, destinatario=d)
        for d in destinatarios_para(flag, parceiro, somente_grupos=somente_grupos)
    ]


def destinos_comissionamento(
    user: AbstractBaseUser | None, parceiro: Parceiro
) -> list[DestinoEnvio]:
    """Comissionamento: empresário(s) cadastrado(s) no parceiro.
    Sem empresário cadastrado, aplica fallback para o telefone do parceiro ou Destinatários configurados.
    """
    from ..destinatarios_especialista import jid_individual

    destinos: list[DestinoEnvio] = []
    vistos: set[str] = set()

    def add(
        jid: str,
        nome: str,
        *,
        grupo: bool = False,
        destinatario: Destinatario | None = None,
    ) -> None:
        chave = (jid or "").strip() if grupo else jid_individual(jid)
        if not chave or chave in vistos:
            return
        vistos.add(chave)
        destinos.append(
            DestinoEnvio(
                jid=chave, nome=nome, parceiro=parceiro, destinatario=destinatario
            )
        )

    n_empresario = 0
    for contato in parceiro.contatos.filter(ativo=True):
        if contato.eh_empresario() and contato.telefone:
            antes = len(destinos)
            add(contato.telefone, contato.nome or "Empresário")
            if len(destinos) > antes:
                n_empresario += 1

    if n_empresario == 0 and parceiro.telefone:
        add(parceiro.telefone, parceiro.contato_nome or parceiro.nome or "Empresário")

    if not destinos:
        for dest in Destinatario.objects.filter(
            parceiro=parceiro,
            ativo=True,
            envio_comissionamento=True,
        ):
            add(
                dest.jid,
                dest.nome,
                grupo=(dest.tipo == Destinatario.TipoDestino.GRUPO),
                destinatario=dest,
            )

    if not destinos:
        for dest in Destinatario.objects.filter(
            parceiro=parceiro,
            ativo=True,
            tipo=Destinatario.TipoDestino.GRUPO,
        ):
            add(dest.jid, dest.nome, grupo=True, destinatario=dest)

    return destinos


def destinos_osab(user: AbstractBaseUser | None, parceiro: Parceiro) -> list[DestinoEnvio]:
    """OSAB: empresário e especialista. Sem empresário, usa o grupo cadastrado em Destinatários."""
    from ..destinatarios_especialista import jid_individual

    destinos: list[DestinoEnvio] = []
    vistos: set[str] = set()

    def add(jid: str, nome: str, *, grupo: bool = False) -> None:
        chave = (jid or "").strip() if grupo else jid_individual(jid)
        if not chave or chave in vistos:
            return
        vistos.add(chave)
        destinos.append(DestinoEnvio(jid=chave, nome=nome, parceiro=parceiro))

    n_empresario = 0
    for contato in parceiro.contatos.filter(ativo=True):
        if contato.eh_empresario():
            antes = len(destinos)
            add(contato.telefone, contato.nome or "Empresário")
            if len(destinos) > antes:
                n_empresario += 1

    if n_empresario == 0:
        for dest in Destinatario.objects.filter(
            parceiro=parceiro,
            ativo=True,
            tipo=Destinatario.TipoDestino.GRUPO,
            envio_osab=True,
        ):
            add(dest.jid, dest.nome, grupo=True)

    spec = parceiro.especialista
    if spec and not (user is not None and spec.id == user.id):
        add(
            whatsapp_do_usuario(spec),
            (spec.get_full_name() or spec.get_username() or "Especialista").strip(),
        )
    return destinos


def emails_para_envio(
    user: AbstractBaseUser | None,
    flag: str,
    parceiro: Parceiro | None = None,
) -> list[str]:
    """Gestor: e-mails marcados no Destinatário. Especialista não dispara e-mail de Gestão."""
    if user is not None and not eh_gestor(user):
        return []
    flag_email = FLAG_EMAIL.get(flag)
    if not flag_email:
        return []
    qs = Destinatario.objects.filter(ativo=True, **{flag_email: True}).exclude(email="")
    if parceiro is not None:
        qs = qs.filter(parceiro=parceiro)
    vistos: list[str] = []
    for raw in qs.values_list("email", flat=True):
        mail = (raw or "").strip()
        if mail and mail.lower() not in {v.lower() for v in vistos}:
            vistos.append(mail)
    return vistos


def emails_fpd_especialista(parceiro: Parceiro | None) -> list[str]:
    """FPD: e-mail vai para o especialista NIO vinculado ao PDV."""
    if parceiro is None:
        return []
    spec = parceiro.especialista
    if not spec:
        return []
    mail = (spec.email or "").strip()
    if mail and "@" in mail:
        return [mail]
    return []


def _talvez_email(
    *,
    flag: str,
    tipo: str,
    mensagem: str,
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
    arquivo_bytes: bytes = b"",
    nome_arquivo: str = "",
    resumo: ResumoEnvio,
    assunto: str = "",
    corpo_texto: str = "",
    corpo_html: str = "",
    destinos_email: list[str] | None = None,
) -> None:
    if destinos_email is None:
        destinos = emails_para_envio(user, flag, parceiro)
    else:
        destinos = destinos_email
    if not destinos:
        return
    if not smtp_configurado():
        resumo.detalhes.append("E-mail: SMTP não configurado.")
        return
    anexos = []
    if arquivo_bytes and nome_arquivo:
        mime = mimetypes.guess_type(nome_arquivo)[0] or XLSX_MIME
        anexos.append((nome_arquivo, arquivo_bytes, mime))
    titulo = dict(EnvioWhatsApp.Tipo.choices).get(tipo, tipo)
    pdv = parceiro.nome if parceiro else "Gestão"
    ok, erro = enviar_email_com_anexos(
        destinos,
        assunto=assunto or f"[NIO GC] {titulo} — {pdv}",
        corpo_texto=corpo_texto or (mensagem or "").replace("*", ""),
        corpo_html=corpo_html,
        anexos=anexos,
    )
    if ok:
        resumo.enviados += 1
        resumo.detalhes.append(f"OK e-mail → {', '.join(destinos)}")
    else:
        resumo.erros += 1
        resumo.detalhes.append(f"ERRO e-mail: {erro}")


def _msg_sem_destino(user: AbstractBaseUser | None) -> str:
    if user is not None and not eh_gestor(user):
        return "Cadastre seu WhatsApp em Meu perfil para receber as máscaras."
    return "Nenhum destinatário ativo para este envio."


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
    destino_nome: str = "",
) -> EnvioWhatsApp:
    if result.ok:
        status = EnvioWhatsApp.Status.ENVIADO
        erro = ""
    else:
        status = EnvioWhatsApp.Status.ERRO
        erro = result.error
    nome = destino_nome or (destinatario.nome if destinatario else "") or ""
    return EnvioWhatsApp.objects.create(
        tipo=tipo,
        status=status,
        parceiro=parceiro,
        destinatario=destinatario,
        destino_jid=result.destino or (destinatario.jid if destinatario else ""),
        destino_nome=nome,
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
    destinos: list[DestinoEnvio] | list[Destinatario],
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
    flag: str = "",
    arquivo_bytes: bytes = b"",
    nome_arquivo: str = "",
) -> ResumoEnvio:
    resumo = ResumoEnvio()
    if not mensagem.strip():
        resumo.ignorados += 1
        resumo.detalhes.append("Mensagem vazia — nada enviado.")
        return resumo
    if not syncwa_configurado():
        resumo.erros += 1
        resumo.detalhes.append("WhatsApp (Evolution) não configurado.")
        return resumo
    lista = [
        dest
        if isinstance(dest, DestinoEnvio)
        else DestinoEnvio(jid=dest.jid, nome=dest.nome, parceiro=dest.parceiro, destinatario=dest)
        for dest in destinos
    ]
    if not lista:
        resumo.ignorados += 1
        resumo.detalhes.append(_msg_sem_destino(user))
        return resumo

    teste = modo_teste_ativo()
    for dest in lista:
        result = enviar_texto(dest.jid, mensagem)
        _registrar(
            tipo=tipo,
            mensagem=mensagem,
            destinatario=dest.destinatario,
            parceiro=parceiro or dest.parceiro,
            user=user,
            result=result,
            modo_teste=teste,
            destino_nome=dest.nome,
        )
        if result.ok:
            resumo.enviados += 1
            resumo.detalhes.append(f"OK → {dest.nome}")
        else:
            resumo.erros += 1
            resumo.detalhes.append(f"ERRO → {dest.nome}: {result.error}")
    if flag:
        _talvez_email(
            flag=flag,
            tipo=tipo,
            mensagem=mensagem,
            parceiro=parceiro,
            user=user,
            arquivo_bytes=arquivo_bytes,
            nome_arquivo=nome_arquivo,
            resumo=resumo,
        )
    return resumo


def enviar_teste(user: AbstractBaseUser | None = None) -> ResumoEnvio:
    texto = (
        "✅ *NIO GC Tickets — teste WhatsApp*\n\n"
        "Se você recebeu esta mensagem, a integração está ok."
    )
    from django.conf import settings

    jid = (getattr(settings, "SYNCWA_TEST_JID", "") or "").strip()
    if user is not None and not eh_gestor(user):
        return _enviar_para_lista(
            tipo=EnvioWhatsApp.Tipo.TESTE,
            mensagem=texto,
            destinos=destinos_para_envio(user, "envio_capilaridade"),
            parceiro=None,
            user=user,
        )
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
        return ResumoEnvio(erros=1, detalhes=["WhatsApp (Evolution) não configurado."])
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
    filtros: dict | None = None,
    *,
    enviar_motivacional: bool = True,
) -> ResumoEnvio:
    import time

    from ..motivacional import montar_mensagem_motivacional_pdv

    ano, mes = periodo_ativo()
    destinos = destinos_para_envio(user, "envio_capilaridade", parceiro)
    if not destinos:
        return ResumoEnvio(ignorados=1, detalhes=[_msg_sem_destino(user)])

    resumo_total = ResumoEnvio()

    # 1. Envia o Bom Dia com frase motivacional de vendas antes do relatório
    if enviar_motivacional:
        msg_motivacional = montar_mensagem_motivacional_pdv(parceiro)
        resumo_mot = _enviar_para_lista(
            tipo=EnvioWhatsApp.Tipo.CAPILARIDADE,
            mensagem=msg_motivacional,
            destinos=destinos,
            parceiro=parceiro,
            user=user,
            flag="",
        )
        resumo_total.enviados += resumo_mot.enviados
        resumo_total.erros += resumo_mot.erros
        resumo_total.ignorados += resumo_mot.ignorados
        resumo_total.detalhes.extend(resumo_mot.detalhes)
        # Breve pausa para garantir ordem cronológica no WhatsApp
        time.sleep(1)

    # 2. Envia o relatório de capilaridade (planilha + máscara) conforme a regra atual
    mensagem = montar_mascara_pdv(parceiro, ano, mes, filtros)
    arquivo_bytes, nome_arquivo = planilha_capilaridade(parceiro, filtros)
    resumo_anexo = _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.CAPILARIDADE,
        mensagem=mensagem,
        caption=f"📁 *Capilaridade* — {parceiro.nome}",
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_capilaridade",
    )
    resumo_total.enviados += resumo_anexo.enviados
    resumo_total.erros += resumo_anexo.erros
    resumo_total.ignorados += resumo_anexo.ignorados
    resumo_total.detalhes.extend(resumo_anexo.detalhes)
    return resumo_total


def enviar_resumo_capilaridade(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
    filtros: dict | None = None,
) -> ResumoEnvio:
    """Envia o resumo geral para grupos com flag capilaridade (JID único)."""
    ano, mes = periodo_ativo()
    msg = resumo_geral(parceiros, ano, mes, filtros)
    destinos = destinos_para_envio(
        user, "envio_capilaridade", somente_grupos=True
    )
    vistos: set[str] = set()
    unicos: list[DestinoEnvio] = []
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
        flag="envio_capilaridade",
    )


def enviar_capilaridade_todos(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
    *,
    incluir_resumo: bool = False,
    filtros: dict | None = None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    if incluir_resumo:
        parte = enviar_resumo_capilaridade(parceiros, user, filtros)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.extend(parte.detalhes)

    for p in parceiros:
        try:
            parte = enviar_capilaridade_pdv(p, user, filtros)
        except Exception as exc:
            parte = ResumoEnvio(erros=1, detalhes=[f"{p.nome}: {exc}"])
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
    destinos = destinos_para_envio(user, "envio_osab", parceiro)
    arquivo_bytes, nome_arquivo = planilha_osab(parceiro)
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.OSAB,
        mensagem=hist.mensagem,
        caption=f"📁 *OSAB* — {parceiro.nome}",
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_osab",
    )


def enviar_fpd_pdv(parceiro: Parceiro, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    from ..fpd_format import assunto_email_fpd, corpo_texto_email_fpd, html_email_fpd

    rel = RelatorioFPD.objects.filter(parceiro=parceiro).order_by("-criado_em").first()
    if not rel or not rel.mensagem.strip():
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem relatório FPD."])
    destinos = destinos_para_envio(user, "envio_fpd", parceiro)
    arquivo_bytes, nome_arquivo = planilha_fpd(rel)
    email_destinos = emails_fpd_especialista(parceiro)
    resumo = _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.FPD,
        mensagem=rel.mensagem,
        caption=f"📁 *FPD* — {rel.pdv_nome}",
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_fpd",
        email_assunto=assunto_email_fpd(rel),
        email_corpo_texto=corpo_texto_email_fpd(rel),
        email_corpo_html=html_email_fpd(rel),
        email_destinos=email_destinos,
    )
    if not email_destinos and smtp_configurado():
        resumo.detalhes.append(
            f"E-mail FPD não enviado: PDV {parceiro.nome} sem especialista com e-mail cadastrado."
        )
    # Alerta crítico global
    from django.conf import settings

    limite = float(getattr(settings, "FPD_PERCENTUAL_CRITICO", 30))
    if eh_gestor(user) and rel.percentual >= limite:
        criticos = destinos_para_envio(user, "envio_fpd_critico")
        if criticos:
            alerta = (
                f"🚨 *Alerta FPD crítico — {rel.pdv_nome}*\n"
                f"Percentual FPD: *{rel.percentual:.2f}%* (limite {limite:.2f}%)\n\n"
                f"{rel.mensagem}"
            )
            parte = _enviar_para_lista(
                tipo=EnvioWhatsApp.Tipo.FPD_CRITICO,
                mensagem=alerta,
                destinos=criticos,
                parceiro=parceiro,
                user=user,
                flag="envio_fpd_critico",
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
    destinos = destinos_para_envio(user, "envio_churn", parceiro)
    arquivo_bytes, nome_arquivo = planilha_churn(parceiro)
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.CHURN,
        mensagem=row.mensagem,
        caption=f"📁 *Churn* — {parceiro.nome}",
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_churn",
    )


def _unicos_jid(destinos: list[DestinoEnvio]) -> list[DestinoEnvio]:
    vistos: set[str] = set()
    unicos: list[DestinoEnvio] = []
    for d in destinos:
        chave = d.jid.strip().lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(d)
    return unicos


def _enviar_com_anexo(
    *,
    tipo: str,
    mensagem: str,
    caption: str,
    destinos: list[DestinoEnvio] | list[Destinatario],
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
    arquivo_bytes: bytes,
    nome_arquivo: str,
    flag: str = "",
    email_assunto: str = "",
    email_corpo_texto: str = "",
    email_corpo_html: str = "",
    email_destinos: list[str] | None = None,
) -> ResumoEnvio:
    """Envia documento (+ texto se caption/mensagem > 900 chars)."""
    resumo = ResumoEnvio()
    if not syncwa_configurado():
        return ResumoEnvio(erros=1, detalhes=["WhatsApp (Evolution) não configurado."])
    lista = [
        dest
        if isinstance(dest, DestinoEnvio)
        else DestinoEnvio(jid=dest.jid, nome=dest.nome, parceiro=dest.parceiro, destinatario=dest)
        for dest in destinos
    ]
    if not lista:
        return ResumoEnvio(ignorados=1, detalhes=[_msg_sem_destino(user)])

    teste = modo_teste_ativo()
    msg = (mensagem or "").strip() or caption
    texto_extra = bool(msg) and (not arquivo_bytes or len(msg) > 900)

    for dest in lista:
        if arquivo_bytes:
            result_doc = enviar_documento(
                dest.jid,
                conteudo=arquivo_bytes,
                file_name=nome_arquivo,
                caption=caption if texto_extra else msg[:1024],
            )
            _registrar(
                tipo=tipo,
                mensagem=f"[anexo] {nome_arquivo}\n{caption}",
                destinatario=dest.destinatario,
                parceiro=parceiro or dest.parceiro,
                user=user,
                result=result_doc,
                modo_teste=teste,
                destino_nome=dest.nome,
            )
            if result_doc.ok:
                resumo.enviados += 1
                resumo.detalhes.append(f"OK anexo → {dest.nome}")
            else:
                resumo.erros += 1
                resumo.detalhes.append(f"ERRO anexo → {dest.nome}: {result_doc.error}")
                continue

        if texto_extra or not arquivo_bytes:
            result_txt = enviar_texto(dest.jid, msg)
            _registrar(
                tipo=tipo,
                mensagem=msg,
                destinatario=dest.destinatario,
                parceiro=parceiro or dest.parceiro,
                user=user,
                result=result_txt,
                modo_teste=teste,
                destino_nome=dest.nome,
            )
            if result_txt.ok:
                resumo.enviados += 1
                resumo.detalhes.append(f"OK texto → {dest.nome}")
            else:
                resumo.erros += 1
                resumo.detalhes.append(f"ERRO texto → {dest.nome}: {result_txt.error}")
    if flag:
        _talvez_email(
            flag=flag,
            tipo=tipo,
            mensagem=msg,
            parceiro=parceiro,
            user=user,
            arquivo_bytes=arquivo_bytes,
            nome_arquivo=nome_arquivo,
            resumo=resumo,
            assunto=email_assunto,
            corpo_texto=email_corpo_texto,
            corpo_html=email_corpo_html,
            destinos_email=email_destinos,
        )
    return resumo


def _ler_arquivo_relatorio(arquivo_field, nome_fallback: str) -> tuple[bytes, str]:
    if not arquivo_field:
        return b"", nome_fallback
    try:
        with arquivo_field.open("rb") as fh:
            return fh.read(), Path(arquivo_field.name).name
    except Exception as exc:
        raise RuntimeError(f"Falha ao ler anexo: {exc}") from exc


def _caption_curta(rel: RelatorioComissionamento) -> str:
    return (
        f"📁 *Comissionamento* — {rel.pdv_nome}\n"
        f"Pedidos: {rel.qtd_pedido} · Linhas: {rel.qtd_linha}"
    )


def formatar_mensagem_comissionamento(rel: RelatorioComissionamento) -> str:
    msg = (rel.mensagem or "").strip()
    if not msg:
        return ""

    email_esp = ""
    if rel.parceiro and rel.parceiro.especialista and rel.parceiro.especialista.email:
        email_esp = rel.parceiro.especialista.email.strip()
    if not email_esp:
        email_esp = "rogerio.pacheco@niointernet.com.br"

    if "Orientação para envio do email" in msg or "Orientaçaõ para envio do email" in msg:
        msg_atualizada = re.sub(
            r"Com c[óo]pia para:\s*[^ \t\n\r]+(?:\s*@@?\s*[^ \t\n\r]+)?\s*e\s*PP-GestaodosParceiros@niointernet\.com\.br",
            f"Com cópia para: {email_esp} e PP-GestaodosParceiros@niointernet.com.br",
            msg,
            flags=re.IGNORECASE,
        )
        return msg_atualizada

    m_razao = re.search(r"RAZ[ÃA]O SOCIAL:\s*(.+)", msg, flags=re.IGNORECASE)
    empresa = m_razao.group(1).strip() if m_razao else ""
    if not empresa or empresa == "-":
        empresa = (rel.pdv_nome or (rel.parceiro.nome if rel.parceiro else "")).strip()

    m_ciclo = re.search(r"REFER[ÊE]NCIA:\s*(?:COMISSAO\s*)?([^\n\r]+)", msg, flags=re.IGNORECASE)
    ciclo = m_ciclo.group(1).strip() if m_ciclo else ""
    ciclo = re.sub(r"^COMISS[ÃA]O\s*", "", ciclo, flags=re.IGNORECASE).strip()

    assunto_email = f"{empresa}_{ciclo}" if ciclo and ciclo != "-" else f"{empresa}_[CICLO]"

    bloco = (
        "\n\nOrientação para envio do email: \n\n"
        "Enviar o email para recebimentonfes@niointernet.com.br\n"
        f"Com cópia para: {email_esp} e PP-GestaodosParceiros@niointernet.com.br\n\n"
        "No corpo do email retirar assinatura e não escrever nada no corpo do email \n"
        f"E o assunto do email deverá ser {assunto_email}"
    )
    return msg + bloco


def enviar_comissionamento_pdv(
    parceiro: Parceiro,
    user: AbstractBaseUser | None = None,
    *,
    relatorio: RelatorioComissionamento | None = None,
) -> ResumoEnvio:
    rel = relatorio or (
        RelatorioComissionamento.objects.filter(parceiro=parceiro)
        .order_by("-criado_em")
        .first()
    )
    if not rel:
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem relatório de comissionamento."])
    destinos = destinos_para_envio(user, "envio_comissionamento", parceiro)
    try:
        arquivo_bytes, nome_arquivo = _ler_arquivo_relatorio(
            rel.arquivo, f"comissionamento_{parceiro.nome}.xlsx"
        )
        stem = Path(nome_arquivo).stem
        stem_limpo = re.sub(r"(_[a-zA-Z0-9]{7})+$", "", stem)
        if stem_limpo:
            nome_arquivo = f"{stem_limpo}.xlsx"
    except RuntimeError as exc:
        return ResumoEnvio(erros=1, detalhes=[str(exc)])

    mensagem_final = formatar_mensagem_comissionamento(rel)
    if mensagem_final and mensagem_final != rel.mensagem:
        rel.mensagem = mensagem_final
        rel.save(update_fields=["mensagem"])

    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.COMISSIONAMENTO,
        mensagem=mensagem_final or rel.mensagem,
        caption=_caption_curta(rel),
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_comissionamento",
    )


def enviar_comissionamento_lote(
    lote_id: int,
    user: AbstractBaseUser | None = None,
    parceiros=None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    qs = RelatorioComissionamento.objects.filter(lote_id=lote_id).select_related("parceiro")
    qs = _filtrar_lote_escopo(qs, user, parceiros, incluir_sem_pdv=False)
    if not qs.exists():
        return ResumoEnvio(ignorados=1, detalhes=["Lote sem relatórios de comissionamento."])
    for rel in qs:
        parte = enviar_comissionamento_pdv(rel.parceiro, user, relatorio=rel)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.append(
            f"— {rel.pdv_nome}: {parte.enviados} ok / {parte.erros} erro / {parte.ignorados} ign"
        )
    return total


def enviar_comissionamento_email_especialista(
    relatorio: RelatorioComissionamento,
    user: AbstractBaseUser | None = None,
) -> tuple[bool, str]:
    """Envia por e-mail a planilha e o texto de comissionamento para o especialista do parceiro."""
    if not smtp_configurado():
        return False, "Serviço de e-mail (SMTP) não configurado no servidor."

    especialista = relatorio.parceiro.especialista if relatorio.parceiro else None
    email_dest = (especialista.email if especialista else "").strip()
    if not email_dest or "@" not in email_dest:
        nome_esp = (especialista.get_full_name() or especialista.username) if especialista else "Nenhum especialista vinculado"
        return False, f"O parceiro {relatorio.pdv_nome} não possui especialista com e-mail cadastrado ({nome_esp})."

    anexos: list[tuple[str, bytes, str]] = []
    if relatorio.arquivo:
        try:
            dados_arquivo, nome_bruto = _ler_arquivo_relatorio(
                relatorio.arquivo, f"comissionamento_{relatorio.pdv_nome}.xlsx"
            )
            stem = Path(nome_bruto).stem
            stem_limpo = re.sub(r"(_[a-zA-Z0-9]{7})+$", "", stem)
            nome_arquivo = f"{stem_limpo}.xlsx" if stem_limpo else f"comissionamento_{relatorio.pdv_nome}.xlsx"
            mime = mimetypes.guess_type(nome_arquivo)[0] or XLSX_MIME
            anexos.append((nome_arquivo, dados_arquivo, mime))
        except Exception as exc:
            return False, f"Não foi possível ler a planilha de comissionamento: {exc}"

    mensagem_final = formatar_mensagem_comissionamento(relatorio)
    msg = (mensagem_final or relatorio.mensagem or "").strip()

    m_razao = re.search(r"RAZ[ÃA]O SOCIAL:\s*(.+)", msg, flags=re.IGNORECASE)
    empresa = m_razao.group(1).strip() if m_razao else ""
    if not empresa or empresa == "-":
        empresa = (relatorio.pdv_nome or (relatorio.parceiro.nome if relatorio.parceiro else "")).strip()

    m_ciclo = re.search(r"REFER[ÊE]NCIA:\s*(?:COMISSAO\s*)?([^\n\r]+)", msg, flags=re.IGNORECASE)
    ciclo = m_ciclo.group(1).strip() if m_ciclo else ""
    ciclo = re.sub(r"^COMISS[ÃA]O\s*", "", ciclo, flags=re.IGNORECASE).strip()

    if ciclo and ciclo != "-":
        assunto = f"Comissionamento — {empresa}_{ciclo}"
    else:
        assunto = f"Comissionamento — {empresa}"

    nome_esp_display = (especialista.get_full_name() or especialista.username or "Especialista").strip()
    corpo_texto = (mensagem_final or relatorio.mensagem or "").replace("\r\n", "\n").replace("\n", "\r\n").replace("*", "")
    corpo_html = formatar_html_email_comissionamento(relatorio, nome_esp_display)

    ok, erro = enviar_email_com_anexos(
        [email_dest],
        assunto=assunto,
        corpo_texto=corpo_texto,
        corpo_html=corpo_html,
        anexos=anexos,
    )
    if ok:
        return True, f"Planilha e texto de comissionamento enviados para {email_dest} com sucesso!"
    return False, f"Falha ao enviar e-mail para {email_dest}: {erro}"


def formatar_html_email_comissionamento(rel: RelatorioComissionamento, nome_esp: str) -> str:
    """Gera HTML com divs e estilos inline compatíveis com o Outlook/Word e outros clientes de e-mail."""
    import html

    msg = formatar_mensagem_comissionamento(rel) or rel.mensagem or ""

    partes = re.split(r"(?i)\n*(?=Orienta[çc][ãa]o para envio do email:?)", msg, maxsplit=1)
    corpo_dados = partes[0].strip()
    corpo_orientacao = partes[1].strip() if len(partes) > 1 else ""

    def processar_linhas(texto: str) -> str:
        linhas_out = []
        for raw in texto.splitlines():
            linha = raw.strip()
            if not linha:
                linhas_out.append('<div style="height: 8px; line-height: 8px;">&nbsp;</div>')
                continue
            escaped = html.escape(linha)
            formatado = re.sub(r"\*([^*\n\r]+)\*", r"<strong>\1</strong>", escaped)
            if "TOTAL " in linha or "Conferência total" in linha:
                formatado = f'<span style="color: #047857; font-weight: bold;">{formatado}</span>'
            linhas_out.append(f'<div style="margin: 0; padding: 2px 0; line-height: 1.5;">{formatado}</div>')
        return "\n".join(linhas_out)

    dados_html = processar_linhas(corpo_dados)
    orientacao_html = processar_linhas(corpo_orientacao) if corpo_orientacao else ""

    orientacao_box = ""
    if orientacao_html:
        orientacao_box = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 16px; background-color: #fefce8; border: 1px solid #fef08a; border-left: 4px solid #eab308; border-radius: 6px;">
          <tr>
            <td style="padding: 14px 16px; font-family: Arial, Helvetica, sans-serif; font-size: 13px; color: #713f12; line-height: 1.5;">
              {orientacao_html}
            </td>
          </tr>
        </table>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
</head>
<body style="margin: 0; padding: 10px; background-color: #ffffff; font-family: Arial, Helvetica, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #1e293b; line-height: 1.6; max-width: 650px;">
    <tr>
      <td style="padding: 0 0 14px 0;">
        <p style="margin: 0 0 6px 0; font-size: 15px;">Olá, <strong>{html.escape(nome_esp)}</strong>!</p>
        <p style="margin: 0; color: #475569;">Segue em anexo a planilha e abaixo os dados da apuração de comissionamento do parceiro <strong>{html.escape(rel.pdv_nome)}</strong>:</p>
      </td>
    </tr>
    <tr>
      <td style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 18px 20px; font-family: Arial, Helvetica, sans-serif; font-size: 13px; color: #1e293b;">
        {dados_html}
      </td>
    </tr>
    {f"<tr><td>{orientacao_box}</td></tr>" if orientacao_box else ""}
    <tr>
      <td style="padding-top: 20px; font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9;">
        NIO GC Tickets · Gestão de Parceiros
      </td>
    </tr>
  </table>
</body>
</html>"""


def enviar_comissionamento_lote_email(
    lote_id: int,
    user: AbstractBaseUser | None = None,
    parceiros=None,
) -> ResumoEnvio:
    """Envia em lote as planilhas e mensagens de comissionamento para os especialistas de cada PDV."""
    total = ResumoEnvio()
    qs = RelatorioComissionamento.objects.filter(lote_id=lote_id).select_related(
        "parceiro__especialista"
    )
    qs = _filtrar_lote_escopo(qs, user, parceiros, incluir_sem_pdv=False)
    if not qs.exists():
        return ResumoEnvio(ignorados=1, detalhes=["Lote sem relatórios de comissionamento."])

    for rel in qs:
        ok, msg_retorno = enviar_comissionamento_email_especialista(rel, user)
        if ok:
            total.enviados += 1
            total.detalhes.append(f"OK → {rel.pdv_nome}: {msg_retorno}")
        else:
            total.erros += 1
            total.detalhes.append(f"ERRO → {rel.pdv_nome}: {msg_retorno}")

    return total


def enviar_tarefa(rel: RelatorioTarefa, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    destinos = destinos_para_envio(
        user, "envio_tarefas", rel.parceiro, somente_grupos=not rel.parceiro_id
    )
    if not rel.parceiro_id:
        destinos = _unicos_jid(destinos)

    try:
        arquivo_bytes, nome_arquivo = _ler_arquivo_relatorio(
            rel.arquivo, f"tarefas_{rel.tipo_relatorio}.xlsx"
        )
    except RuntimeError as exc:
        return ResumoEnvio(erros=1, detalhes=[str(exc)])

    caption = (
        f"📋 *Tarefas* — {rel.get_tipo_relatorio_display()}\n"
        f"{rel.pdv_nome or 'MG'} · total {rel.total}"
    )
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.TAREFAS,
        mensagem=rel.mensagem,
        caption=caption,
        destinos=destinos,
        parceiro=rel.parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_tarefas",
    )


def enviar_tarefas_todos(
    parceiros,
    user: AbstractBaseUser | None = None,
) -> ResumoEnvio:
    """Último relatório de cada PDV do escopo (+ fechadas/futuros, se gestor)."""
    total = ResumoEnvio()
    vistos: set[int] = set()
    rels: list[RelatorioTarefa] = []
    for p in parceiros:
        rel = RelatorioTarefa.objects.filter(parceiro=p).order_by("-criado_em").first()
        if rel and rel.id not in vistos:
            vistos.add(rel.id)
            rels.append(rel)
    if user is None or (eh_gestor(user) and not gerencia_de(user)):
        for tipo in (
            RelatorioTarefa.TipoRelatorio.FECHADAS,
            RelatorioTarefa.TipoRelatorio.FUTUROS,
        ):
            rel = (
                RelatorioTarefa.objects.filter(parceiro__isnull=True, tipo_relatorio=tipo)
                .order_by("-criado_em")
                .first()
            )
            if rel and rel.id not in vistos:
                vistos.add(rel.id)
                rels.append(rel)
    if not rels:
        return ResumoEnvio(ignorados=1, detalhes=["Nenhum relatório de tarefas no escopo."])
    for rel in rels:
        parte = enviar_tarefa(rel, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        rotulo = rel.pdv_nome or rel.get_tipo_relatorio_display()
        total.detalhes.append(f"— {rotulo}: {parte.enviados} ok / {parte.erros} erro")
    return total


def enviar_tarefas_lote(
    lote_id: int,
    user: AbstractBaseUser | None = None,
    parceiros=None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    qs = RelatorioTarefa.objects.filter(lote_id=lote_id).select_related("parceiro")
    qs = _filtrar_lote_escopo(qs, user, parceiros)
    if not qs.exists():
        return ResumoEnvio(ignorados=1, detalhes=["Lote sem relatórios de tarefas."])
    for rel in qs:
        parte = enviar_tarefa(rel, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        rotulo = rel.pdv_nome or rel.get_tipo_relatorio_display()
        total.detalhes.append(f"— {rotulo}: {parte.enviados} ok / {parte.erros} erro")
    return total


def enviar_venda_indevida(rel: RelatorioVendaIndevida, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    destinos = destinos_para_envio(
        user,
        "envio_venda_indevida",
        None if rel.consolidado or not rel.parceiro_id else rel.parceiro,
        somente_grupos=bool(rel.consolidado or not rel.parceiro_id),
    )
    if rel.consolidado or not rel.parceiro_id:
        destinos = _unicos_jid(destinos)

    try:
        arquivo_bytes, nome_arquivo = _ler_arquivo_relatorio(rel.arquivo, "vi.xlsx")
    except RuntimeError as exc:
        return ResumoEnvio(erros=1, detalhes=[str(exc)])

    caption = (
        f"🚨 *VI* — {'consolidado' if rel.consolidado else rel.pdv_nome}\n"
        f"Total: {rel.total}"
    )
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.VENDA_INDEVIDA,
        mensagem=rel.mensagem,
        caption=caption,
        destinos=destinos,
        parceiro=rel.parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_venda_indevida",
    )


def enviar_venda_indevida_lote(
    lote_id: int,
    user: AbstractBaseUser | None = None,
    *,
    incluir_consolidado: bool = True,
    parceiros=None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    qs = RelatorioVendaIndevida.objects.filter(lote_id=lote_id).select_related("parceiro")
    if not incluir_consolidado:
        qs = qs.filter(consolidado=False)
    qs = _filtrar_lote_escopo(qs, user, parceiros)
    if not qs.exists():
        return ResumoEnvio(ignorados=1, detalhes=["Lote sem relatórios de venda indevida."])
    for rel in qs:
        parte = enviar_venda_indevida(rel, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        rotulo = "consolidado" if rel.consolidado else rel.pdv_nome
        total.detalhes.append(f"— {rotulo}: {parte.enviados} ok / {parte.erros} erro")
    return total


def enviar_recompra(rel: RelatorioRecompra, user: AbstractBaseUser | None = None) -> ResumoEnvio:
    destinos = destinos_para_envio(
        user,
        "envio_recompra",
        None if rel.consolidado or not rel.parceiro_id else rel.parceiro,
        somente_grupos=bool(rel.consolidado or not rel.parceiro_id),
    )
    if rel.consolidado or not rel.parceiro_id:
        destinos = _unicos_jid(destinos)

    try:
        arquivo_bytes, nome_arquivo = _ler_arquivo_relatorio(rel.arquivo, "recompra.xlsx")
    except RuntimeError as exc:
        return ResumoEnvio(erros=1, detalhes=[str(exc)])

    caption = (
        f"🔁 *Recompra* — {'consolidado' if rel.consolidado else rel.pdv_nome}\n"
        f"Total: {rel.total}"
    )
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.RECOMPRA,
        mensagem=rel.mensagem,
        caption=caption,
        destinos=destinos,
        parceiro=rel.parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_recompra",
    )


def enviar_recompra_lote(
    lote_id: int,
    user: AbstractBaseUser | None = None,
    *,
    incluir_consolidado: bool = True,
    parceiros=None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    qs = RelatorioRecompra.objects.filter(lote_id=lote_id).select_related("parceiro")
    if not incluir_consolidado:
        qs = qs.filter(consolidado=False)
    qs = _filtrar_lote_escopo(qs, user, parceiros)
    if not qs.exists():
        return ResumoEnvio(ignorados=1, detalhes=["Lote sem relatórios de recompra."])
    for rel in qs:
        parte = enviar_recompra(rel, user)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        rotulo = "consolidado" if rel.consolidado else rel.pdv_nome
        total.detalhes.append(f"— {rotulo}: {parte.enviados} ok / {parte.erros} erro")
    return total


def enviar_parcial(
    parceiro: Parceiro,
    user: AbstractBaseUser | None,
    *,
    arquivo_bytes: bytes,
    nome_arquivo: str,
    caption: str = "",
) -> ResumoEnvio:
    if not arquivo_bytes:
        return ResumoEnvio(erros=1, detalhes=["Anexe uma imagem para o parcial."])
    from ..pipelines.resultados import caption_parcial_envio

    texto = caption_parcial_envio(caption, parceiro)
    destinos = destinos_para_envio(user, "envio_resultados", parceiro)
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.PARCIAL,
        mensagem=texto,
        caption=texto,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_resultados",
    )


def enviar_parcial_todos(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None,
    *,
    arquivo_bytes: bytes,
    nome_arquivo: str,
    caption: str = "",
) -> ResumoEnvio:
    total = ResumoEnvio()
    if not arquivo_bytes:
        return ResumoEnvio(erros=1, detalhes=["Anexe uma imagem para o parcial."])
    for p in parceiros:
        parte = enviar_parcial(
            p,
            user,
            arquivo_bytes=arquivo_bytes,
            nome_arquivo=nome_arquivo,
            caption=caption,
        )
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.append(f"— {p.nome}: {parte.enviados} ok / {parte.erros} erro")
    if not parceiros:
        total.ignorados += 1
        total.detalhes.append("Nenhum PDV no escopo.")
    return total


def enviar_acumulado_pdv(
    parceiro: Parceiro,
    user: AbstractBaseUser | None = None,
    *,
    ano: int | None = None,
    mes: int | None = None,
) -> ResumoEnvio:
    from ..pipelines.resultados import linhas_acumulado, mensagem_acumulado_pdv

    if ano is None or mes is None:
        ano, mes = periodo_ativo()
    resumo = linhas_acumulado([parceiro], ano, mes)
    linhas = resumo.get("linhas") or []
    if not linhas:
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: sem dados de acumulado."])
    mensagem = mensagem_acumulado_pdv(
        linhas[0], d0=resumo.get("d0"), d1=resumo.get("d1"), ano=ano, mes=mes
    )
    destinos = destinos_para_envio(user, "envio_resultados", parceiro)
    arquivo_bytes, nome_arquivo = planilha_acumulado(resumo)
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.ACUMULADO,
        mensagem=mensagem,
        caption=f"📊 *Acumulado {mes:02d}/{ano}* — {parceiro.nome}",
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_resultados",
    )


def enviar_acumulado_todos(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
    *,
    ano: int | None = None,
    mes: int | None = None,
) -> ResumoEnvio:
    total = ResumoEnvio()
    for p in parceiros:
        parte = enviar_acumulado_pdv(p, user, ano=ano, mes=mes)
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.append(f"— {p.nome}: {parte.enviados} ok / {parte.erros} erro")
    if not parceiros:
        total.ignorados += 1
        total.detalhes.append("Nenhum PDV no escopo.")
    return total


def enviar_ranking(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None = None,
    *,
    destinatario_id: int | None = None,
) -> ResumoEnvio:
    from ..ranking_imagem import imagem_ranking
    from ..pipelines.resultados import montar_ranking

    ranking = montar_ranking(parceiros)
    periodo = ranking.get("periodo") or {}
    fim = periodo.get("fim")
    periodo_txt = fim.strftime("%m/%Y") if fim else ""
    caption = f"🏆 *Ranking VB*{f' · {periodo_txt}' if periodo_txt else ''}"

    if user is not None and not eh_gestor(user):
        destinos = destinos_para_envio(user, "envio_resultados")
    elif destinatario_id:
        from django.db.models import Q

        dest = (
            Destinatario.objects.filter(
                pk=destinatario_id,
                ativo=True,
                tipo=Destinatario.TipoDestino.GRUPO,
                envio_resultados=True,
            )
            .filter(Q(ranking_consolidado=True) | Q(parceiro__in=parceiros))
            .select_related("parceiro")
            .first()
        )
        if not dest:
            return ResumoEnvio(
                erros=1,
                detalhes=["Grupo inválido ou sem flag Resultados no escopo."],
            )
        destinos = [
            DestinoEnvio(
                jid=dest.jid,
                nome=dest.nome,
                parceiro=dest.parceiro,
                destinatario=dest,
            )
        ]
    else:
        return ResumoEnvio(erros=1, detalhes=["Escolha o grupo WhatsApp para enviar o ranking."])

    arquivo_bytes, nome_arquivo = imagem_ranking(ranking)
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.RANKING,
        mensagem=caption,
        caption=caption,
        destinos=destinos,
        parceiro=None,
        user=user,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        flag="envio_resultados",
    )


def _destino_grupo(destinatario_id: int, parceiros: list[Parceiro] | None = None) -> list[DestinoEnvio]:
    from django.db.models import Q

    qs = Destinatario.objects.filter(
        pk=destinatario_id,
        ativo=True,
        tipo=Destinatario.TipoDestino.GRUPO,
        envio_resultados=True,
    )
    if parceiros is not None:
        qs = qs.filter(Q(ranking_consolidado=True) | Q(parceiro__in=parceiros))
    dest = qs.select_related("parceiro").first()
    if not dest:
        return []
    return [
        DestinoEnvio(
            jid=dest.jid,
            nome=dest.nome,
            parceiro=dest.parceiro,
            destinatario=dest,
        )
    ]


def _enviar_parcial_imagem(
    *,
    png: bytes,
    nome: str,
    caption: str,
    destinos: list[DestinoEnvio],
    parceiro: Parceiro | None,
    user: AbstractBaseUser | None,
) -> ResumoEnvio:
    return _enviar_com_anexo(
        tipo=EnvioWhatsApp.Tipo.PARCIAL,
        mensagem=caption,
        caption=caption,
        destinos=destinos,
        parceiro=parceiro,
        user=user,
        arquivo_bytes=png,
        nome_arquivo=nome,
        flag="envio_resultados",
    )


def _destino_especialista(especialista_id: int) -> list[DestinoEnvio]:
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=especialista_id).first()
    if not user:
        return []
    jid = whatsapp_do_usuario(user)
    if not jid:
        return []
    nome = (user.get_full_name() or user.username or "Especialista").strip()
    return [DestinoEnvio(jid=jid, nome=nome)]


def enviar_parcial_gerencia(
    dados: dict,
    user: AbstractBaseUser | None,
    *,
    destinatario_id: int | None = None,
    parceiros: list[Parceiro] | None = None,
) -> ResumoEnvio:
    from ..parcial_imagem import imagem_parcial_gerencia
    from ..pipelines.parcial_vendas import caption_imagem_parcial

    if not dados or not dados.get("linhas"):
        return ResumoEnvio(erros=1, detalhes=["Importe a base Excel antes de enviar."])
    if user is not None and not eh_gestor(user):
        return ResumoEnvio(erros=1, detalhes=["Somente gestores enviam a visão de gerência."])
    if not destinatario_id:
        return ResumoEnvio(erros=1, detalhes=["Escolha o grupo de gerência."])
    destinos = _destino_grupo(destinatario_id, parceiros)
    if not destinos:
        return ResumoEnvio(erros=1, detalhes=["Grupo inválido ou sem flag Resultados."])
    png, nome = imagem_parcial_gerencia(dados)
    caption = caption_imagem_parcial(dados, sufixo="Parceiros PP")
    return _enviar_parcial_imagem(
        png=png,
        nome=nome,
        caption=caption,
        destinos=destinos,
        parceiro=None,
        user=user,
    )


def enviar_parcial_especialista(
    dados: dict,
    user: AbstractBaseUser | None,
    *,
    especialista_id: int,
) -> ResumoEnvio:
    from ..parcial_imagem import imagem_parcial_especialista
    from ..pipelines.parcial_vendas import agrupar_por_especialista, caption_imagem_parcial

    if not dados or not dados.get("linhas"):
        return ResumoEnvio(erros=1, detalhes=["Importe a base Excel antes de enviar."])
    grupo = next(
        (g for g in agrupar_por_especialista(dados["linhas"]) if g.get("especialista_id") == especialista_id),
        None,
    )
    if not grupo:
        return ResumoEnvio(erros=1, detalhes=["Especialista sem PDVs na base importada."])
    if user is not None and not eh_gestor(user) and user.id != especialista_id:
        return ResumoEnvio(erros=1, detalhes=["Sem permissão para enviar a carteira deste especialista."])
    destinos = _destino_especialista(especialista_id)
    if not destinos:
        return ResumoEnvio(erros=1, detalhes=["WhatsApp do especialista não cadastrado."])
    png, nome = imagem_parcial_especialista(grupo, dados)
    caption = caption_imagem_parcial(dados, sufixo=grupo["especialista"])
    return _enviar_parcial_imagem(
        png=png,
        nome=nome,
        caption=caption,
        destinos=destinos,
        parceiro=None,
        user=user,
    )


def enviar_parcial_carteira(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None,
    dados: dict,
) -> ResumoEnvio:
    """Envia a carteira do usuário logado (especialista)."""
    if user is None:
        return ResumoEnvio(erros=1, detalhes=["Usuário inválido."])
    return enviar_parcial_especialista(
        dados,
        user,
        especialista_id=user.id,
    )


def enviar_parcial_grupos(
    parceiros: list[Parceiro],
    user: AbstractBaseUser | None,
    dados: dict,
) -> ResumoEnvio:
    """Envia imagem individual para o grupo de cada PDV no escopo."""
    from ..parcial_imagem import imagem_parcial_pdv
    from ..pipelines.parcial_vendas import caption_imagem_parcial, linha_pdv

    if not dados or not dados.get("linhas"):
        return ResumoEnvio(erros=1, detalhes=["Importe a base Excel antes de enviar."])
    total = ResumoEnvio()
    for parceiro in parceiros:
        linha = linha_pdv(dados, parceiro.pk)
        if not linha:
            total.ignorados += 1
            total.detalhes.append(f"— {parceiro.nome}: fora da base importada.")
            continue
        png, nome = imagem_parcial_pdv(linha, dados)
        caption = caption_imagem_parcial(dados, sufixo=parceiro.nome)
        parte = _enviar_parcial_imagem(
            png=png,
            nome=nome,
            caption=caption,
            destinos=destinos_para_envio(user, "envio_resultados", parceiro),
            parceiro=parceiro,
            user=user,
        )
        total.enviados += parte.enviados
        total.erros += parte.erros
        total.ignorados += parte.ignorados
        total.detalhes.append(f"— {parceiro.nome}: {parte.enviados} ok / {parte.erros} erro")
    if not parceiros:
        total.ignorados += 1
        total.detalhes.append("Nenhum PDV no escopo.")
    return total


def enviar_parcial_pdv(
    parceiro: Parceiro,
    user: AbstractBaseUser | None,
    dados: dict,
) -> ResumoEnvio:
    from ..parcial_imagem import imagem_parcial_pdv
    from ..pipelines.parcial_vendas import caption_imagem_parcial, linha_pdv

    linha = linha_pdv(dados, parceiro.pk)
    if not linha:
        return ResumoEnvio(ignorados=1, detalhes=[f"{parceiro.nome}: fora da base importada."])
    png, nome = imagem_parcial_pdv(linha, dados)
    caption = caption_imagem_parcial(dados, sufixo=parceiro.nome)
    return _enviar_parcial_imagem(
        png=png,
        nome=nome,
        caption=caption,
        destinos=destinos_para_envio(user, "envio_resultados", parceiro),
        parceiro=parceiro,
        user=user,
    )
