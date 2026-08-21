from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings


class SyncWAError(Exception):
    """Falha ao falar com a API SyncWA."""


@dataclass
class SyncWAResult:
    ok: bool
    message_log_id: str = ""
    status: str = ""
    error: str = ""
    destino: str = ""


def syncwa_configurado() -> bool:
    return bool(getattr(settings, "SYNCWA_BASE_URL", "").strip() and getattr(settings, "SYNCWA_API_KEY", "").strip())


def modo_teste_ativo() -> bool:
    return bool(getattr(settings, "SYNCWA_MODO_TESTE", False))


def jid_teste() -> str:
    return (getattr(settings, "SYNCWA_TEST_JID", "") or "").strip()


def normalizar_destino(valor: str) -> str:
    """Aceita JID completo (@g.us / @s.whatsapp.net) ou número BR com DDI.

    Números individuais vão como JID completo (@s.whatsapp.net) para o SyncWA
    não reescrever o nono dígito BR (ex.: 5531988… → 5531888…).
    """
    bruto = (valor or "").strip()
    if not bruto:
        raise SyncWAError("Destino vazio.")
    if "@" in bruto:
        return bruto
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        raise SyncWAError(f"Destino inválido: {valor!r}")
    if len(digitos) in (10, 11):
        digitos = f"55{digitos}"
    return f"{digitos}@s.whatsapp.net"


def destino_efetivo(jid: str) -> tuple[str, bool]:
    """Retorna (destino, foi_redirecionado_para_teste)."""
    destino = normalizar_destino(jid)
    if modo_teste_ativo():
        teste = jid_teste()
        if not teste:
            raise SyncWAError("SYNCWA_MODO_TESTE=True, mas SYNCWA_TEST_JID está vazio.")
        return normalizar_destino(teste), True
    return destino, False


def _headers() -> dict[str, str]:
    return {
        "x-api-key": settings.SYNCWA_API_KEY.strip(),
        "Accept": "application/json",
    }


def _base() -> str:
    return settings.SYNCWA_BASE_URL.rstrip("/")


def healthcheck(timeout: float = 5.0) -> dict:
    if not syncwa_configurado():
        return {"ok": False, "error": "SYNCWA_BASE_URL / SYNCWA_API_KEY não configurados."}
    try:
        r = requests.get(f"{_base()}/health", timeout=timeout)
        body = {}
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return {"ok": r.status_code < 500, "status_code": r.status_code, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def listar_grupos(timeout: float | None = None) -> dict:
    """GET /v1/groups — grupos da sessão SyncWA pareada."""
    if not syncwa_configurado():
        return {"ok": False, "error": "SyncWA não configurado.", "groups": []}
    timeout = timeout if timeout is not None else float(getattr(settings, "SYNCWA_TIMEOUT", 60))
    try:
        r = requests.get(f"{_base()}/v1/groups", headers=_headers(), timeout=timeout)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Falha de rede: {exc}", "groups": []}
    if r.status_code >= 400:
        try:
            detail = r.json()
            msg = detail.get("message") or detail.get("error") or detail
        except Exception:
            msg = r.text[:300]
        return {"ok": False, "error": f"HTTP {r.status_code}: {msg}", "groups": []}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "Resposta inválida do SyncWA.", "groups": []}
    groups = data.get("groups") or []
    return {"ok": True, "count": int(data.get("count") or len(groups)), "groups": groups}


def _chunk_texto(texto: str, limite: int = 4000) -> list[str]:
    texto = (texto or "").strip()
    if not texto:
        return []
    if len(texto) <= limite:
        return [texto]
    partes: list[str] = []
    atual = ""
    for bloco in texto.split("\n\n"):
        candidato = f"{atual}\n\n{bloco}".strip() if atual else bloco
        if len(candidato) <= limite:
            atual = candidato
            continue
        if atual:
            partes.append(atual)
        if len(bloco) <= limite:
            atual = bloco
        else:
            for i in range(0, len(bloco), limite):
                partes.append(bloco[i : i + limite])
            atual = ""
    if atual:
        partes.append(atual)
    return partes


def enviar_texto(to: str, text: str, timeout: float | None = None) -> SyncWAResult:
    if not syncwa_configurado():
        return SyncWAResult(ok=False, error="SyncWA não configurado (SYNCWA_BASE_URL / SYNCWA_API_KEY).")
    try:
        destino, _ = destino_efetivo(to)
    except SyncWAError as exc:
        return SyncWAResult(ok=False, error=str(exc), destino=to)

    timeout = timeout if timeout is not None else float(getattr(settings, "SYNCWA_TIMEOUT", 60))
    chunks = _chunk_texto(text)
    if not chunks:
        return SyncWAResult(ok=False, error="Mensagem vazia.", destino=destino)

    last = SyncWAResult(ok=False, destino=destino)
    for idx, chunk in enumerate(chunks):
        corpo = chunk if len(chunks) == 1 else f"({idx + 1}/{len(chunks)})\n{chunk}"
        try:
            r = requests.post(
                f"{_base()}/v1/messages/text",
                headers=_headers(),
                json={"to": destino, "text": corpo},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return SyncWAResult(ok=False, error=f"Falha de rede: {exc}", destino=destino)

        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:300]
            return SyncWAResult(
                ok=False,
                error=f"HTTP {r.status_code}: {detail}",
                destino=destino,
            )
        try:
            data = r.json()
        except Exception:
            data = {}
        last = SyncWAResult(
            ok=True,
            message_log_id=str(data.get("messageLogId") or ""),
            status=str(data.get("status") or "QUEUED"),
            destino=destino,
        )
    return last


def enviar_documento(
    to: str,
    *,
    conteudo: bytes,
    file_name: str,
    caption: str = "",
    mime_type: str | None = None,
    timeout: float | None = None,
) -> SyncWAResult:
    """Envia anexo via POST /v1/messages/media/upload (multipart)."""
    if not syncwa_configurado():
        return SyncWAResult(ok=False, error="SyncWA não configurado (SYNCWA_BASE_URL / SYNCWA_API_KEY).")
    if not conteudo:
        return SyncWAResult(ok=False, error="Arquivo vazio.")
    try:
        destino, _ = destino_efetivo(to)
    except SyncWAError as exc:
        return SyncWAResult(ok=False, error=str(exc), destino=to)

    timeout = timeout if timeout is not None else float(getattr(settings, "SYNCWA_TIMEOUT", 60))
    nome = Path(file_name or "anexo.xlsx").name
    mime = mime_type or mimetypes.guess_type(nome)[0] or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # SyncWA limita caption a 1024 chars
    caption_envio = (caption or "")[:1024]

    try:
        r = requests.post(
            f"{_base()}/v1/messages/media/upload",
            headers={"x-api-key": settings.SYNCWA_API_KEY.strip()},
            data={"to": destino, "caption": caption_envio, "fileName": nome},
            files={"file": (nome, conteudo, mime)},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return SyncWAResult(ok=False, error=f"Falha de rede: {exc}", destino=destino)

    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:300]
        return SyncWAResult(ok=False, error=f"HTTP {r.status_code}: {detail}", destino=destino)

    try:
        data = r.json()
    except Exception:
        data = {}
    return SyncWAResult(
        ok=True,
        message_log_id=str(data.get("messageLogId") or ""),
        status=str(data.get("status") or "QUEUED"),
        destino=destino,
    )
