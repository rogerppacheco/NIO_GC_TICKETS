from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings


class SyncWAError(Exception):
    """Falha ao falar com Evolution / n8n."""


@dataclass
class SyncWAResult:
    ok: bool
    message_log_id: str = ""
    status: str = ""
    error: str = ""
    destino: str = ""


def _timeout() -> float:
    return float(getattr(settings, "SYNCWA_TIMEOUT", 60))


def _evo_url() -> str:
    return (getattr(settings, "EVOLUTION_API_URL", "") or "").strip().rstrip("/")


def _evo_key() -> str:
    return (getattr(settings, "EVOLUTION_API_KEY", "") or "").strip()


def _evo_instance() -> str:
    name = (getattr(settings, "EVOLUTION_INSTANCE_NAME", "") or "").strip()
    return name or "nio_gc_tickets"


def _n8n_url() -> str:
    return (
        getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "")
        or getattr(settings, "N8N_WEBHOOK_URL", "")
        or ""
    ).strip()


def syncwa_configurado() -> bool:
    return bool(_evo_url() and _evo_key())


def modo_teste_ativo() -> bool:
    return bool(getattr(settings, "SYNCWA_MODO_TESTE", False))


def jid_teste() -> str:
    return (
        getattr(settings, "WHATSAPP_TEST_JID", "")
        or getattr(settings, "SYNCWA_TEST_JID", "")
        or ""
    ).strip()


def normalizar_destino(valor: str) -> str:
    """Aceita JID completo (@g.us / @s.whatsapp.net) ou número BR com DDI."""
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


def numero_para_evolution(destino: str) -> str:
    """Evolution: JID de grupo @g.us ou só dígitos do número."""
    s = (destino or "").strip()
    if "@g.us" in s or "@lid" in s:
        return s
    if "@s.whatsapp.net" in s or "@c.us" in s:
        return s.split("@", 1)[0]
    if s.endswith("-group"):
        return f"{s[: -len('-group')]}@g.us"
    return re.sub(r"\D", "", s)


def destino_efetivo(jid: str) -> tuple[str, bool]:
    """Retorna (destino, foi_redirecionado_para_teste)."""
    destino = normalizar_destino(jid)
    if modo_teste_ativo():
        teste = jid_teste()
        if not teste:
            raise SyncWAError("Modo teste ativo, mas WHATSAPP_TEST_JID / SYNCWA_TEST_JID está vazio.")
        return normalizar_destino(teste), True
    return destino, False


def _evo_headers() -> dict[str, str]:
    return {"apikey": _evo_key(), "Content-Type": "application/json"}


def _message_id(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    if data.get("messageId") or data.get("id"):
        return str(data.get("messageId") or data.get("id"))
    key = data.get("key")
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])
    inner = data.get("data")
    if isinstance(inner, dict):
        k = inner.get("key")
        if isinstance(k, dict) and k.get("id"):
            return str(k["id"])
        if inner.get("keyId") or inner.get("id"):
            return str(inner.get("keyId") or inner.get("id"))
    return ""


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


def healthcheck(timeout: float = 5.0) -> dict:
    if not syncwa_configurado():
        return {"ok": False, "error": "EVOLUTION_API_URL / EVOLUTION_API_KEY não configurados."}
    try:
        r = requests.get(
            f"{_evo_url()}/instance/connectionState/{_evo_instance()}",
            headers=_evo_headers(),
            timeout=timeout,
        )
        body: dict = {}
        try:
            body = r.json() if r.content else {}
        except Exception:
            body = {"raw": r.text[:200]}
        state = ""
        if isinstance(body, dict):
            inst = body.get("instance") if isinstance(body.get("instance"), dict) else body
            state = str(inst.get("state") or inst.get("status") or body.get("state") or "")
        ok = r.status_code < 500 and state.lower() in {"open", "connected", "online"}
        return {"ok": ok, "status_code": r.status_code, "state": state, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def listar_grupos(timeout: float | None = None) -> dict:
    """GET /group/fetchAllGroups — grupos da instância Evolution pareada."""
    if not syncwa_configurado():
        return {"ok": False, "error": "Evolution não configurada.", "groups": []}
    timeout = timeout if timeout is not None else _timeout()
    try:
        r = requests.get(
            f"{_evo_url()}/group/fetchAllGroups/{_evo_instance()}?getParticipants=true",
            headers=_evo_headers(),
            timeout=timeout,
        )
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
        return {"ok": False, "error": "Resposta inválida da Evolution.", "groups": []}

    raw: list = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        inner = data.get("groups") or data.get("response") or data.get("data") or []
        raw = list(inner.values()) if isinstance(inner, dict) else list(inner)

    groups: list[dict] = []
    seen: set[str] = set()
    for g in raw:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or g.get("jid") or g.get("groupId") or "").strip()
        if not gid:
            continue
        if "@g.us" not in gid:
            gid = f"{re.sub(r'\D', '', gid)}@g.us"
        if gid in seen:
            continue
        seen.add(gid)
        parts = g.get("participants") or g.get("size") or []
        size = len(parts) if isinstance(parts, list) else (int(parts) if str(parts).isdigit() else "")
        groups.append(
            {
                "jid": gid,
                "name": str(g.get("subject") or g.get("name") or "Sem nome"),
                "size": size,
            }
        )
    return {"ok": True, "count": len(groups), "groups": groups}


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> tuple[int, object]:
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    try:
        body = r.json() if r.content else {}
    except Exception:
        body = r.text[:400]
    return r.status_code, body


def _enviar_texto_n8n(number: str, text: str, destino: str, timeout: float) -> SyncWAResult | None:
    webhook = _n8n_url()
    if not webhook:
        return None
    try:
        status, body = _post_json(
            webhook,
            {
                "phone_number": number,
                "message_body": text,
                "source": "nio-gc-tickets",
            },
            {"Content-Type": "application/json", "Accept": "application/json"},
            timeout,
        )
    except requests.RequestException:
        return None
    if status not in (200, 201, 202, 204):
        return None
    mid = _message_id(body) if isinstance(body, dict) else ""
    return SyncWAResult(ok=True, message_log_id=mid, status="SENT", destino=destino)


def _enviar_texto_evolution(number: str, text: str, destino: str, timeout: float) -> SyncWAResult:
    try:
        status, body = _post_json(
            f"{_evo_url()}/message/sendText/{_evo_instance()}",
            {"number": number, "text": text},
            _evo_headers(),
            timeout,
        )
    except requests.RequestException as exc:
        return SyncWAResult(ok=False, error=f"Falha de rede: {exc}", destino=destino)
    if status >= 400:
        return SyncWAResult(ok=False, error=f"HTTP {status}: {body}", destino=destino)
    if isinstance(body, dict) and body.get("error"):
        return SyncWAResult(ok=False, error=str(body.get("error")), destino=destino)
    return SyncWAResult(
        ok=True,
        message_log_id=_message_id(body),
        status="SENT",
        destino=destino,
    )


def enviar_texto(to: str, text: str, timeout: float | None = None) -> SyncWAResult:
    if not syncwa_configurado():
        return SyncWAResult(ok=False, error="Evolution não configurada (EVOLUTION_API_URL / EVOLUTION_API_KEY).")
    try:
        destino, _ = destino_efetivo(to)
    except SyncWAError as exc:
        return SyncWAResult(ok=False, error=str(exc), destino=to)

    timeout = timeout if timeout is not None else _timeout()
    chunks = _chunk_texto(text)
    if not chunks:
        return SyncWAResult(ok=False, error="Mensagem vazia.", destino=destino)

    number = numero_para_evolution(destino)
    last = SyncWAResult(ok=False, destino=destino)
    for idx, chunk in enumerate(chunks):
        corpo = chunk if len(chunks) == 1 else f"({idx + 1}/{len(chunks)})\n{chunk}"
        via_n8n = _enviar_texto_n8n(number, corpo, destino, timeout)
        last = via_n8n if via_n8n and via_n8n.ok else _enviar_texto_evolution(number, corpo, destino, timeout)
        if not last.ok:
            return last
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
    if not syncwa_configurado():
        return SyncWAResult(ok=False, error="Evolution não configurada (EVOLUTION_API_URL / EVOLUTION_API_KEY).")
    if not conteudo:
        return SyncWAResult(ok=False, error="Arquivo vazio.")
    try:
        destino, _ = destino_efetivo(to)
    except SyncWAError as exc:
        return SyncWAResult(ok=False, error=str(exc), destino=to)

    timeout = timeout if timeout is not None else _timeout()
    nome = Path(file_name or "anexo.xlsx").name
    mime = mime_type or mimetypes.guess_type(nome)[0] or "application/octet-stream"
    b64 = base64.b64encode(conteudo).decode("ascii")
    media = f"data:{mime};base64,{b64}"
    number = numero_para_evolution(destino)
    mediatype = "image" if mime.startswith("image/") else "document"
    payload = {
        "number": number,
        "mediatype": mediatype,
        "mimetype": mime,
        "media": media,
        "fileName": nome,
        "caption": (caption or "")[:1024],
    }
    try:
        status, body = _post_json(
            f"{_evo_url()}/message/sendMedia/{_evo_instance()}",
            payload,
            _evo_headers(),
            max(timeout, 60.0),
        )
    except requests.RequestException as exc:
        return SyncWAResult(ok=False, error=f"Falha de rede: {exc}", destino=destino)
    if status >= 400:
        return SyncWAResult(ok=False, error=f"HTTP {status}: {body}", destino=destino)
    if isinstance(body, dict) and body.get("error"):
        return SyncWAResult(ok=False, error=str(body.get("error")), destino=destino)
    return SyncWAResult(ok=True, message_log_id=_message_id(body), status="SENT", destino=destino)
