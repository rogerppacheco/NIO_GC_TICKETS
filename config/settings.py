import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-nio-gc-tickets")
DEBUG = os.environ.get("DEBUG", "True").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tickets",
    "gestao",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "gestao.middleware.RequestContextMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tickets.middleware.AcessoInternoMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tickets.context_processors.nav_counts",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

POSTGRES_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "nio_gc_tickets").strip()
if DATABASES["default"].get("ENGINE", "").endswith("postgresql"):
    options = DATABASES["default"].setdefault("OPTIONS", {})
    # Schema do app primeiro: auth_user local (não o cadastro da viabilidade em public).
    options["options"] = f"-c search_path={POSTGRES_SCHEMA},public"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# --- Media / anexos ---
# Local (dev): disco do projeto
# Produção: Cloudflare R2 (S3-compatível) quando as variáveis R2_* estiverem setadas
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "").strip()
R2_CUSTOM_DOMAIN = os.environ.get("R2_CUSTOM_DOMAIN", "").strip()  # ex.: media.seudominio.com
R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "").strip()  # ex.: https://pub-xxx.r2.dev

USE_R2 = all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME])

if USE_R2:
    AWS_ACCESS_KEY_ID = R2_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY = R2_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET_NAME
    AWS_S3_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    AWS_S3_REGION_NAME = "auto"
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "public, max-age=86400"}
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_ADDRESSING_STYLE = "path"

    if R2_CUSTOM_DOMAIN:
        AWS_S3_CUSTOM_DOMAIN = R2_CUSTOM_DOMAIN
        MEDIA_URL = f"https://{R2_CUSTOM_DOMAIN}/"
    elif R2_PUBLIC_BASE_URL:
        # URL pública do bucket (r2.dev) — sem barra final no env
        base = R2_PUBLIC_BASE_URL.rstrip("/")
        AWS_S3_CUSTOM_DOMAIN = base.replace("https://", "").replace("http://", "")
        MEDIA_URL = f"{base}/"
    else:
        # Fallback: endpoint do R2 (só funciona se o bucket permitir leitura pública)
        AWS_S3_CUSTOM_DOMAIN = None
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{R2_BUCKET_NAME}/"
        AWS_QUERYSTRING_AUTH = True

    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fila"
LOGOUT_REDIRECT_URL = "login"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --- Consultas DFV/CDOE (Power BI ao vivo — mesmo serviço do site-record) ---
DFV_POWERBI_ENABLED = os.environ.get("DFV_POWERBI_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
    "sim",
}
DFV_POWERBI_RESOURCE_KEY = os.environ.get(
    "DFV_POWERBI_RESOURCE_KEY", "8a9db8f9-7cf1-4db5-90d2-5259ad149eba"
).strip()
DFV_POWERBI_CLUSTER = os.environ.get(
    "DFV_POWERBI_CLUSTER", "https://wabi-brazil-south-b-primary-api.analysis.windows.net"
).strip()
DFV_POWERBI_MODEL_ID = int(os.environ.get("DFV_POWERBI_MODEL_ID", "6061538") or "6061538")
DFV_POWERBI_SP_RESOURCE_KEY = os.environ.get(
    "DFV_POWERBI_SP_RESOURCE_KEY", "81e95c1a-e770-44e3-9646-19df8443756c"
).strip()
DFV_POWERBI_SP_MODEL_ID = int(os.environ.get("DFV_POWERBI_SP_MODEL_ID", "7340452") or "7340452")
DFV_POWERBI_SUL_RESOURCE_KEY = os.environ.get(
    "DFV_POWERBI_SUL_RESOURCE_KEY", "cc212c25-1b6a-4301-877b-703e2c7aa788"
).strip()
DFV_POWERBI_SUL_MODEL_ID = int(os.environ.get("DFV_POWERBI_SUL_MODEL_ID", "6062850") or "6062850")
DFV_POWERBI_CO_RESOURCE_KEY = os.environ.get(
    "DFV_POWERBI_CO_RESOURCE_KEY", "a321b404-8186-4645-8070-507a8fea6abb"
).strip()
DFV_POWERBI_CO_MODEL_ID = int(os.environ.get("DFV_POWERBI_CO_MODEL_ID", "6063900") or "6063900")
DFV_POWERBI_NNE_RESOURCE_KEY = os.environ.get(
    "DFV_POWERBI_NNE_RESOURCE_KEY", "7b6cd391-63ef-4af2-9b09-1b0b1caa29a9"
).strip()
DFV_POWERBI_NNE_MODEL_ID = int(os.environ.get("DFV_POWERBI_NNE_MODEL_ID", "6064171") or "6064171")
DFV_POWERBI_TIMEOUT_SECONDS = float(os.environ.get("DFV_POWERBI_TIMEOUT_SECONDS", "18") or "18")
DFV_POWERBI_CACHE_TTL_SECONDS = int(os.environ.get("DFV_POWERBI_CACHE_TTL_SECONDS", "600") or "600")

# Formulário Google Forms do projeto consulta-viabilidade-vtal (mesmo link da tela de login)
VIABILIDADE_FORMS_URL = os.environ.get(
    "VIABILIDADE_FORMS_URL",
    "https://docs.google.com/forms/d/e/1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform",
).strip()

# --- WhatsApp: Evolution API + n8n (mesmo padrão do site-record) ---
EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "").strip()
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "").strip()
EVOLUTION_INSTANCE_NAME = os.environ.get("EVOLUTION_INSTANCE_NAME", "nio_gc_tickets").strip() or "nio_gc_tickets"
N8N_OUTBOUND_WEBHOOK_URL = (
    os.environ.get("N8N_OUTBOUND_WEBHOOK_URL") or os.environ.get("N8N_WEBHOOK_URL") or ""
).strip()
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "").strip()
WHATSAPP_TEST_JID = (os.environ.get("WHATSAPP_TEST_JID") or os.environ.get("SYNCWA_TEST_JID") or "").strip()
SYNCWA_TEST_JID = WHATSAPP_TEST_JID
SYNCWA_MODO_TESTE = (
    os.environ.get("WHATSAPP_MODO_TESTE") or os.environ.get("SYNCWA_MODO_TESTE") or "False"
).lower() in {"1", "true", "yes", "on"}
SYNCWA_TIMEOUT = int(os.environ.get("SYNCWA_TIMEOUT", "60"))
FPD_PERCENTUAL_CRITICO = float(os.environ.get("FPD_PERCENTUAL_CRITICO", "30"))

# SMTP — mesmo padrão do sistema de auditorias (Office 365 / sysr)
SMTP_HOST = (os.environ.get("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS") or ""
SMTP_FROM = (os.environ.get("SMTP_FROM") or "").strip()
SMTP_USE_TLS = (os.environ.get("SMTP_USE_TLS", "true") or "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "sim",
}
