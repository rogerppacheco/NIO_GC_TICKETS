from __future__ import annotations

import mimetypes

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import tradehub_catalogo as catalogo


def _prefixo_categoria(slug: str) -> str:
    return f"materiais/{slug}/"


@login_required
@require_GET
def tradehub_inicio(request: HttpRequest) -> HttpResponse:
    dados = catalogo.conteudo()
    return render(
        request,
        "tickets/tradehub/inicio.html",
        {
            "home": dados.get("home") or {},
            "faq": dados.get("faq") or [],
            "categorias": catalogo.categorias(),
        },
    )


@login_required
@require_GET
def tradehub_secao(request: HttpRequest, slug: str, pasta: str = "") -> HttpResponse:
    cat = catalogo.categoria(slug)
    if not cat:
        raise Http404("Categoria não encontrada.")
    pasta = catalogo._norm(pasta).strip("/")
    prefixo = _prefixo_categoria(slug)
    if pasta:
        if ".." in pasta.split("/"):
            raise Http404("Pasta inválida.")
        prefixo = f"{prefixo}{pasta}/"
    q = (request.GET.get("q") or "").strip()
    pastas, arquivos = catalogo.listar_pasta(prefixo)
    pastas, arquivos = catalogo.filtrar(q, pastas, arquivos)
    destaques = [] if pasta or q else catalogo.destaques(cat, slug)
    if destaques:
        arquivos_destaque = {d["path"] for d in destaques if d.get("tipo") == "arquivo" and d.get("path")}
        pastas_destaque = {d.get("rel") for d in destaques if d.get("tipo") == "pasta" and d.get("rel")}
        arquivos = [a for a in arquivos if a["path"] not in arquivos_destaque]
        pastas = [p for p in pastas if p["rel"] not in pastas_destaque]
    for item in pastas:
        rel = f"{pasta}/{item['rel']}".strip("/") if pasta else item["rel"]
        item["url"] = catalogo._url_pasta(slug, rel)
    crumbs = [{"titulo": "Trade Hub", "url": "tradehub"}]
    crumbs.append({"titulo": cat["titulo"], "url": None if not pasta else "secao", "slug": slug})
    if pasta:
        acumulado = []
        for parte in pasta.split("/"):
            acumulado.append(parte)
            crumbs.append(
                {
                    "titulo": catalogo.humanizar(parte),
                    "url": "pasta",
                    "slug": slug,
                    "pasta": "/".join(acumulado),
                }
            )
        crumbs[-1]["url"] = None
    return render(
        request,
        "tickets/tradehub/secao.html",
        {
            "categoria": cat,
            "pasta": pasta,
            "titulo": catalogo.humanizar(pasta.split("/")[-1]) if pasta else cat["titulo"],
            "intro": "" if pasta else cat.get("intro") or "",
            "destaques": destaques,
            "pastas": pastas,
            "arquivos": arquivos,
            "q": q,
            "crumbs": crumbs,
            "app": None if pasta else cat.get("app"),
        },
    )


@login_required
@require_http_methods(["GET", "HEAD"])
def tradehub_arquivo(request: HttpRequest, rel: str) -> HttpResponse:
    rel = catalogo._norm(rel)
    local = catalogo.caminho_local(rel)
    if local and local.is_file():
        ctype = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        return FileResponse(local.open("rb"), as_attachment=True, filename=local.name, content_type=ctype)
    if catalogo.media_publico():
        return redirect(catalogo.url_publica_r2(rel))
    if getattr(settings, "USE_R2", False):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise Http404("Arquivo indisponível.") from exc
        cliente = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        url = cliente.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": catalogo.chave_r2(rel)},
            ExpiresIn=300,
        )
        return redirect(url)
    raise Http404("Arquivo não encontrado.")
