"""Instância Evolution por usuário: equipe envia pelo próprio chip."""
from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from tickets.acesso import eh_gestor

from ..models import GestaoConfig, InstanciaWhatsApp
from .evolution_connection import EvolutionConnectionService, instancia_global
from .syncwa import SyncWAError

MSG_SEM_INSTANCIA = (
    "Conecte seu WhatsApp em Comunicação → WhatsApp (QR no celular) "
    "antes de enviar. Os envios da sua carteira saem do seu número, "
    "não do chip da gestão."
)

CHAVE_MODO_ENVIO = "WHATSAPP_MODO_ENVIO"
MODO_ENVIO_CENTRAL = "central"
MODO_ENVIO_PESSOAL = "pessoal"


def modo_envio_whatsapp() -> str:
    """central (padrão, chip nio_gc_tickets) ou pessoal (chip de cada um)."""
    row = GestaoConfig.objects.filter(chave=CHAVE_MODO_ENVIO).first()
    valor = (row.valor if row else "").strip().lower()
    if valor in {MODO_ENVIO_PESSOAL, "por_usuario", "especialista"}:
        return MODO_ENVIO_PESSOAL
    return MODO_ENVIO_CENTRAL


def envio_usa_chip_central() -> bool:
    return modo_envio_whatsapp() == MODO_ENVIO_CENTRAL


def salvar_modo_envio(valor: str) -> str:
    modo = (
        MODO_ENVIO_PESSOAL
        if (valor or "").strip().lower() in {MODO_ENVIO_PESSOAL, "por_usuario", "especialista"}
        else MODO_ENVIO_CENTRAL
    )
    GestaoConfig.objects.update_or_create(
        chave=CHAVE_MODO_ENVIO, defaults={"valor": modo}
    )
    return modo


def nome_instancia_usuario(user) -> str:
    return f"nio_u{user.pk}"


def garantir_registro(user) -> InstanciaWhatsApp:
    inst, _ = InstanciaWhatsApp.objects.get_or_create(
        user=user,
        defaults={"nome": nome_instancia_usuario(user)},
    )
    return inst


def servico_painel(user) -> EvolutionConnectionService:
    if eh_gestor(user):
        return EvolutionConnectionService()
    inst = garantir_registro(user)
    return EvolutionConnectionService(instance_name=inst.nome)


def gravar_status(user, status: dict) -> None:
    if eh_gestor(user):
        return
    inst = garantir_registro(user)
    inst.estado = (status.get("state") or "")[:40]
    inst.numero = (status.get("owner") or inst.numero or "")[:40]
    inst.save(update_fields=["estado", "numero", "atualizado_em"])


def instancia_para_envio(user) -> str:
    """Nome da instância Evolution que dispara o envio.

    Padrão: chip da gestão (nio_gc_tickets). No modo pessoal, a equipe
    só envia se o próprio WhatsApp estiver conectado — sem fallback silencioso.
    """
    if user is None or eh_gestor(user) or envio_usa_chip_central():
        return instancia_global()
    try:
        inst = user.instancia_whatsapp
    except (ObjectDoesNotExist, AttributeError):
        raise SyncWAError(MSG_SEM_INSTANCIA)
    svc = EvolutionConnectionService(instance_name=inst.nome)
    status = svc.get_status()
    gravar_status(user, status)
    if not status.get("connected"):
        raise SyncWAError(MSG_SEM_INSTANCIA)
    return inst.nome
