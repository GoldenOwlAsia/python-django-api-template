from .base import *

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

DEBUG = os.getenv("DEBUG", True)

STATIC_ROOT = os.path.join(BASE_DIR, "static_root")

# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_DEV_NAME", "dev_db"),
        "USER": os.getenv("DB_DEV_USER", "postgres"),
        "PASSWORD": os.getenv("DB_DEV_PASSWORD", ""),
        "HOST": os.getenv("DB_DEV_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_DEV_PORT", "5432"),
    }
}

if DEBUG:
    try:
        import debug_toolbar  # NOQA
    except ImportError:
        pass
    else:
        INSTALLED_APPS.append("debug_toolbar")
        INTERNAL_IPS = ["127.0.0.1"]
        MIDDLEWARE.insert(
            MIDDLEWARE.index("django.middleware.common.CommonMiddleware") + 1,
            "debug_toolbar.middleware.DebugToolbarMiddleware",
        )

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            'datefmt': "%d/%b/%Y %H:%M:%S"
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard'
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'propagate': True,
            'level': 'INFO',
        },
    }
}
