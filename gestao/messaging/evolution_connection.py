"""Proxy Evolution API para status, QR Code, criação e desconexão."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_INSTANCE = "nio_gc_tickets"


class EvolutionConnectionError(Exception):
    """Falha ao comunicar com a Evolution API."""


def instancia_global() -> str:
    return (
        getattr(settings, "EVOLUTION_INSTANCE_NAME", "") or DEFAULT_INSTANCE
    ).strip() or DEFAULT_INSTANCE


class EvolutionConnectionService:
    def __init__(self, instance_name: str | None = None) -> None:
        self.base_url = (getattr(settings, "EVOLUTION_API_URL", "") or "").rstrip("/")
        self.api_key = getattr(settings, "EVOLUTION_API_KEY", "") or ""
        self.instance_name = (instance_name or "").strip() or instancia_global()

    def ensure_configured(self) -> None:
        if not self.base_url or not self.api_key:
            raise EvolutionConnectionError(
                "Evolution não configurada (EVOLUTION_API_URL / EVOLUTION_API_KEY)."
            )

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: int = 30,
        *,
        allow_statuses: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        self.ensure_configured()
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
            try:
                data = resp.json() if resp.content else {}
            except ValueError:
                data = {"raw": resp.text}
            if not isinstance(data, dict):
                data = {"data": data}
            data["_http_status"] = resp.status_code
            if resp.status_code not in allow_statuses:
                logger.error(
                    "Evolution %s %s HTTP %s: %s",
                    method,
                    path,
                    resp.status_code,
                    str(data)[:500],
                )
                raise EvolutionConnectionError(
                    "Não foi possível comunicar com a Evolution API."
                )
            return data
        except requests.exceptions.RequestException as exc:
            logger.error("Evolution %s %s falhou: %s", method, path, exc)
            raise EvolutionConnectionError(
                "Não foi possível comunicar com a Evolution API."
            ) from exc

    def get_status(self) -> dict[str, Any]:
        path = f"/instance/connectionState/{self.instance_name}"
        try:
            data = self._request("GET", path, allow_statuses=(200, 201, 404))
        except EvolutionConnectionError:
            return {
                "instanceName": self.instance_name,
                "state": "close",
                "connected": False,
                "n8nConfigured": bool(
                    (getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()
                ),
                "evolutionConfigured": True,
            }
        if data.get("_http_status") == 404:
            return {
                "instanceName": self.instance_name,
                "state": "close",
                "connected": False,
                "n8nConfigured": bool(
                    (getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()
                ),
                "evolutionConfigured": True,
            }
        inst = data.get("instance") if isinstance(data.get("instance"), dict) else data
        state = (
            inst.get("state")
            or data.get("state")
            or data.get("connectionStatus")
            or "unknown"
        )
        normalized = str(state).lower()
        owner = ""
        for chave in ("owner", "wuid", "wid", "number"):
            valor = inst.get(chave) or data.get(chave)
            if valor:
                owner = str(valor).split("@", 1)[0]
                break
        return {
            "instanceName": self.instance_name,
            "state": normalized,
            "connected": normalized in {"open", "connected", "online"},
            "owner": owner,
            "n8nConfigured": bool(
                (getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()
            ),
            "evolutionConfigured": True,
        }

    def create_instance(self) -> dict[str, Any]:
        payload = {
            "instanceName": self.instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
        }
        return self._request(
            "POST",
            "/instance/create",
            payload,
            allow_statuses=(200, 201, 403),
        )

    def ensure_exists(self) -> None:
        status = self.get_status()
        if status.get("connected") or status.get("state") in {
            "connecting",
            "open",
            "connected",
            "online",
        }:
            return
        try:
            self.create_instance()
        except EvolutionConnectionError:
            logger.exception("Falha ao criar instância Evolution %s", self.instance_name)

    @staticmethod
    def _extract_base64(payload: dict[str, Any]) -> str | None:
        qrcode = payload.get("qrcode")
        candidates = [
            qrcode.get("base64") if isinstance(qrcode, dict) else None,
            payload.get("base64"),
            payload.get("code"),
            (payload.get("pairing") or {}).get("base64")
            if isinstance(payload.get("pairing"), dict)
            else None,
        ]
        for value in candidates:
            if not isinstance(value, str) or not value:
                continue
            if value.startswith("data:image"):
                return value
            clean = value.replace("data:image/png;base64,", "")
            return f"data:image/png;base64,{clean}"
        return None

    def get_qrcode(self, max_attempts: int = 8, delay_seconds: float = 2.0) -> dict[str, Any]:
        self.ensure_exists()
        path = f"/instance/connect/{self.instance_name}"
        for attempt in range(1, max_attempts + 1):
            data = self._request("GET", path)
            base64 = self._extract_base64(data)
            if base64:
                return {
                    "instanceName": self.instance_name,
                    "base64": base64,
                    "count": data.get("count")
                    or (data.get("qrcode") or {}).get("count")
                    or 1,
                }
            if attempt < max_attempts:
                time.sleep(delay_seconds)
        raise EvolutionConnectionError(
            "QR Code ainda não disponível. Tente novamente em alguns segundos."
        )

    def disconnect(self) -> dict[str, Any]:
        path = f"/instance/logout/{self.instance_name}"
        evolution_data = self._request("DELETE", path, allow_statuses=(200, 201, 400, 404))
        status = self.get_status()
        return {
            "success": True,
            "instanceName": self.instance_name,
            "message": "Instância desconectada com sucesso.",
            "evolution": evolution_data,
            "status": status,
        }
