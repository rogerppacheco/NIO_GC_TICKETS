from __future__ import annotations

import json
import mimetypes
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.urls import reverse
from django.utils._os import safe_join

ICONES = {
    "manuais": "📘",
    "enxoval_merchan": "🪧",
    "folheteria": "📄",
    "uniformes": "👕",
    "ambientacao_escritorio": "🏢",
    "brindes": "🎁",
    "trade_digital": "📱",
    "vende_comunica": "📣",
    "prospeccao": "🔎",
    "pap_alto_valor": "⭐",
    "piloto_toolkit_meta": "🧪",
}

NOME = "Kit de marca"

SLUGS_SOMENTE_EQUIPE = frozenset({"prospeccao", "pap_alto_valor"})

GRUPOS = (
    (
        "loja",
        "Para o PDV",
        (
            "manuais",
            "enxoval_merchan",
            "folheteria",
            "ambientacao_escritorio",
            "brindes",
            "piloto_toolkit_meta",
        ),
    ),
    ("time", "Para o time", ("uniformes",)),
    ("canais", "Apps e comunicados", ("trade_digital", "vende_comunica")),
    ("campo", "Uso interno", ("prospeccao", "pap_alto_valor")),
)

EXTRAS = {
    "prospeccao": {
        "titulo": "Prospecção",
        "intro": "Apresentações e cards para abordar parceiro e PAP.",
    },
    "pap_alto_valor": {
        "titulo": "PAP Alto Valor",
        "intro": "Cartas e peças da operação PAP Alto Valor.",
    },
    "piloto_toolkit_meta": {
        "titulo": "Piloto Toolkit Meta",
        "intro": "Arquivos do piloto de toolkit para Meta.",
    },
}

SIGLAS = {"pap": "PAP", "pdv": "PDV", "nio": "NIO", "meta": "Meta", "rgb": "RGB", "id": "ID"}


def _dir() -> Path:
    return Path(getattr(settings, "TRADEHUB_DIR", Path(__file__).resolve().parent.parent / "tradehub"))


def _norm(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def humanizar(nome: str) -> str:
    partes = nome.replace("_", " ").replace("-", " ").split()
    saida = []
    for parte in partes:
        chave = parte.lower()
        if chave in SIGLAS:
            saida.append(SIGLAS[chave])
        elif parte.isupper() or (parte[:1].isdigit() and len(parte) > 1):
            saida.append(parte)
        else:
            saida.append(parte.capitalize())
    return " ".join(saida) or nome


def formatar_tamanho(n: int | None) -> str:
    if not n:
        return "—"
    valor = float(n)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            if unidade == "B":
                return f"{int(valor)} {unidade}"
            return f"{valor:.1f} {unidade}"
        valor /= 1024
    return "—"


@lru_cache(maxsize=1)
def _conteudo() -> dict:
    path = _dir() / "conteudo.json"
    if not path.is_file():
        return {"home": {}, "faq": [], "categorias": []}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inventario() -> list[dict]:
    path = _dir() / "inventario.json"
    if not path.is_file():
        return []
    dados = json.loads(path.read_text(encoding="utf-8"))
    arquivos = []
    for item in dados.get("files") or []:
        rel = _norm(item.get("path") or "")
        if not rel or rel.endswith("/"):
            continue
        arquivos.append(
            {
                "path": rel,
                "nome": rel.rsplit("/", 1)[-1],
                "bytes": item.get("bytes") or 0,
                "content_type": item.get("content_type") or "",
            }
        )
    return arquivos


def conteudo() -> dict:
    return _conteudo()


def prefixo_r2() -> str:
    prefixo = getattr(settings, "TRADEHUB_R2_PREFIX", "tradehub/") or "tradehub/"
    return prefixo if prefixo.endswith("/") else prefixo + "/"


def chave_r2(rel: str) -> str:
    return f"{prefixo_r2()}{_norm(rel)}"


def caminho_local(rel: str) -> Path | None:
    rel = _norm(rel)
    if not rel or ".." in rel.split("/"):
        return None
    try:
        full = safe_join(str(_dir()), *rel.split("/"))
    except ValueError:
        return None
    return Path(full) if full else None


def media_publico() -> bool:
    return bool(
        getattr(settings, "USE_R2", False)
        and (
            getattr(settings, "R2_PUBLIC_BASE_URL", "")
            or getattr(settings, "R2_CUSTOM_DOMAIN", "")
        )
    )


def url_publica_r2(rel: str) -> str:
    base = getattr(settings, "MEDIA_URL", "/") or "/"
    if not base.endswith("/"):
        base += "/"
    return urljoin(base, chave_r2(rel))


def url_download(rel: str) -> str:
    rel = _norm(rel)
    local = caminho_local(rel)
    if local and local.is_file():
        return reverse("tradehub_arquivo", kwargs={"rel": rel})
    if media_publico():
        return url_publica_r2(rel)
    return reverse("tradehub_arquivo", kwargs={"rel": rel})


def disponivel(rel: str) -> bool:
    local = caminho_local(rel)
    if local and local.is_file():
        return True
    return bool(getattr(settings, "USE_R2", False))


def extensao(nome: str) -> str:
    suf = Path(nome).suffix.lower().lstrip(".")
    return suf or "arquivo"


def _contar_por_prefixo(prefixo: str) -> int:
    prefixo = _norm(prefixo)
    if prefixo and not prefixo.endswith("/"):
        prefixo += "/"
    return sum(1 for item in _inventario() if item["path"].startswith(prefixo))


def pode_ver_categoria(user, slug: str) -> bool:
    """PAP Alto Valor e Prospecção: só especialista ou gerência."""
    if slug not in SLUGS_SOMENTE_EQUIPE:
        return True
    from .acesso import eh_especialista, eh_gerencia

    return eh_especialista(user) or eh_gerencia(user)


def slug_da_rel(rel: str) -> str:
    partes = _norm(rel).split("/")
    if len(partes) >= 2 and partes[0] == "materiais":
        return partes[1]
    return ""


def pode_ver_material(user, rel: str) -> bool:
    slug = slug_da_rel(rel)
    if not slug:
        return True
    return pode_ver_categoria(user, slug)


def categorias(user=None) -> list[dict]:
    base = list(_conteudo().get("categorias") or [])
    conhecidas = {c.get("slug") for c in base}
    tops: dict[str, int] = {}
    for item in _inventario():
        partes = item["path"].split("/")
        if len(partes) < 2 or partes[0] != "materiais":
            continue
        tops[partes[1]] = tops.get(partes[1], 0) + 1
    for slug, n in sorted(tops.items()):
        if slug in conhecidas:
            continue
        extra = EXTRAS.get(slug, {})
        base.append(
            {
                "slug": slug,
                "titulo": extra.get("titulo") or humanizar(slug),
                "intro": extra.get("intro") or "Outros arquivos desta biblioteca.",
            }
        )
        conhecidas.add(slug)
    saida = []
    for cat in base:
        slug = cat["slug"]
        saida.append(
            {
                **cat,
                "icone": ICONES.get(slug, "📦"),
                "n_arquivos": _contar_por_prefixo(f"materiais/{slug}/") if slug not in {"trade_digital", "vende_comunica"} else 0,
            }
        )
    if user is not None:
        saida = [cat for cat in saida if pode_ver_categoria(user, cat["slug"])]
    return saida


def categoria(slug: str, user=None) -> dict | None:
    for cat in categorias(user):
        if cat["slug"] == slug:
            return cat
    return None


def categorias_agrupadas(user=None) -> list[dict]:
    cats = categorias(user)
    por_slug = {c["slug"]: c for c in cats}
    grupos = []
    vistos: set[str] = set()
    for gid, titulo, slugs in GRUPOS:
        itens = [por_slug[s] for s in slugs if s in por_slug]
        if not itens:
            continue
        grupos.append({"id": gid, "titulo": titulo, "categorias": itens})
        vistos.update(c["slug"] for c in itens)
    resto = [c for c in cats if c["slug"] not in vistos]
    if resto:
        grupos.append({"id": "outros", "titulo": "Outros arquivos", "categorias": resto})
    return grupos


def filtrar_grupos(grupos: list[dict], q: str) -> list[dict]:
    termo = (q or "").strip().lower()
    if not termo:
        return grupos
    saida = []
    for grupo in grupos:
        cats = [
            c
            for c in grupo["categorias"]
            if termo in (c.get("titulo") or "").lower() or termo in (c.get("intro") or "").lower()
        ]
        if cats:
            saida.append({**grupo, "categorias": cats})
    return saida


def listar_pasta(prefixo: str) -> tuple[list[dict], list[dict]]:
    prefixo = _norm(prefixo)
    if prefixo and not prefixo.endswith("/"):
        prefixo += "/"
    subdirs: dict[str, int] = {}
    arquivos: list[dict] = []
    for item in _inventario():
        path = item["path"]
        if prefixo and not path.startswith(prefixo):
            continue
        resto = path[len(prefixo) :] if prefixo else path
        if not resto:
            continue
        if "/" in resto:
            nome = resto.split("/", 1)[0]
            subdirs[nome] = subdirs.get(nome, 0) + 1
            continue
        arquivos.append(
            {
                **item,
                "ext": extensao(item["nome"]),
                "tamanho": formatar_tamanho(item["bytes"]),
                "url": url_download(item["path"]),
                "tipo": mimetypes.guess_type(item["nome"])[0] or item.get("content_type") or "",
            }
        )
    pastas = [
        {
            "nome": nome,
            "titulo": humanizar(nome),
            "n_arquivos": n,
            "rel": nome,
        }
        for nome, n in sorted(subdirs.items(), key=lambda x: x[0].lower())
    ]
    arquivos.sort(key=lambda x: x["nome"].lower())
    return pastas, arquivos


def _url_pasta(slug: str, rel_dentro: str) -> str:
    rel_dentro = _norm(rel_dentro).rstrip("/")
    if not rel_dentro:
        return reverse("tradehub_secao", kwargs={"slug": slug})
    return reverse("tradehub_pasta", kwargs={"slug": slug, "pasta": rel_dentro})


def destaques(cat: dict, slug: str) -> list[dict]:
    itens = []
    if cat.get("manual"):
        itens.append({"titulo": "Manual", "arquivo": cat["manual"]})
    if cat.get("manuais_pasta"):
        itens.append({"titulo": "Manuais de uniformes", "pasta": cat["manuais_pasta"]})
    itens.extend(cat.get("itens") or [])
    for peca in cat.get("pecas") or []:
        itens.append({"titulo": humanizar(Path(peca.rstrip("/")).name), "pasta": peca})

    prefixo_cat = f"materiais/{slug}/"
    saida = []
    vistos: set[str] = set()
    for item in itens:
        bloco: dict = {"titulo": item.get("titulo") or "Material"}
        extras = []
        if item.get("cidades"):
            extras.append({"titulo": "Lista de cidades", "url": url_download(item["cidades"])})
        if item.get("orientacao"):
            extras.append({"titulo": "Orientação para produção", "url": url_download(item["orientacao"])})
        bloco["extras"] = extras
        if item.get("arquivo"):
            rel = _norm(item["arquivo"])
            if rel in vistos:
                continue
            vistos.add(rel)
            bloco["url"] = url_download(rel)
            bloco["path"] = rel
            bloco["ext"] = extensao(rel)
            bloco["tipo"] = "arquivo"
        elif item.get("pasta"):
            pasta = _norm(item["pasta"])
            if pasta in vistos:
                continue
            vistos.add(pasta)
            bloco["tipo"] = "pasta"
            bloco["path"] = pasta
            if pasta.startswith(prefixo_cat):
                bloco["rel"] = pasta[len(prefixo_cat) :].strip("/")
                bloco["url"] = _url_pasta(slug, bloco["rel"])
            else:
                bloco["rel"] = pasta
                bloco["url"] = _url_pasta(slug, pasta)
        else:
            continue
        saida.append(bloco)
    return saida


def filtrar(q: str, pastas: list[dict], arquivos: list[dict]) -> tuple[list[dict], list[dict]]:
    termo = (q or "").strip().lower()
    if not termo:
        return pastas, arquivos
    pastas = [p for p in pastas if termo in p["titulo"].lower() or termo in p["nome"].lower()]
    arquivos = [a for a in arquivos if termo in a["nome"].lower()]
    return pastas, arquivos
