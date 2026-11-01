"""
Django settings for Offerboard.

One settings file for every environment. Anything that differs between your
laptop and production (secrets, debug, hosts, database) comes from environment
variables, which are loaded from .env when that file exists.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    """Read an environment variable, treating an empty value as unset."""
    return os.environ.get(name) or default


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# --- Core --------------------------------------------------------------------

# DEBUG is off unless explicitly turned on, so a missing variable in
# production can never expose debug pages.
DEBUG = env("DEBUG") == "1"

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render sets this to the service's own hostname (e.g. offerboard.onrender.com).
if render_host := env("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "accounts",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page requires sign-in unless its view is marked @login_not_required.
    # Secure by default: forgetting a decorator locks a page, it never leaks one.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "accounts.context_processors.auth_options",
            ],
        },
    },
]

# --- Database ----------------------------------------------------------------

# Production uses Supabase Postgres through DATABASE_URL. Locally it falls back
# to SQLite so the app runs with zero setup; CI runs the tests on Postgres.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth --------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "tracker:board"
ACCOUNT_LOGOUT_REDIRECT_URL = "landing"

# Email + password only; no usernames anywhere in the UI.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_SESSION_REMEMBER = True
# Turned on in milestone 5, once real email sending is set up.
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"  # for links in emails

# Google sign-in is configured from env vars, so no database setup is needed.
# Without the variables the Google button simply isn't shown.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        # Google verifies emails, so signing in with Google links to an existing
        # email/password account with the same address instead of failing.
        "EMAIL_AUTHENTICATION": True,
        "APPS": (
            [{"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET, "key": ""}]
            if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
            else []
        ),
    }
}
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = True  # one click on "Continue with Google", no extra confirm page

# --- Email -------------------------------------------------------------------

# Reminder emails go out through Gmail SMTP from a GitHub Actions job (see
# .github/workflows/reminders.yml). Render's free tier blocks outgoing SMTP, so
# the web app itself never sets these and uses the console backend (log only).
smtp_username = env("SMTP_USERNAME")
smtp_password = env("SMTP_PASSWORD")
if smtp_username and smtp_password:
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": env("SMTP_HOST", "smtp.gmail.com"),
                "port": int(env("SMTP_PORT", "587")),
                "username": smtp_username,
                "password": smtp_password,
                "use_tls": True,
                "timeout": 20,
            },
        }
    }
else:
    MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", f"Offerboard <{smtp_username or 'noreply@offerboard.local'}>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Full address of the site, for links in emails (there's no request to build them from).
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")

# Shown on the privacy page for questions and deletion requests.
CONTACT_EMAIL = env("CONTACT_EMAIL")

# --- Static files ------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed filenames + gzip/brotli, served by WhiteNoise with far-future caching.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Security (production) ---------------------------------------------------

if not DEBUG:
    # Render terminates HTTPS at its proxy and forwards plain HTTP.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SILENCED_SYSTEM_CHECKS = [
    # HSTS preload is a promise for a whole domain; we don't own onrender.com.
    "security.W021",
    # The web app on Render deliberately has no mail server (Render's free tier
    # blocks SMTP). Reminder emails are sent from GitHub Actions instead.
    "mail.E001",
]
X_FRAME_OPTIONS = "DENY"
# The health check is called over plain HTTP by Render's internal checker.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]

# --- Misc --------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "America/Toronto")
USE_I18N = True
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
