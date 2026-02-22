from .settings import *
import os
import dj_database_url


DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

# ---------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=600,  # persistent connections
        conn_health_checks=True,  # auto-reconnect on stale connections
    ),
}

# ---------------------------------------------------------------
# CACHE - Redis
# ---------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry_on_timeout": True,
        },
    }
}


# ---------------------------------------------------------------
# STATIC FILES - WhiteNoise
# ---------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[2:],
]

STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ---------------------------------------------------------------
# CLOUDINARY — Media Storage
# ---------------------------------------------------------------

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.environ["CLOUDINARY_CLOUD_NAME"],
    "API_KEY": os.environ["CLOUDINARY_API_KEY"],
    "API_SECRET": os.environ["CLOUDINARY_API_SECRET"],
    "SECURE": True,
}

DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# ---------------------------------------------------------------
# CORS
# ---------------------------------------------------------------

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "https://vantage-api.onrender.com",
]

# ---------------------------------------------------------------
# JWT — djangorestframework-simplejwt
# ---------------------------------------------------------------

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------
# SECURITY HEADERS
# ---------------------------------------------------------------

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {module} {process:d} {thread:d} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "django.db.backends": {
            "level": "WARNING",  # suppress query logs in prod
            "handlers": ["console"],
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------
# RATE LIMITING (django-ratelimit)
# Apply in views with @ratelimit(key='user', rate='100/m')
# ---------------------------------------------------------------

RATELIMIT_USE_CACHE = "default"
RATELIMIT_ENABLE = True
