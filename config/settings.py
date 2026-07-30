"""
Django settings for config project.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# Lee variables desde .env si existe (no se versiona, ver .env.example)
environ.Env.read_env(BASE_DIR / ".env")


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-change-me-in-.env",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core',
    'analytics',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# Por defecto usa SQLite para levantar el proyecto sin dependencias externas.
# En staging/producción, define DATABASE_URL en .env, por ejemplo:
# DATABASE_URL=postgres://f1user:f1pass@localhost:5432/f1
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

# CORS: útil para el frontend (React) planeado en el roadmap.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

# FastF1 cache local (ignorado en git, ver .gitignore)
FASTF1_CACHE_DIR = env("FASTF1_CACHE_DIR", default=str(BASE_DIR / "cache"))

# Corrección de combustible usada por analytics/modules/pace_adjusted.py:
# segundos por vuelta que el auto "gana" por menor carga de combustible
# (se suma al lap_time real para neutralizar ese efecto). Configurable sin
# tocar código.
FUEL_CORRECTION_PER_LAP = env.float("FUEL_CORRECTION_PER_LAP", default=0.035)


# Logging
# Sin esta config, cualquier logging.getLogger(__name__) de nuestro código
# (core, analytics, dashboard) sube por la jerarquía hasta el logger raíz,
# que por defecto no tiene ningún handler -> los mensajes se descartan en
# silencio. Los únicos logs que se veían antes eran los de FastF1, que
# configura su propio handler de forma interna, independiente de esto.
#
# Nota: FastF1 nombra sus propios loggers con nombres cortos como "core" o
# "req" (no "fastf1.core"). Nuestra app Django "core" también termina
# propagando a través de un logger llamado "core" (por jerarquía, ya que
# "core.services.traffic" es hijo de "core"). No es un problema: en el peor
# caso, los logs internos de FastF1 también pasan por nuestro handler/nivel,
# lo cual es inofensivo.
DJANGO_LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="DEBUG" if DEBUG else "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname:<8} {name} - {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    # Root logger: captura todo lo que no tenga un logger más específico
    # configurado explícitamente (core, core.services.traffic, analytics,
    # dashboard, etc. propagan hasta acá).
    "root": {
        "handlers": ["console"],
        "level": DJANGO_LOG_LEVEL,
    },
    "loggers": {
        # Se define aparte con propagate=False para que los logs de Django
        # no se dupliquen (una vez por su propio manejo, otra vez por el
        # root logger de arriba).
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}