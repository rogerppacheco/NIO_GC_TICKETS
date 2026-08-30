from __future__ import annotations

import html
import re


def wpp_para_html(texto: str) -> str:
    """Converte formatação simples do WhatsApp (*negrito*) para HTML seguro."""
    escaped = html.escape(texto or "")
    escaped = re.sub(r"\*([^*]+)\*", r"<strong>\1</strong>", escaped)
    escaped = escaped.replace("\n", "<br>")
    return escaped
