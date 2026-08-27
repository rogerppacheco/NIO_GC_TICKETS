from __future__ import annotations

import re

from django.db.models import Q

from tickets.models import Parceiro, PerfilStaff

from .models import Destinatario

PREFIXO_NOME = "Especialista: "

FLAGS_RELATORIO = {
    "envio_osab": False,
    "envio_capilaridade": True,
    "envio_fpd": True,
    "envio_fpd_critico": False,
    "envio_churn": True,
    "envio_comissionamento": True,
    "envio_tarefas": True,
    "envio_venda_indevida": True,
    "envio_recompra": True,
    "envio_resultados": True,
}


def jid_individual(whatsapp: str) -> str:
    digitos = re.sub(r"\D", "", whatsapp or "")
    if not digitos:
        return ""
    if len(digitos) in (10, 11):
        digitos = f"55{digitos}"
    return digitos


def nome_destinatario_especialista(user) -> str:
    nome = (user.get_full_name() or "").strip() or user.first_name or user.username
    return f"{PREFIXO_NOME}{nome}"[:150]


def sincronizar_destinatarios_especialistas(parceiros=None) -> dict:
    """Cria/atualiza destinatário individual com o WhatsApp do especialista de cada PDV."""
    qs = parceiros if parceiros is not None else Parceiro.objects.filter(ativo=True)
    qs = qs.select_related("especialista", "especialista__perfil_staff")
    criados: list[str] = []
    atualizados: list[str] = []
    removidos: list[str] = []
    sem_whatsapp: list[str] = []
    sem_especialista: list[str] = []

    for pdv in qs:
        spec = pdv.especialista
        if not spec:
            sem_especialista.append(pdv.nome)
            continue
        perfil = getattr(spec, "perfil_staff", None)
        if perfil and perfil.papel == PerfilStaff.Papel.GESTOR:
            jid_gestor = jid_individual(getattr(perfil, "whatsapp", "") or "")
            filtro = Q(nome__startswith=PREFIXO_NOME)
            if jid_gestor:
                filtro |= Q(jid=jid_gestor)
            apagados, _ = Destinatario.objects.filter(
                parceiro=pdv,
                tipo=Destinatario.TipoDestino.INDIVIDUAL,
            ).filter(filtro).delete()
            if apagados:
                removidos.append(pdv.nome)
            continue
        jid = jid_individual(getattr(perfil, "whatsapp", "") or "")
        if not jid:
            sem_whatsapp.append(pdv.nome)
            continue
        nome = nome_destinatario_especialista(spec)
        existente = (
            Destinatario.objects.filter(parceiro=pdv, jid=jid).first()
            or Destinatario.objects.filter(
                parceiro=pdv,
                tipo=Destinatario.TipoDestino.INDIVIDUAL,
                nome__startswith=PREFIXO_NOME,
            ).first()
        )
        if existente:
            mudou = False
            if existente.jid != jid:
                existente.jid = jid
                mudou = True
            if existente.nome != nome:
                existente.nome = nome
                mudou = True
            if existente.tipo != Destinatario.TipoDestino.INDIVIDUAL:
                existente.tipo = Destinatario.TipoDestino.INDIVIDUAL
                mudou = True
            if not existente.ativo:
                existente.ativo = True
                mudou = True
            for campo, valor in FLAGS_RELATORIO.items():
                if getattr(existente, campo) != valor:
                    setattr(existente, campo, valor)
                    mudou = True
            if mudou:
                existente.save()
                atualizados.append(pdv.nome)
            continue
        Destinatario.objects.create(
            parceiro=pdv,
            nome=nome,
            jid=jid,
            tipo=Destinatario.TipoDestino.INDIVIDUAL,
            ativo=True,
            prioridade=50,
            **FLAGS_RELATORIO,
        )
        criados.append(pdv.nome)

    return {
        "criados": criados,
        "atualizados": atualizados,
        "sem_whatsapp": sem_whatsapp,
        "sem_especialista": sem_especialista,
        "removidos": removidos,
    }
