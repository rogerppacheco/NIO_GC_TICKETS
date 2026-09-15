"""Espelha /public/materiais/ do Trade Hub (listagens Apache públicas)."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

BASE = "https://tradehub.nioprojetos.com.br/public/materiais/"
ROOT = Path(__file__).resolve().parent
MIRROR = ROOT / "materiais"
UA = "NIO-GC-Tickets TradeHub mirror/1.0"
WORKERS = 6


class ListingParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__()
        self.page_url = page_url
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href or href.startswith("?") or href.startswith("#"):
            return
        self.hrefs.append(urljoin(self.page_url, href))


def fetch(url: str, timeout: int = 180) -> tuple[int, str, bytes]:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def is_under_base(url: str) -> bool:
    p = urlparse(url)
    base = urlparse(BASE)
    return p.netloc == base.netloc and p.path.startswith(urlparse(BASE).path)


def looks_like_dir(url: str) -> bool:
    path = urlparse(url).path
    if path.endswith("/"):
        return True
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in name


def local_path(url: str) -> Path:
    rel = unquote(urlparse(url).path)
    prefix = urlparse(BASE).path
    if rel.startswith(prefix):
        rel = rel[len(prefix) :]
    rel = rel.lstrip("/")
    return MIRROR / rel


def collect() -> tuple[list[str], list[str], list[dict]]:
    seen: set[str] = set()
    dirs: list[str] = []
    files: list[str] = []
    errors: list[dict] = []
    queue = [BASE]
    while queue:
        url = queue.pop(0).split("#")[0]
        if looks_like_dir(url) and not url.endswith("/"):
            url += "/"
        if url in seen or not is_under_base(url):
            continue
        seen.add(url)
        if not looks_like_dir(url):
            files.append(url)
            continue
        try:
            _status, ctype, data = fetch(url, timeout=60)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append({"url": url, "error": str(exc), "phase": "list"})
            continue
        if "html" not in (ctype or "").lower():
            files.append(url.rstrip("/"))
            continue
        dirs.append(url)
        parser = ListingParser(url)
        parser.feed(data.decode("utf-8", errors="replace"))
        for href in parser.hrefs:
            href = href.split("#")[0]
            path = urlparse(href).path
            name = path.rstrip("/").rsplit("/", 1)[-1]
            if name in {"", "icons"} or "/icons/" in href:
                continue
            if href.rstrip("/") == url.rstrip("/"):
                continue
            if not is_under_base(href):
                continue
            if href not in seen:
                queue.append(href)
    return dirs, files, errors


def download_one(url: str) -> dict:
    dest = local_path(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return {
            "url": url,
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "bytes": dest.stat().st_size,
            "skipped": True,
        }
    try:
        _status, ctype, data = fetch(url)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"url": url, "error": str(exc), "phase": "download"}
    dest.write_bytes(data)
    return {
        "url": url,
        "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
        "bytes": len(data),
        "content_type": ctype,
    }


def main() -> None:
    t0 = time.time()
    MIRROR.mkdir(parents=True, exist_ok=True)
    print("Listando pastas...", flush=True)
    dirs, files, errors = collect()
    print(f"dirs={len(dirs)} files={len(files)} list_errors={len(errors)}", flush=True)
    downloaded: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(download_one, u): u for u in files}
        done = 0
        for fut in as_completed(futs):
            row = fut.result()
            downloaded.append(row)
            if row.get("error"):
                errors.append(row)
            done += 1
            if done % 25 == 0 or done == len(files):
                print(f"download {done}/{len(files)}", flush=True)
    ok = [f for f in downloaded if not f.get("error")]
    inventory = {
        "source": BASE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "n_dirs": len(dirs),
        "n_files": len(ok),
        "n_errors": len(errors),
        "total_bytes": sum(f.get("bytes") or 0 for f in ok),
        "dirs": dirs,
        "files": ok,
        "errors": errors,
    }
    (ROOT / "inventario.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "n_dirs": inventory["n_dirs"],
                "n_files": inventory["n_files"],
                "n_errors": inventory["n_errors"],
                "total_mb": round(inventory["total_bytes"] / (1024 * 1024), 1),
                "elapsed_sec": inventory["elapsed_sec"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
