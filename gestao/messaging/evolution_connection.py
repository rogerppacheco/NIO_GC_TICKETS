"""Proxy Evolution API para status, QR Code e desconexão (painel Gestão)."""
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


class EvolutionConnectionService:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "EVOLUTION_API_URL", "") or "").rstrip("/")
        self.api_key = getattr(settings, "EVOLUTION_API_KEY", "") or ""
        self.instance_name = (
            getattr(settings, "EVOLUTION_INSTANCE_NAME", "") or DEFAULT_INSTANCE
        ).strip() or DEFAULT_INSTANCE

    def ensure_configured(self) -> None:
        if not self.base_url or not self.api_key:
            raise EvolutionConnectionError(
                "Evolution não configurada (EVOLUTION_API_URL / EVOLUTION_API_KEY)."
            )

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict[str, Any]:
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
            if resp.status_code not in (200, 201):
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
            return data if isinstance(data, dict) else {"data": data}
        except requests.exceptions.RequestException as exc:
            logger.error("Evolution %s %s falhou: %s", method, path, exc)
            raise EvolutionConnectionError(
                "Não foi possível comunicar com a Evolution API."
            ) from exc

    def get_status(self) -> dict[str, Any]:
        path = f"/instance/connectionState/{self.instance_name}"
        data = self._request("GET", path)
        inst = data.get("instance") if isinstance(data.get("instance"), dict) else data
        state = (
            inst.get("state")
            or data.get("state")
            or data.get("connectionStatus")
            or "unknown"
        )
        normalized = str(state).lower()
        return {
            "instanceName": self.instance_name,
            "state": normalized,
            "connected": normalized in {"open", "connected", "online"},
            "n8nConfigured": bool(
                (getattr(settings, "N8N_OUTBOUND_WEBHOOK_URL", "") or "").strip()
            ),
            "evolutionConfigured": True,
        }

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
        evolution_data = self._request("DELETE", path)
        status = self.get_status()
        return {
            "success": True,
            "instanceName": self.instance_name,
            "message": "Instância desconectada com sucesso.",
            "evolution": evolution_data,
            "status": status,
        }
