#!/usr/bin/env python3
"""
Publica ou atualiza o fluxo outbound NIO GC Tickets no n8n (upsert + activate).

Variáveis:
  N8N_API_URL=https://n8n-production-65362.up.railway.app
  N8N_API_KEY=<api key do n8n>
  EVOLUTION_API_KEY=<apikey da Evolution — substitui o placeholder do JSON>

Uso:
    python ferramentas/n8n/deploy_nio_gc_tickets_outbound_flow.py
    python ferramentas/n8n/deploy_nio_gc_tickets_outbound_flow.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

FLOW_FILE = Path(__file__).resolve().parent / "nio-gc-tickets-n8n-outbound-flow.json"
FLOW_NAME = "NIO GC Tickets — WhatsApp (Outbound)"
WEBHOOK_PATH = "nio-gc-tickets-enviar-mensagem"
DEFAULT_N8N_BASE = "https://n8n-production-65362.up.railway.app"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _api_base(n8n_url: str) -> str:
    base = n8n_url.rstrip("/")
    if base.endswith("/api/v1"):
        return base
    return f"{base}/api/v1"


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "accept": "application/json",
        "X-N8N-API-KEY": api_key,
    }


def _request(
    method: str,
    api_base: str,
    api_key: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{api_base}{path}"
    resp = requests.request(
        method,
        url,
        headers=_headers(api_key),
        json=payload,
        timeout=60,
    )
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {"raw": resp.text}
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"{method} {path} HTTP {resp.status_code}: {str(data)[:800]}")
    return data if isinstance(data, dict) else {"data": data}


def load_flow(evolution_key: str) -> Dict[str, Any]:
    with FLOW_FILE.open(encoding="utf-8") as fh:
        raw = fh.read()
    if evolution_key:
        raw = raw.replace("__EVOLUTION_API_KEY__", evolution_key)
    return json.loads(raw)


def list_workflows(api_base: str, api_key: str) -> List[Dict[str, Any]]:
    data = _request("GET", api_base, api_key, "/workflows")
    items = data.get("data")
    return items if isinstance(items, list) else []


def upsert_workflow(
    api_base: str,
    api_key: str,
    flow: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = {
        "name": flow["name"],
        "nodes": flow["nodes"],
        "connections": flow["connections"],
        "settings": flow.get("settings") or {"executionOrder": "v1"},
        "staticData": flow.get("staticData"),
    }
    if existing and existing.get("id"):
        wf_id = str(existing["id"])
        print(f"Atualizando workflow existente: {wf_id}")
        return _request("PUT", api_base, api_key, f"/workflows/{wf_id}", payload)
    print("Criando workflow NIO GC Tickets outbound")
    return _request("POST", api_base, api_key, "/workflows", payload)


def activate_workflow(api_base: str, api_key: str, workflow_id: str) -> None:
    _request("POST", api_base, api_key, f"/workflows/{workflow_id}/activate")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy fluxo n8n outbound NIO GC Tickets")
    parser.add_argument("--dry-run", action="store_true", help="Só exibe URL esperada")
    args = parser.parse_args()

    n8n_url = _env("N8N_API_URL", DEFAULT_N8N_BASE)
    n8n_key = _env("N8N_API_KEY")
    evo_key = _env("EVOLUTION_API_KEY")
    webhook_base = _env("N8N_WEBHOOK_BASE_URL", n8n_url.replace("/api/v1", ""))
    expected_webhook = f"{webhook_base.rstrip('/')}/webhook/{WEBHOOK_PATH}"

    print("Fluxo:", FLOW_FILE.name)
    print("Webhook (N8N_OUTBOUND_WEBHOOK_URL):")
    print(f"  {expected_webhook}")
    print()
    print("Variáveis Railway nio-gc-tickets:")
    print(f"  N8N_OUTBOUND_WEBHOOK_URL={expected_webhook}")
    print("  EVOLUTION_API_URL=https://evolution-api-production-b36a.up.railway.app")
    print("  EVOLUTION_INSTANCE_NAME=nio_gc_tickets")
    print()

    if args.dry_run:
        return 0

    if not n8n_key:
        print("Defina N8N_API_KEY para publicar o fluxo.", file=sys.stderr)
        return 1
    if not evo_key:
        print("Defina EVOLUTION_API_KEY para preencher o apikey do fluxo.", file=sys.stderr)
        return 1

    api_base = _api_base(n8n_url)
    flow = load_flow(evo_key)
    existing = next((w for w in list_workflows(api_base, n8n_key) if w.get("name") == FLOW_NAME), None)
    saved = upsert_workflow(api_base, n8n_key, flow, existing)
    wf_id = str(saved.get("id") or (existing or {}).get("id") or "")
    if not wf_id:
        print("Workflow sem ID após upsert.", file=sys.stderr)
        return 1

    if not saved.get("active"):
        activate_workflow(api_base, n8n_key, wf_id)
        print(f"Workflow ativado: id={wf_id}")
    else:
        print(f"Workflow já ativo: id={wf_id}")

    print(f"\nConfigure no Railway: N8N_OUTBOUND_WEBHOOK_URL={expected_webhook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
