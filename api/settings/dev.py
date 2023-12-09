from .base import *

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

DEBUG = True

STATIC_ROOT = os.path.join(BASE_DIR, 'static_root')

# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_DEV_NAME', 'baron'),
        'USER': os.getenv('DB_DEV_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_DEV_PASSWORD', ''),
        'HOST': os.getenv('DB_DEV_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_DEV_PORT', '5432'),
    }
}
