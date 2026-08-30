# -*- coding: utf-8 -*-
"""
Consulta ao vivo de fachadas no Power BI público (multi-região).

Regiões: DFV_SUDESTE (MG/ES/RJ), DFV_SP e DFV_SUL (PR/SC/RS).

Comandos WhatsApp:
- DFV: filtro por CEP (consulta as 3 bases em paralelo)
- CDOE: filtro por CODIGO_CDO (roteia pela UF → região)

Independente da base local `crm_app.models.DFV` (legado; comando Fachada desativado).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ENTITY = "BASE_HP_F"

# Colunas mínimas para montar a resposta do WhatsApp
SELECT_COLS: list[str] = [
    "CEP",
    "NO_FACHADA",
    "COMPLEMENTO1",
    "COMPLEMENTO2",
    "COMPLEMENTO3",
    "LOGRADOURO",
    "BAIRRO",
    "MUNICIPIO",
    "UF",
    "VIABILIDADE_ATUAL",
    "CODIGO_CDO",
]

CACHE_KEY_PREFIX = "dfv_pbi:cep:"
CACHE_KEY_PREFIX_CDO = "dfv_pbi:cdo:"
_local_cache_lock = threading.Lock()
_local_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass(frozen=True)
class DfvRegionConfig:
    """Configuração de um relatório Power BI regional (DFV)."""

    code: str
    label: str
    resource_key: str
    model_id: int
    ufs: tuple[str, ...]


# Defaults alinhados aos links públicos Nio (tenant comum)
_DEFAULT_REGION_SUDESTE = DfvRegionConfig(
    code="SUDESTE",
    label="Sudeste",
    resource_key="8a9db8f9-7cf1-4db5-90d2-5259ad149eba",
    model_id=6061538,
    ufs=("MG", "ES", "RJ"),
)
_DEFAULT_REGION_SP = DfvRegionConfig(
    code="SP",
    label="SP",
    resource_key="81e95c1a-e770-44e3-9646-19df8443756c",
    model_id=7340452,
    ufs=("SP",),
)
_DEFAULT_REGION_SUL = DfvRegionConfig(
    code="SUL",
    label="Sul",
    resource_key="cc212c25-1b6a-4301-877b-703e2c7aa788",
    model_id=6062850,
    ufs=("PR", "SC", "RS"),
)


class DfvPowerBiError(Exception):
    """Erro na consulta ao Power BI (rede, parse, API)."""


class DfvPowerBiTimeout(DfvPowerBiError):
    """Timeout ao consultar o Power BI."""


class DfvPowerBiDisabled(DfvPowerBiError):
    """Feature flag DFV_POWERBI_ENABLED desligada."""


def limpar_cep(cep: str) -> str:
    """Mantém só dígitos e normaliza para 8 posições (zero à esquerda)."""
    digitos = re.sub(r"\D", "", str(cep or ""))
    if not digitos:
        return ""
    if len(digitos) > 8:
        digitos = digitos[-8:]
    return digitos.zfill(8)


def limpar_codigo_cdo(codigo: str) -> str:
    """
    Normaliza o código CDO informado pelo vendedor.

    Remove espaços extras e mantém letras/números/hífen em maiúsculas.
    """
    texto = str(codigo or "").strip().upper()
    texto = re.sub(r"\s+", "", texto)
    # Remove aspas e caracteres de formatação comuns no WhatsApp
    texto = texto.strip("*_`'\"")
    return texto


def variantes_codigo_cdo(codigo: str) -> list[str]:
    """
    Gera candidatas de CODIGO_CDO para consulta no Power BI.

    No DFV o valor costuma ser CDOE-28005; o vendedor muitas vezes digita só 28005.
    """
    bruto = limpar_codigo_cdo(codigo)
    if not bruto:
        return []

    digitos = re.sub(r"\D", "", bruto)
    ordered: list[str] = []

    def _add(valor: str) -> None:
        v = limpar_codigo_cdo(valor)
        if v and v not in ordered:
            ordered.append(v)

    _add(bruto)
    if digitos:
        # Formato observado no Power BI (prioridade)
        _add(f"CDOE-{digitos}")
        _add(f"CDO-{digitos}")
        _add(f"CDOE{digitos}")
        _add(f"CDO{digitos}")
        _add(digitos)

    # Se veio com CDO- mas a base usa CDOE-
    if bruto.startswith("CDO-") and not bruto.startswith("CDOE-"):
        _add("CDOE-" + bruto[4:])
    if bruto.startswith("CDOE-"):
        _add("CDO-" + bruto[5:])

    return ordered


# Ordem exibida no WhatsApp (Sudeste → SP → Sul)
CDOE_UFS: tuple[str, ...] = ("MG", "ES", "RJ", "SP", "PR", "SC", "RS")

COBERTURA_DFV_TXT = "MG/ES/RJ, SP e Sul (PR/SC/RS)"


def limpar_uf(uf: str) -> str:
    """Normaliza UF coberta pelo DFV multi-região. Aceita texto ou id cdoe_uf_XX."""
    texto = str(uf or "").strip().upper()
    texto = texto.replace("CDOE_UF_", "").replace("UF_", "")
    texto = re.sub(r"[^A-Z]", "", texto)
    if len(texto) >= 2:
        texto = texto[:2]
    return texto if texto in CDOE_UFS else ""


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


def _feature_enabled() -> bool:
    return bool(_cfg("DFV_POWERBI_ENABLED", True))


def listar_regioes_dfv() -> list[DfvRegionConfig]:
    """
    Retorna regiões DFV habilitadas (com resource_key e model_id válidos).

    Mantém compatibilidade com DFV_POWERBI_RESOURCE_KEY / MODEL_ID (Sudeste)
    e aceita overrides DFV_POWERBI_SP_* / DFV_POWERBI_SUL_*.
    """
    sudeste_key = str(
        _cfg("DFV_POWERBI_RESOURCE_KEY", _DEFAULT_REGION_SUDESTE.resource_key) or ""
    ).strip()
    sudeste_model = int(
        _cfg("DFV_POWERBI_MODEL_ID", _DEFAULT_REGION_SUDESTE.model_id) or 0
    )
    sp_key = str(
        _cfg("DFV_POWERBI_SP_RESOURCE_KEY", _DEFAULT_REGION_SP.resource_key) or ""
    ).strip()
    sp_model = int(_cfg("DFV_POWERBI_SP_MODEL_ID", _DEFAULT_REGION_SP.model_id) or 0)
    sul_key = str(
        _cfg("DFV_POWERBI_SUL_RESOURCE_KEY", _DEFAULT_REGION_SUL.resource_key) or ""
    ).strip()
    sul_model = int(_cfg("DFV_POWERBI_SUL_MODEL_ID", _DEFAULT_REGION_SUL.model_id) or 0)

    candidatas = [
        DfvRegionConfig(
            code="SUDESTE",
            label="Sudeste",
            resource_key=sudeste_key,
            model_id=sudeste_model,
            ufs=_DEFAULT_REGION_SUDESTE.ufs,
        ),
        DfvRegionConfig(
            code="SP",
            label="SP",
            resource_key=sp_key,
            model_id=sp_model,
            ufs=_DEFAULT_REGION_SP.ufs,
        ),
        DfvRegionConfig(
            code="SUL",
            label="Sul",
            resource_key=sul_key,
            model_id=sul_model,
            ufs=_DEFAULT_REGION_SUL.ufs,
        ),
    ]
    return [r for r in candidatas if r.resource_key and r.model_id > 0]


def regiao_por_uf(uf: str) -> Optional[DfvRegionConfig]:
    """Localiza a região DFV que cobre a UF informada."""
    uf_limpo = limpar_uf(uf)
    if not uf_limpo:
        return None
    for regiao in listar_regioes_dfv():
        if uf_limpo in regiao.ufs:
            return regiao
    return None


def _sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _eh_viavel(status: Optional[str]) -> bool:
    s = _sem_acentos(status or "").upper().strip()
    # "INVIAVEL" contém "VIAVEL" — excluir primeiro
    if "INVIAVEL" in s:
        return False
    return "VIAVEL" in s


def _montar_complemento(row: dict[str, Any]) -> str:
    partes = []
    for key in ("COMPLEMENTO1", "COMPLEMENTO2", "COMPLEMENTO3"):
        val = row.get(key)
        if val is None:
            continue
        texto = str(val).strip()
        if texto and texto.lower() not in ("none", "null", "nan"):
            partes.append(texto)
    return " | ".join(partes)


def _headers(resource_key: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": "https://app.powerbi.com/",
        "Content-Type": "application/json;charset=UTF-8",
    }


def _null_mask(item: dict[str, Any]) -> int:
    if "\u00d8" in item:
        return int(item["\u00d8"])
    if "Ø" in item:
        return int(item["Ø"])
    return 0


def parse_dsr_rows(
    data_obj: dict[str, Any],
    n_cols: int,
) -> tuple[list[list[Any]], bool, Optional[list[Any]]]:
    """
    Parse DSR com ValueDicts, bitmask R (repeat) e Ø (null).

    Returns:
        (rows, incomplete, restart_tokens)
    """
    try:
        result = data_obj["results"][0]["result"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DfvPowerBiError(f"Resposta Power BI sem results: {exc}") from exc

    if "data" not in result:
        # Sem dados / CEP inexistente — tratar como lista vazia
        err = result.get("error") or result.get("errorCode")
        if err:
            raise DfvPowerBiError(f"Erro no Power BI: {err}")
        return [], False, None

    try:
        ds = result["data"]["dsr"]["DS"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise DfvPowerBiError(f"DSR inválido: {exc}") from exc

    value_dicts = ds.get("ValueDicts", {}) or {}
    dm0 = ds.get("PH", [{}])[0].get("DM0", []) or []
    if not dm0:
        return [], False, None

    col_dn: dict[int, str] = {}
    rows: list[list[Any]] = []
    prev: list[Any] = [None] * n_cols

    for item in dm0:
        if "S" in item:
            col_dn = {}
            for sdef in item["S"]:
                name = sdef.get("N", "")
                dn = sdef.get("DN")
                if name.startswith("G") and dn:
                    col_dn[int(name[1:])] = dn

        c_vals = list(item.get("C", []) or [])
        r_mask = int(item.get("R", 0) or 0)
        n_mask = _null_mask(item)
        row: list[Any] = [None] * n_cols
        ci = 0
        for col in range(n_cols):
            if n_mask & (1 << col):
                row[col] = None
                continue
            if r_mask & (1 << col):
                row[col] = prev[col]
                continue
            if ci >= len(c_vals):
                row[col] = None
                continue
            raw = c_vals[ci]
            ci += 1
            dn = col_dn.get(col)
            if dn and dn in value_dicts and isinstance(raw, int):
                vd = value_dicts[dn]
                if 0 <= raw < len(vd):
                    row[col] = vd[raw]
                else:
                    row[col] = raw
            else:
                row[col] = raw
        prev = row
        rows.append(row)

    incomplete = not bool(ds.get("IC", True))
    rt = ds.get("RT")
    return rows, incomplete, rt


def _build_cmd(
    filters: list[tuple[str, str]],
    restart_tokens: Optional[list[Any]] = None,
) -> dict[str, Any]:
    window_count = int(_cfg("DFV_POWERBI_WINDOW_COUNT", 5000) or 5000)
    select = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "b"}},
                "Property": col,
            },
            "Name": f"{ENTITY}.{col}",
        }
        for col in SELECT_COLS
    ]
    window_obj: dict[str, Any] = {"Count": window_count}
    if restart_tokens is not None:
        window_obj["RestartTokens"] = restart_tokens

    where_clauses: list[dict[str, Any]] = []
    for filter_property, filter_value in filters:
        literal = str(filter_value).replace("'", "''")
        where_clauses.append(
            {
                "Condition": {
                    "Comparison": {
                        "ComparisonKind": 0,
                        "Left": {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": "b"}},
                                "Property": filter_property,
                            }
                        },
                        "Right": {"Literal": {"Value": f"'{literal}'"}},
                    }
                }
            }
        )

    return {
        "SemanticQueryDataShapeCommand": {
            "Query": {
                "Version": 2,
                "From": [{"Name": "b", "Entity": ENTITY, "Type": 0}],
                "Select": select,
                "Where": where_clauses,
            },
            "Binding": {
                "Primary": {"Groupings": [{"Projections": list(range(len(SELECT_COLS)))}]},
                "DataReduction": {
                    "DataVolume": 4,
                    "Primary": {"Window": window_obj},
                },
                "Version": 1,
            },
        }
    }


def _query_page(cmd: dict[str, Any], region: DfvRegionConfig) -> dict[str, Any]:
    cluster = str(_cfg("DFV_POWERBI_CLUSTER", "") or "").rstrip("/")
    timeout = float(_cfg("DFV_POWERBI_TIMEOUT_SECONDS", 18) or 18)
    if not cluster or not region.model_id:
        raise DfvPowerBiError("Configuração Power BI incompleta (cluster/model id).")

    payload = {
        "version": "1.0.0",
        "queries": [{"Query": {"Commands": [cmd]}}],
        "cancelQueries": [],
        "modelId": region.model_id,
    }
    url = f"{cluster}/public/reports/querydata?synchronous=true"
    try:
        response = requests.post(
            url,
            headers=_headers(region.resource_key),
            data=json.dumps(payload),
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise DfvPowerBiTimeout("Timeout ao consultar o Power BI.") from exc
    except requests.RequestException as exc:
        raise DfvPowerBiError(f"Falha de rede no Power BI: {exc}") from exc

    if response.status_code >= 400:
        raise DfvPowerBiError(
            f"Power BI HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DfvPowerBiError("Resposta Power BI não é JSON válido.") from exc


def _rows_to_dicts(rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {
            SELECT_COLS[i]: (row[i] if i < len(row) else None)
            for i in range(len(SELECT_COLS))
        }
        # Normaliza CEP vindo como número (ex.: 3013000 -> 03013000)
        cep_raw = item.get("CEP")
        if cep_raw is not None:
            item["CEP"] = limpar_cep(str(cep_raw))
        out.append(item)
    return out


def _cache_get(key: str) -> Optional[list[dict[str, Any]]]:
    ttl = int(_cfg("DFV_POWERBI_CACHE_TTL_SECONDS", 600) or 0)
    if ttl <= 0:
        return None
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        logger.debug("[DFV-PBI] cache Django indisponível; usando memória local", exc_info=True)

    now = time.time()
    with _local_cache_lock:
        entry = _local_cache.get(key)
        if not entry:
            return None
        expires_at, data = entry
        if expires_at < now:
            _local_cache.pop(key, None)
            return None
        return data


def _cache_set(key: str, data: list[dict[str, Any]]) -> None:
    ttl = int(_cfg("DFV_POWERBI_CACHE_TTL_SECONDS", 600) or 0)
    if ttl <= 0:
        return
    try:
        cache.set(key, data, timeout=ttl)
        return
    except Exception:
        logger.debug("[DFV-PBI] falha ao gravar cache Django", exc_info=True)

    with _local_cache_lock:
        _local_cache[key] = (time.time() + ttl, data)
        # Evita crescimento indefinido em memória
        if len(_local_cache) > 500:
            oldest = sorted(_local_cache.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                _local_cache.pop(k, None)


def _consultar_por_filtro(
    filters: list[tuple[str, str]],
    cache_key: str,
    log_label: str,
    region: DfvRegionConfig,
) -> list[dict[str, Any]]:
    """Consulta paginada genérica no Power BI com cache (uma região)."""
    if not _feature_enabled():
        raise DfvPowerBiDisabled("Consulta DFV Power BI desabilitada.")

    if not region.resource_key:
        raise DfvPowerBiError(
            f"Resource key não configurada para região {region.code}."
        )

    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("[DFV-PBI] cache hit %s (%s registros)", log_label, len(cached))
        return cached

    started = time.monotonic()
    all_rows: list[dict[str, Any]] = []
    restart: Optional[list[Any]] = None
    page = 0
    max_pages = int(_cfg("DFV_POWERBI_MAX_PAGES", 20) or 20)

    try:
        while page < max_pages:
            page += 1
            data = _query_page(
                _build_cmd(filters, restart_tokens=restart),
                region=region,
            )
            rows, incomplete, rt = parse_dsr_rows(data, len(SELECT_COLS))
            dicts = _rows_to_dicts(rows)
            for item in dicts:
                item["_fonte_regiao"] = region.code
                item["_fonte_label"] = region.label
            all_rows.extend(dicts)
            logger.info(
                "[DFV-PBI] %s page=%s +%s total=%s incomplete=%s",
                log_label,
                page,
                len(rows),
                len(all_rows),
                incomplete,
            )
            if not incomplete or not rt or not rows:
                break
            restart = rt
    except DfvPowerBiError:
        raise
    except Exception as exc:
        logger.exception("[DFV-PBI] erro inesperado %s", log_label)
        raise DfvPowerBiError(str(exc)) from exc

    elapsed = time.monotonic() - started
    logger.info(
        "[DFV-PBI] %s concluído: %s registros em %.1fs",
        log_label,
        len(all_rows),
        elapsed,
    )
    _cache_set(cache_key, all_rows)
    return all_rows


def _consultar_em_regioes(
    filters: list[tuple[str, str]],
    cache_key_base: str,
    log_label: str,
    regions: Optional[list[DfvRegionConfig]] = None,
) -> list[dict[str, Any]]:
    """
    Consulta uma ou mais regiões em paralelo e une os resultados.

    Se todas as regiões falharem, propaga o primeiro erro.
    Sucesso parcial (alguma região OK) devolve o que for encontrado.
    """
    if not _feature_enabled():
        raise DfvPowerBiDisabled("Consulta DFV Power BI desabilitada.")

    alvos = list(regions) if regions is not None else listar_regioes_dfv()
    if not alvos:
        raise DfvPowerBiError("Nenhuma região DFV Power BI configurada.")

    if len(alvos) == 1:
        regiao = alvos[0]
        return _consultar_por_filtro(
            filters=filters,
            cache_key=f"{cache_key_base}:reg:{regiao.code.lower()}",
            log_label=f"{log_label}|{regiao.code}",
            region=regiao,
        )

    resultados: list[list[dict[str, Any]]] = []
    erros: list[Exception] = []

    def _job(regiao: DfvRegionConfig) -> list[dict[str, Any]]:
        return _consultar_por_filtro(
            filters=filters,
            cache_key=f"{cache_key_base}:reg:{regiao.code.lower()}",
            log_label=f"{log_label}|{regiao.code}",
            region=regiao,
        )

    max_workers = min(len(alvos), 3)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = {executor.submit(_job, r): r for r in alvos}
        for futuro in as_completed(futuros):
            regiao = futuros[futuro]
            try:
                resultados.append(futuro.result())
            except Exception as exc:
                logger.warning(
                    "[DFV-PBI] falha região %s em %s: %s",
                    regiao.code,
                    log_label,
                    exc,
                )
                erros.append(exc)

    if resultados:
        merged: list[dict[str, Any]] = []
        for bloco in resultados:
            merged.extend(bloco)
        return merged

    if erros:
        raise erros[0]
    return []


def consultar_fachadas_por_cep(cep: str) -> list[dict[str, Any]]:
    """
    Consulta fachadas do CEP nas bases DFV (Sudeste, SP e Sul) em paralelo.

    Returns:
        Lista de dicts com as colunas de SELECT_COLS (+ metadados de região).

    Raises:
        DfvPowerBiDisabled: feature flag desligada
        DfvPowerBiTimeout: timeout HTTP em todas as regiões
        DfvPowerBiError: demais falhas (sem fallback para base local)
    """
    cep_limpo = limpar_cep(cep)
    if len(cep_limpo) != 8:
        raise DfvPowerBiError("CEP inválido.")

    return _consultar_em_regioes(
        filters=[("CEP", cep_limpo)],
        cache_key_base=f"{CACHE_KEY_PREFIX}{cep_limpo}",
        log_label=f"CEP={cep_limpo}",
    )


def filtrar_registros_por_uf(
    registros: list[dict[str, Any]], uf: str
) -> list[dict[str, Any]]:
    uf_limpo = limpar_uf(uf)
    if not uf_limpo:
        return list(registros)
    return [
        r
        for r in registros
        if str(r.get("UF") or "").strip().upper() == uf_limpo
    ]


def consultar_fachadas_por_cdo(
    codigo_cdo: str,
    uf: Optional[str] = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Consulta fachadas pelo CODIGO_CDO no Power BI (comando CDOE).

    Com UF, consulta só a região correspondente. Sem UF, consulta todas.
    Tenta variantes (ex.: 28005 → CDOE-28005).

    Returns:
        (registros, codigo_encontrado)
    """
    variantes = variantes_codigo_cdo(codigo_cdo)
    if not variantes:
        raise DfvPowerBiError("Código CDO inválido.")

    uf_limpo = limpar_uf(uf) if uf else ""
    regions: Optional[list[DfvRegionConfig]] = None
    if uf_limpo:
        regiao = regiao_por_uf(uf_limpo)
        if regiao is None:
            raise DfvPowerBiError(f"UF {uf_limpo} sem região DFV configurada.")
        regions = [regiao]

    last_error: Optional[Exception] = None

    for variante in variantes:
        filters: list[tuple[str, str]] = [("CODIGO_CDO", variante)]
        cache_key = f"{CACHE_KEY_PREFIX_CDO}{variante}"
        log_label = f"CODIGO_CDO={variante}"
        if uf_limpo:
            filters.append(("UF", uf_limpo))
            cache_key = f"{cache_key}:uf:{uf_limpo}"
            log_label = f"{log_label}|UF={uf_limpo}"

        try:
            regs = _consultar_em_regioes(
                filters=filters,
                cache_key_base=cache_key,
                log_label=log_label,
                regions=regions,
            )
        except DfvPowerBiError as exc:
            last_error = exc
            continue

        if uf_limpo and regs:
            regs = filtrar_registros_por_uf(regs, uf_limpo)

        if regs:
            return regs, variante

    if last_error and not isinstance(last_error, DfvPowerBiDisabled):
        pass

    # Fallback: código sem UF no Where (quando o filtro UF não retornou linhas)
    if uf_limpo and regions:
        for variante in variantes:
            try:
                regs = _consultar_em_regioes(
                    filters=[("CODIGO_CDO", variante)],
                    cache_key_base=f"{CACHE_KEY_PREFIX_CDO}{variante}",
                    log_label=f"CODIGO_CDO={variante}",
                    regions=regions,
                )
            except DfvPowerBiError:
                continue
            filtrados = filtrar_registros_por_uf(regs, uf_limpo)
            if filtrados:
                return filtrados, variante
            if regs and not filtrados:
                return [], variante

    return [], variantes[0]


def _ordenar_chave_fachada(num: Any) -> tuple[int, str]:
    texto = str(num or "").strip()
    digitos = "".join(ch for ch in texto if ch.isdigit())
    try:
        return (int(digitos) if digitos else 10**9, texto)
    except ValueError:
        return (10**9, texto)


def _filtrar_e_deduplicar(
    registros: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """
    Prefere viáveis; se não houver, mantém todos.
    Deduplica por (número + complementos).

    Returns:
        (lista_processada, usou_somente_viaveis)
    """
    viaveis = [r for r in registros if _eh_viavel(r.get("VIABILIDADE_ATUAL"))]
    usou_viaveis = bool(viaveis)
    base = viaveis if usou_viaveis else list(registros)

    vistos: set[tuple[str, str]] = set()
    unicos: list[dict[str, Any]] = []
    for row in base:
        num = str(row.get("NO_FACHADA") or "").strip()
        compl = _montar_complemento(row)
        chave = (num, compl)
        if chave in vistos:
            continue
        vistos.add(chave)
        enriched = dict(row)
        enriched["_complemento"] = compl
        enriched["_linha"] = f"{num} ({compl})" if compl else num
        unicos.append(enriched)

    unicos.sort(key=lambda r: _ordenar_chave_fachada(r.get("NO_FACHADA")))
    return unicos, usou_viaveis


def _split_mensagem(texto: str, max_len: int = 3800) -> list[str]:
    if len(texto) <= max_len:
        return [texto]
    partes: list[str] = []
    atual = ""
    for linha in texto.split("\n"):
        candidato = f"{atual}\n{linha}" if atual else linha
        if len(candidato) <= max_len:
            atual = candidato
            continue
        if atual:
            partes.append(atual)
        if len(linha) <= max_len:
            atual = linha
        else:
            for i in range(0, len(linha), max_len):
                pedaco = linha[i : i + max_len]
                if len(pedaco) == max_len:
                    partes.append(pedaco)
                else:
                    atual = pedaco
            if not atual:
                atual = ""
    if atual:
        partes.append(atual)
    return partes or [texto[:max_len]]


def formatar_resposta_dfv_powerbi(
    cep: str,
    registros: list[dict[str, Any]],
) -> list[str]:
    """
    Formata a resposta WhatsApp do comando DFV (Power BI ao vivo).

    Returns:
        Uma ou mais mensagens (fatiadas ~3800 chars).
    """
    cep_limpo = limpar_cep(cep)
    if not registros:
        return [
            (
                f"❌ *NENHUMA FACHADA ENCONTRADA (Power BI)*\n\n"
                f"Não encontramos fachadas para o CEP *{cep_limpo}* no DFV ao vivo "
                f"(cobertura {COBERTURA_DFV_TXT}).\n"
                f"Tente *Viabilidade* ou *CDOE* se souber o código do CDO."
            )
        ]

    filtrados, so_viaveis = _filtrar_e_deduplicar(registros)
    primeiro = filtrados[0] if filtrados else registros[0]
    logradouro = str(primeiro.get("LOGRADOURO") or "—").strip() or "—"
    bairro = str(primeiro.get("BAIRRO") or "—").strip() or "—"
    municipio = str(primeiro.get("MUNICIPIO") or "—").strip() or "—"
    uf = str(primeiro.get("UF") or "").strip()
    cidade_uf = f"{municipio}/{uf}" if uf else municipio
    fonte_label = str(primeiro.get("_fonte_label") or "").strip()
    fontes = sorted(
        {
            str(r.get("_fonte_label") or "").strip()
            for r in filtrados
            if r.get("_fonte_label")
        }
    )
    if len(fontes) > 1:
        fonte_label = " / ".join(fontes)
    titulo_fonte = f" — {fonte_label}" if fonte_label else ""

    cdos = sorted(
        {
            str(r.get("CODIGO_CDO")).strip()
            for r in filtrados
            if r.get("CODIGO_CDO") not in (None, "")
        }
    )
    cdos_str = ", ".join(cdos) if cdos else "—"

    linhas_num = [r["_linha"] for r in filtrados if r.get("_linha")]
    # Mesmo formato da antiga consulta Fachada: números separados por vírgula
    lista_str = ", ".join(linhas_num)

    aviso_status = ""
    if not so_viaveis:
        statuses = sorted(
            {
                str(r.get("VIABILIDADE_ATUAL") or "").strip()
                for r in filtrados
                if r.get("VIABILIDADE_ATUAL")
            }
        )
        status_txt = ", ".join(statuses) if statuses else "não informado"
        aviso_status = (
            f"\n⚠️ *Sem fachadas viáveis* neste CEP — exibindo status: {status_txt}\n"
        )

    cabecalho = (
        f"🏢 *DFV (Power BI ao vivo{titulo_fonte})*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro} | *Cidade/UF:* {cidade_uf}\n"
        f"📡 *CDO(s):* {cdos_str}\n"
        f"✅ *Total de fachadas:* {len(filtrados)}"
        f"{aviso_status}\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{lista_str}"
    )
    return _split_mensagem(cabecalho)


def _chave_rua(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("LOGRADOURO") or "").strip().upper(),
        limpar_cep(str(row.get("CEP") or "")),
        str(row.get("BAIRRO") or "").strip().upper(),
        str(row.get("MUNICIPIO") or "").strip().upper(),
        str(row.get("UF") or "").strip().upper(),
    )


def montar_grupos_rua_cdoe(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Agrupa registros por rua/CEP e retorna lista serializável para a sessão WhatsApp.

    Cada grupo contém metadados da rua e a lista deduplicada de números (_linha).
    """
    if not registros:
        return []

    filtrados, so_viaveis = _filtrar_e_deduplicar(registros)
    buckets: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for row in filtrados:
        chave = _chave_rua(row)
        if chave not in buckets:
            cep = chave[1]
            cep_fmt = f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else (cep or "—")
            municipio = str(row.get("MUNICIPIO") or "—").strip() or "—"
            uf = str(row.get("UF") or "").strip()
            buckets[chave] = {
                "logradouro": str(row.get("LOGRADOURO") or "—").strip() or "—",
                "cep": cep,
                "cep_fmt": cep_fmt,
                "bairro": str(row.get("BAIRRO") or "—").strip() or "—",
                "municipio": municipio,
                "uf": uf,
                "cidade_uf": f"{municipio}/{uf}" if uf else municipio,
                "linhas": [],
                "so_viaveis": so_viaveis,
            }
        linha = row.get("_linha")
        if linha:
            buckets[chave]["linhas"].append(str(linha))

    grupos = list(buckets.values())
    grupos.sort(
        key=lambda g: (
            g.get("logradouro") or "",
            g.get("cep") or "",
            g.get("bairro") or "",
        )
    )
    return grupos


def listar_cidades_cdoe(grupos: list[dict[str, Any]]) -> list[str]:
    """Cidades distintas dos grupos, ordenadas."""
    cidades = sorted(
        {
            str(g.get("municipio") or "").strip().upper()
            for g in grupos
            if str(g.get("municipio") or "").strip()
        }
    )
    return cidades


def filtrar_grupos_por_cidade(
    grupos: list[dict[str, Any]], cidade: str
) -> list[dict[str, Any]]:
    alvo = _sem_acentos(str(cidade or "")).strip().upper()
    if not alvo:
        return list(grupos)
    out: list[dict[str, Any]] = []
    for g in grupos:
        nome = _sem_acentos(str(g.get("municipio") or "")).strip().upper()
        if nome == alvo:
            out.append(g)
    return out


def resolver_cidade_escolhida(
    escolha: str, cidades: list[str]
) -> Optional[str]:
    """Resolve índice (1-based), id cdoe_cid_N ou nome da cidade."""
    texto = str(escolha or "").strip()
    if not texto or not cidades:
        return None

    upper = texto.upper()
    m = re.match(r"^(?:CDOE_CID_)?(\d+)$", upper.replace(" ", ""))
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(cidades):
            return cidades[idx - 1]

    alvo = _sem_acentos(upper)
    for cidade in cidades:
        if _sem_acentos(cidade) == alvo:
            return cidade
    # match parcial
    for cidade in cidades:
        if alvo and alvo in _sem_acentos(cidade):
            return cidade
    return None


def formatar_pedido_cidade_cdoe(
    codigo_cdo: str, uf: str, cidades: list[str]
) -> list[str]:
    linhas = [f"{i}) {c}" for i, c in enumerate(cidades, start=1)]
    texto = (
        f"📡 *CDOE {codigo_cdo}* — UF *{uf}*\n\n"
        f"Encontramos *{len(cidades)}* cidades. Escolha a cidade:\n"
        f"{chr(10).join(linhas)}\n\n"
        f"Digite o *número* da cidade (ou o nome) / use a lista se aparecer.\n"
        f"Ou *CANCELAR* para sair."
    )
    return _split_mensagem(texto)


def formatar_resumo_cdoe(codigo_cdo: str, grupos: list[dict[str, Any]]) -> list[str]:
    """Formata o passo de ruas da CDOE: lista numerada de ruas/CEPs."""
    codigo = limpar_codigo_cdo(codigo_cdo)
    if not grupos:
        return [
            (
                f"❌ *NENHUM ENDEREÇO ENCONTRADO (CDOE)*\n\n"
                f"Não encontramos fachadas para o código *{codigo}* no Power BI "
                f"(cobertura {COBERTURA_DFV_TXT}).\n"
                f"Confira o código (ex.: *CDOE-28005* ou *28005*) e tente novamente, "
                f"ou use *DFV* com o CEP."
            )
        ]

    total_fachadas = sum(len(g.get("linhas") or []) for g in grupos)
    linhas_resumo: list[str] = []
    for i, g in enumerate(grupos, start=1):
        qtd = len(g.get("linhas") or [])
        linhas_resumo.append(
            f"{i}) *{g.get('logradouro') or '—'}* — CEP {g.get('cep_fmt') or '—'} "
            f"— {g.get('bairro') or '—'} ({g.get('cidade_uf') or '—'}) — "
            f"{qtd} fachada{'s' if qtd != 1 else ''}"
        )

    texto = (
        f"📡 *CDOE (Power BI ao vivo)*\n\n"
        f"Código: *{codigo}*\n"
        f"Ruas/CEPs: *{len(grupos)}* | Fachadas: *{total_fachadas}*\n\n"
        f"Escolha a rua digitando o *número*:\n"
        f"{chr(10).join(linhas_resumo)}\n\n"
        f"Ou envie *CANCELAR* para sair."
    )
    return _split_mensagem(texto)


def formatar_numeros_rua_cdoe(codigo_cdo: str, grupo: dict[str, Any]) -> list[str]:
    """Formata o 2º passo da CDOE: números da rua escolhida."""
    codigo = limpar_codigo_cdo(codigo_cdo)
    linhas = list(grupo.get("linhas") or [])
    logradouro = grupo.get("logradouro") or "—"
    cep_fmt = grupo.get("cep_fmt") or "—"
    bairro = grupo.get("bairro") or "—"
    cidade_uf = grupo.get("cidade_uf") or "—"

    if not linhas:
        return [
            (
                f"❌ Nenhum número encontrado para *{logradouro}* "
                f"(CEP {cep_fmt}) na CDOE *{codigo}*."
            )
        ]

    aviso = ""
    if not grupo.get("so_viaveis", True):
        aviso = "\n⚠️ *Sem fachadas viáveis* nesta rua — exibindo todos os números encontrados.\n"

    texto = (
        f"📡 *CDOE {codigo}*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"📮 *CEP:* {cep_fmt}\n"
        f"🏙️ *Bairro:* {bairro} | *Cidade/UF:* {cidade_uf}\n"
        f"✅ *Total de fachadas:* {len(linhas)}"
        f"{aviso}\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{', '.join(linhas)}"
    )
    return _split_mensagem(texto)
