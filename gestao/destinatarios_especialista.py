from __future__ import annotations

import re

from django.db.models import Q

from tickets.acesso import eh_gestor, parceiros_para_destinatarios
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
    """Normaliza celular BR para dígitos com DDI 55.

    Aceita 10/11 dígitos (sem DDI), 12 (55+DDD+8, mobile antigo sem o 9)
    ou 13 (55+DDD+9xxxxxxxx).
    """
    digitos = re.sub(r"\D", "", whatsapp or "")
    if not digitos:
        return ""
    if len(digitos) in (10, 11):
        digitos = f"55{digitos}"
    # Mobile antigo: 55 + DDD(2) + 8 dígitos → inserir 9 após o DDD.
    if len(digitos) == 12 and digitos.startswith("55"):
        ddd, local = digitos[2:4], digitos[4:]
        if len(local) == 8 and not local.startswith("9"):
            digitos = f"55{ddd}9{local}"
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
                owner__isnull=True,
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
            Destinatario.objects.filter(parceiro=pdv, jid=jid, owner__isnull=True).first()
            or Destinatario.objects.filter(
                parceiro=pdv,
                owner__isnull=True,
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


def owner_da_lista(user):
    """None = lista da gestão. Caso contrário, a lista pessoal do usuário."""
    if user is None or eh_gestor(user):
        return None
    return user


def qs_destinatarios_da_lista(user):
    """Destinatários que a tela de Comunicação mostra para o usuário."""
    qs = Destinatario.objects.select_related(
        "parceiro",
        "parceiro__especialista",
        "parceiro__especialista__perfil_staff",
        "owner",
    )
    visiveis = parceiros_para_destinatarios(user)
    if eh_gestor(user):
        return qs.filter(owner__isnull=True).filter(
            Q(parceiro__in=visiveis) | Q(parceiro__isnull=True)
        )
    return qs.filter(owner=user, parceiro__in=visiveis)
