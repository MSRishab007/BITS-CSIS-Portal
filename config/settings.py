"""
Settings for the department asset & purchase portal.

All environment-specific values come from a `.env` file (see `.env.example`),
so the same code runs on a laptop and on the college server.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECURE_COOKIES=(bool, False),
    ALLOWED_EMAIL_DOMAINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")


def _path(value: str) -> Path:
    """Resolve a path from .env; relative paths are relative to the project."""
    p = Path(value)
    return p if p.is_absolute() else BASE_DIR / p


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "axes",
    "simple_history",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.purchases",
    "apps.administration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    # Records which user made each change in the change history.
    "simple_history.middleware.HistoryRequestMiddleware",
    # Must be last: turns a locked-out login into a "too many attempts" page.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
                "apps.core.context_processors.portal",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database: SQLite tuned for a small multi-user web app.
#   WAL            -> readers don't block the writer
#   busy_timeout   -> wait up to 5 s for a lock instead of failing at once
#   IMMEDIATE      -> take the write lock at the start of a transaction,
#                     avoiding "database is locked" errors mid-transaction
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _path(env("DATABASE_PATH", default="db.sqlite3")),
        "OPTIONS": {
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=5000;"
                "PRAGMA foreign_keys=ON;"
            ),
            "transaction_mode": "IMMEDIATE",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# Argon2 first: new and changed passwords are hashed with it.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Order matters: axes checks for a lockout before the password is tested.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.EmailOrUsernameBackend",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Length of passwords generated for new users and resets (excluding dashes).
GENERATED_PASSWORD_LENGTH = 12

# ---- Login lockout (django-axes) ----------------------------------------
# 5 wrong passwords for the same account -> that account is locked for
# 15 minutes. Counted per account, not per IP, because the whole campus may
# share one public IP. A successful login resets the count.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_USERNAME_CALLABLE = "apps.accounts.backends.axes_username"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked_out.html"

SILENCED_SYSTEM_CHECKS = [
    # axes suggests also keying on IP. We lock per account on purpose
    # (shared campus IP); changing browser/cookies can't bypass it.
    "axes.W006",
]

# Email domains allowed to hold accounts (lower-case). Empty list = any.
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in env("ALLOWED_EMAIL_DOMAINS") if d.strip()]

# --------------------------------------------------------------------------
# Localisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static & uploaded files
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Bills are private: MEDIA_ROOT is never served directly. Files will be
# streamed through a permission-checked view.
MEDIA_ROOT = _path(env("MEDIA_ROOT", default="media"))
MEDIA_URL = "/media/"

# Reject request bodies larger than this (bulk uploads included).
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------
SECURE_COOKIES = env("SECURE_COOKIES")
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 8  # one working day
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if SECURE_COOKIES:
    # Nginx terminates HTTPS and passes this header on.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --------------------------------------------------------------------------
# Portal
# --------------------------------------------------------------------------
PORTAL_NAME = "Asset & Purchase Portal"
DEPARTMENT_NAME = env("DEPARTMENT_NAME", default="Department")
