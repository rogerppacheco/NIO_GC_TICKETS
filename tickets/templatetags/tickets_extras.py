from __future__ import annotations

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_URL_RE = re.compile(r"(https?://[^\s<]+)", re.IGNORECASE)


def _linkify(escaped: str) -> str:
    def repl(match: re.Match) -> str:
        url = match.group(1).rstrip(").,;]")
        label = url
        if len(label) > 72:
            label = label[:56] + "…" + label[-12:]
        return (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'class="break-link">{label}</a>'
        )

    return _URL_RE.sub(repl, escaped)


@register.filter
def texto_formatado(value) -> str:
    """Quebra linhas, encurta URLs longas e torna links clicáveis."""
    if value in (None, ""):
        return "—"
    text = _linkify(escape(str(value)))
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return mark_safe(text)


@register.filter
def form_field(form, name):
    try:
        return form[name]
    except Exception:
        return None
