from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tickets.tradehub_catalogo import chave_r2, prefixo_r2


class Command(BaseCommand):
    help = "Envia os arquivos de tradehub/materiais para o Cloudflare R2."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Só lista o que seria enviado.")
        parser.add_argument("--force", action="store_true", help="Reenvia mesmo se o objeto já existir com o mesmo tamanho.")
        parser.add_argument("--limit", type=int, default=0, help="Envia no máximo N arquivos (0 = todos).")

    def handle(self, *args, **options):
        if not getattr(settings, "USE_R2", False):
            raise CommandError(
                "R2 não está configurado. Defina R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY e R2_BUCKET_NAME."
            )
        raiz = Path(settings.TRADEHUB_DIR) / "materiais"
        if not raiz.is_dir():
            raise CommandError(f"Pasta local não encontrada: {raiz}")

        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError

        cliente = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        bucket = settings.R2_BUCKET_NAME
        arquivos = [p for p in raiz.rglob("*") if p.is_file()]
        arquivos.sort()
        limite = options["limit"]
        if limite:
            arquivos = arquivos[:limite]

        enviados = 0
        pulados = 0
        erros = 0
        self.stdout.write(
            f"{len(arquivos)} arquivo(s) · prefixo {prefixo_r2()!r} · bucket {bucket}"
        )
        for i, path in enumerate(arquivos, start=1):
            rel = path.relative_to(Path(settings.TRADEHUB_DIR)).as_posix()
            key = chave_r2(rel)
            tamanho = path.stat().st_size
            if not options["force"]:
                try:
                    meta = cliente.head_object(Bucket=bucket, Key=key)
                    if int(meta.get("ContentLength") or 0) == tamanho:
                        pulados += 1
                        continue
                except ClientError:
                    pass
            if options["dry_run"]:
                enviados += 1
                continue
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            extra = {
                "ContentType": ctype,
                "CacheControl": "public, max-age=86400",
            }
            try:
                cliente.upload_file(str(path), bucket, key, ExtraArgs=extra)
                enviados += 1
            except Exception as exc:
                erros += 1
                self.stderr.write(self.style.ERROR(f"falhou {rel}: {exc}"))
            if i % 25 == 0 or i == len(arquivos):
                self.stdout.write(f"{i}/{len(arquivos)} · enviados={enviados} pulados={pulados} erros={erros}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Concluído · enviados={enviados} pulados={pulados} erros={erros}"
            )
        )
