from common.utils.type import *
from pathlib import Path
import json
import os

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "0123456789012345678901234567890123456789")
DEBUG = str_to_bool(os.getenv("DJANGO_DEBUG", "0"))
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("DJANGO_VIRTUAL_HOST", "http://127.0.0.1").split(",")
STATIC_ROOT = os.path.join(BASE_DIR, "data", "public", "static")
STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
MEDIA_ROOT = os.path.join(BASE_DIR, "data", "public", "media")
MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")

LOGIN_URL = "/account/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = os.getenv("AUTHELIA_LOGOUT_URL", "/")

AUTHENTICATION_BACKENDS = [
    "common.auth.AutheliaBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTHELIA_AUTH_ENABLED = str_to_bool(os.getenv("AUTHELIA_AUTH_ENABLED", "0"))
AUTHELIA_USER_HEADER = os.getenv("AUTHELIA_USER_HEADER", "HTTP_REMOTE_USER")
AUTHELIA_GROUPS_HEADER = os.getenv("AUTHELIA_GROUPS_HEADER", "HTTP_REMOTE_GROUPS")
AUTHELIA_EMAIL_HEADER = os.getenv("AUTHELIA_EMAIL_HEADER", "HTTP_REMOTE_EMAIL")
AUTHELIA_NAME_HEADER = os.getenv("AUTHELIA_NAME_HEADER", "HTTP_REMOTE_NAME")
AUTHELIA_ADMIN_GROUPS = [group.strip() for group in os.getenv("AUTHELIA_ADMIN_GROUPS", "admin").split(",") if group.strip()]
AUTHELIA_TRUSTED_PROXIES = [proxy.strip() for proxy in os.getenv("AUTHELIA_TRUSTED_PROXIES", "").split(",") if proxy.strip()]
# When enabled, any user authenticated by Authelia is granted staff/superuser
# access regardless of the Remote-Groups header. Useful when the reverse proxy
# does not forward groups and the site is already gated by Authelia.
AUTHELIA_ALL_STAFF = str_to_bool(os.getenv("AUTHELIA_ALL_STAFF", "0"))

with open(os.path.join(BASE_DIR, "logging.json"), "r") as f:
    LOGGING = json.load(f)
    LOGGING["root"]["level"] = os.getenv("DJANGO_LOG_LEVEL", "WARNING").upper()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "django_cleanup.apps.CleanupConfig",
    "django_bootstrap_icons",
    "crispy_forms",
    "crispy_bootstrap5",
    "common",
    "macros",
    "sdr",
]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.auth.AutheliaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "monitor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "common.views.load_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "monitor.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.{}".format(os.getenv("DATABASE_ENGINE", "sqlite3")),
        "NAME": os.getenv("DATABASE_NAME", os.path.join(BASE_DIR, "data", "db.sqlite3")),
        "USER": os.getenv("DATABASE_USERNAME", "admin"),
        "PASSWORD": os.getenv("DATABASE_PASSWORD", "password"),
        "HOST": os.getenv("DATABASE_HOST", "127.0.0.1"),
        "PORT": os.getenv("DATABASE_PORT", 5432),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

FORMAT_MODULE_PATH = ["common.formats"]
LANGUAGE_CODE = "en-us"
LANGUAGES = [("en", "English")]
LOCALE_PATHS = [os.path.join(BASE_DIR, "locale")]
TITLE_CLASS = "m-2 p-0"
TIME_ZONE = os.getenv("TZ", "UTC")
SATELLITES_CACHE_DIR = os.path.join(BASE_DIR, "cache", "satellites")
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MQTT = {
    "url": os.getenv("MQTT_URL", ""),
    "user": os.getenv("MQTT_USER", ""),
    "password": os.getenv("MQTT_PASSWORD", ""),
    "frontend_path": os.getenv("MQTT_FRONTEND_PATH", ""),
}

LOG_DIR = os.getenv("LOG_DIR", "")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
