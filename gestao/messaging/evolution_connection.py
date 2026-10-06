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

    def _poll_qr(self, max_attempts: int, delay_seconds: float) -> dict[str, Any] | None:
        path = f"/instance/connect/{self.instance_name}"
        for attempt in range(1, max_attempts + 1):
            data = self._request("GET", path)
            base64 = self._extract_base64(data)
            if base64:
                return {
                    "instanceName": self.instance_name,
                    "connected": False,
                    "base64": base64,
                    "count": data.get("count")
                    or (data.get("qrcode") or {}).get("count")
                    or 1,
                }
            if attempt < max_attempts and delay_seconds:
                time.sleep(delay_seconds)
        return None

    def _reset_pairing(self) -> None:
        """Na Evolution 2.3 o logout em `connecting` responde 500 (Connection Closed)."""
        try:
            self._request(
                "POST",
                f"/instance/restart/{self.instance_name}",
                timeout=45,
                allow_statuses=(200, 201, 400, 404),
            )
            return
        except EvolutionConnectionError:
            logger.exception("Falha ao reiniciar pareamento %s", self.instance_name)
        try:
            self._request(
                "DELETE",
                f"/instance/logout/{self.instance_name}",
                allow_statuses=(200, 201, 400, 404, 500),
            )
        except EvolutionConnectionError:
            logger.exception("Falha ao encerrar pareamento %s", self.instance_name)
        try:
            self.create_instance()
        except EvolutionConnectionError:
            logger.exception("Falha ao recriar instância %s", self.instance_name)

    def get_qrcode(
        self,
        max_attempts: int = 8,
        delay_seconds: float = 2.0,
        *,
        restart_if_missing: bool = True,
    ) -> dict[str, Any]:
        status = self.get_status()
        if status.get("connected"):
            return {
                "instanceName": self.instance_name,
                "connected": True,
                "base64": "",
                "count": 0,
                "state": status.get("state") or "open",
            }

        self.ensure_exists()
        found = self._poll_qr(1, 0)
        if found:
            return found

        state = str(status.get("state") or "").lower()
        # connecting sem código: a sessão já gastou os QR e não emite outro.
        if restart_if_missing and state == "connecting":
            logger.warning(
                "Instância %s em connecting sem QR; reiniciando pareamento",
                self.instance_name,
            )
            self._reset_pairing()
            found = self._poll_qr(4, delay_seconds)
            if found:
                return found
            raise EvolutionConnectionError(
                "QR Code ainda não disponível. Tente novamente em alguns segundos."
            )

        found = self._poll_qr(max(max_attempts - 1, 0), delay_seconds)
        if found:
            return found
        if restart_if_missing:
            logger.warning(
                "QR ausente em %s (state=%s); reiniciando pareamento",
                self.instance_name,
                state or "close",
            )
            self._reset_pairing()
            found = self._poll_qr(4, delay_seconds)
            if found:
                return found
        raise EvolutionConnectionError(
            "QR Code ainda não disponível. Tente novamente em alguns segundos."
        )

    def _resposta_pareamento_reiniciado(self) -> dict[str, Any]:
        try:
            data = self._request(
                "POST",
                f"/instance/restart/{self.instance_name}",
                timeout=45,
                allow_statuses=(200, 201, 400),
            )
        except EvolutionConnectionError as exc:
            raise EvolutionConnectionError(
                "Não foi possível reiniciar o pareamento na Evolution."
            ) from exc
        base64 = self._extract_base64(data) or ""
        if data.get("_http_status") not in (200, 201) and not base64:
            raise EvolutionConnectionError(
                "Não foi possível reiniciar o pareamento na Evolution."
            )
        status = self.get_status()
        return {
            "success": True,
            "reset": True,
            "instanceName": self.instance_name,
            "message": "Pareamento reiniciado. Escaneie o QR novo.",
            "base64": base64,
            "count": data.get("count") or 1,
            "status": status,
        }

    def disconnect(self) -> dict[str, Any]:
        """Encerra a sessão ou reinicia o pareamento.

        Na Evolution 2.3, logout com a instância em `connecting` responde
        HTTP 500 e a mensagem Connection Closed — não existe sessão aberta
        para desligar, e o delete também aborta por causa disso. Nesse estado
        o restart gera um QR novo.
        """
        status = self.get_status()
        state = str(status.get("state") or "").lower()
        if state == "connecting" and not status.get("connected"):
            logger.warning(
                "Instância %s em connecting; reiniciando pareamento em vez de logout",
                self.instance_name,
            )
            return self._resposta_pareamento_reiniciado()

        evolution_data: dict[str, Any] = {}
        if status.get("connected"):
            try:
                evolution_data = self._request(
                    "DELETE",
                    f"/instance/logout/{self.instance_name}",
                    timeout=20,
                    allow_statuses=(200, 201, 400, 404, 500),
                )
            except EvolutionConnectionError as exc:
                raise EvolutionConnectionError(
                    "Não foi possível comunicar com a Evolution API."
                ) from exc
            status = self.get_status()
            if status.get("connected"):
                try:
                    evolution_data = self._request(
                        "DELETE",
                        f"/instance/delete/{self.instance_name}",
                        timeout=20,
                        allow_statuses=(200, 201, 404),
                    )
                except EvolutionConnectionError as exc:
                    raise EvolutionConnectionError(
                        "Não foi possível desconectar esta sessão na Evolution."
                    ) from exc
                status = self.get_status()
            if status.get("connected"):
                raise EvolutionConnectionError(
                    "A Evolution manteve a sessão conectada. Tente desconectar de novo."
                )

        return {
            "success": True,
            "instanceName": self.instance_name,
            "message": "Instância desconectada com sucesso.",
            "evolution": {
                "http": evolution_data.get("_http_status"),
            },
            "status": status,
        }
