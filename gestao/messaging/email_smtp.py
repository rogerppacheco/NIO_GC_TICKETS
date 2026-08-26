from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Sequence

from django.conf import settings


def smtp_configurado() -> bool:
    return bool(
        (getattr(settings, "SMTP_HOST", "") or "").strip()
        and (getattr(settings, "SMTP_FROM", "") or "").strip()
    )


def enviar_email_com_anexos(
    destinos: Sequence[str],
    *,
    assunto: str,
    corpo_texto: str,
    anexos: Sequence[tuple[str, bytes, str]] | None = None,
) -> tuple[bool, str]:
    destinos = [d.strip() for d in destinos if d and "@" in d]
    if not destinos:
        return False, "Nenhum e-mail de destino."
    if not smtp_configurado():
        return False, "SMTP não configurado (SMTP_HOST / SMTP_FROM)."

    host = settings.SMTP_HOST
    port = int(getattr(settings, "SMTP_PORT", 587) or 587)
    user = (getattr(settings, "SMTP_USER", "") or "").strip()
    password = getattr(settings, "SMTP_PASS", "") or ""
    remetente = settings.SMTP_FROM
    usar_tls = bool(getattr(settings, "SMTP_USE_TLS", True))

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = ", ".join(destinos)
    msg.set_content(corpo_texto or "(sem corpo)")

    for nome, dados, mime in anexos or ():
        if not dados:
            continue
        principal, _, sub = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(
            dados,
            maintype=principal or "application",
            subtype=sub or "octet-stream",
            filename=nome,
        )

    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            if usar_tls:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except OSError as exc:
        return False, str(exc)
