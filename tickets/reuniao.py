"""Convite de reunião enviado ao WhatsApp do especialista logado."""
from __future__ import annotations

import re
from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone

from .models import ConviteReuniao

_DIAS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
_URL = URLValidator(schemes=["http", "https"])
_DOMINIO = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}([/:?#].*)?$", re.IGNORECASE)


def formatar_telefone(jid: str) -> str:
    digitos = re.sub(r"\D", "", jid or "")
    if len(digitos) == 13 and digitos.startswith("55"):
        return f"+{digitos[:2]} ({digitos[2:4]}) {digitos[4:9]}-{digitos[9:]}"
    if len(digitos) == 12 and digitos.startswith("55"):
        return f"+{digitos[:2]} ({digitos[2:4]}) {digitos[4:8]}-{digitos[8:]}"
    return digitos


def telefone_do_especialista(user) -> str:
    from gestao.destinatarios_especialista import jid_individual
    from gestao.messaging.envio import whatsapp_do_usuario

    return jid_individual(whatsapp_do_usuario(user))


def normalizar_link(valor: str) -> str:
    texto = (valor or "").strip()
    if texto and not re.match(r"^https?://", texto, re.IGNORECASE) and _DOMINIO.match(texto):
        texto = f"https://{texto}"
    return texto


def mensagem_convite(assunto: str, inicio: datetime, link: str) -> str:
    local = timezone.localtime(inicio)
    dia = _DIAS[local.weekday()]
    return (
        f"*Reunião: {assunto}*\n\n"
        f"📅 {dia}, {local.strftime('%d/%m/%Y')}\n"
        f"🕐 {local.strftime('%H:%M')}\n\n"
        f"{link}"
    )


def texto_erro_para_usuario(erro: str) -> str:
    texto = (erro or "").strip()
    baixo = texto.casefold()
    if (
        "conecte seu whatsapp" in baixo
        or "não está configurado" in baixo
        or "nao esta configurado" in baixo
        or "não cadastrado" in baixo
    ):
        return texto
    return "Não foi possível enviar agora. Tente de novo em instantes."


class ConviteReuniaoForm(forms.Form):
    assunto = forms.CharField(
        label="Assunto",
        max_length=160,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Alinhamento semanal com o PDV",
                "autocomplete": "off",
                "maxlength": "160",
            }
        ),
    )
    data = forms.DateField(
        label="Data",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    hora = forms.TimeField(
        label="Horário",
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        input_formats=["%H:%M", "%H:%M:%S"],
    )
    link = forms.CharField(
        label="Link da reunião",
        max_length=500,
        widget=forms.TextInput(
            attrs={
                "placeholder": "https://meet.google.com/...",
                "autocomplete": "off",
                "inputmode": "url",
                "spellcheck": "false",
            }
        ),
    )

    def clean_assunto(self) -> str:
        assunto = re.sub(r"\s+", " ", (self.cleaned_data.get("assunto") or "")).strip()
        if len(assunto) < 3:
            raise ValidationError("Informe um assunto com pelo menos 3 caracteres.")
        return assunto

    def clean_link(self) -> str:
        link = normalizar_link(self.cleaned_data.get("link") or "")
        try:
            _URL(link)
        except ValidationError as exc:
            raise ValidationError("Informe um link http ou https válido.") from exc
        return link

    def inicio(self) -> datetime:
        combinado = datetime.combine(self.cleaned_data["data"], self.cleaned_data["hora"])
        return timezone.make_aware(combinado, timezone.get_current_timezone())


def enviar_convite(*, user, assunto: str, inicio: datetime, link: str) -> ConviteReuniao:
    from gestao.messaging.instancia import instancia_para_envio
    from gestao.messaging.syncwa import SyncWAError, enviar_texto, syncwa_configurado

    jid = telefone_do_especialista(user)
    texto = mensagem_convite(assunto, inicio, link)
    convite = ConviteReuniao(
        especialista=user,
        assunto=assunto,
        inicio=inicio,
        link=link,
        destino_jid=jid,
        mensagem=texto,
        status=ConviteReuniao.Status.ERRO,
    )
    if not jid:
        convite.erro = "WhatsApp não cadastrado no perfil."
        convite.save()
        return convite
    if not syncwa_configurado():
        convite.erro = "O envio por WhatsApp não está configurado no sistema."
        convite.save()
        return convite
    try:
        instance = instancia_para_envio(user)
        resp = enviar_texto(jid, texto, instance=instance)
    except SyncWAError as exc:
        convite.erro = str(exc)[:500]
        convite.save()
        return convite
    if not resp.ok:
        convite.erro = (resp.error or "Falha ao enviar o WhatsApp.")[:500]
        convite.save()
        return convite
    convite.status = ConviteReuniao.Status.ENVIADO
    convite.syncwa_message_id = (resp.message_log_id or "")[:80]
    convite.save()
    return convite
