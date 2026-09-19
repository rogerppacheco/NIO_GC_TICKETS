from __future__ import annotations

import html
import re


def wpp_para_html(texto: str) -> str:
    """Converte formatação simples do WhatsApp (*negrito*) para HTML seguro."""
    escaped = html.escape(texto or "")
    escaped = re.sub(r"\*([^*]+)\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"~~([^~]+)~~", 
        r'<span style="background-color: #fee2e2; color: #b91c1c; text-decoration: line-through; padding: 0.1rem 0.3rem; border-radius: 4px; border: 1px solid #fca5a5;">\1</span>', 
        escaped
    )
    escaped = escaped.replace("\n", "<br>")
    return escaped
