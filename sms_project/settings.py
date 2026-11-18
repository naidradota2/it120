"""
Django settings for sms_project.

Secrets and environment-specific values are read from environment variables,
loaded from a local `.env` file (never committed). See `.env.example`.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from .env into the environment (does not override real env vars).
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# --- Core security -----------------------------------------------------------

DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        # Development fallback only. A real key must be set when DEBUG is off.
        SECRET_KEY = 'dev-only-insecure-key-change-me'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False.')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool('DJANGO_SECURE_COOKIES', True)
    CSRF_COOKIE_SECURE = env_bool('DJANGO_SECURE_COOKIES', True)


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'sms_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sms_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'sms_app.context_processors.sms_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'sms_project.wsgi.application'


# --- Database ----------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# --- Authentication ----------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'sms_app:compose'
LOGOUT_REDIRECT_URL = 'login'


# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True


# --- Static files ------------------------------------------------------------

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'


# --- Messages framework: map to Bootstrap alert classes ------------------------

from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.DEBUG: 'secondary',
    message_constants.INFO: 'info',
    message_constants.SUCCESS: 'success',
    message_constants.WARNING: 'warning',
    message_constants.ERROR: 'danger',
}


# --- SMS provider ------------------------------------------------------------
# SMS_PROVIDER: "textbee" sends real SMS through the textbee.dev gateway.
#               "console" is a test mode: nothing is sent, the message is logged.

SMS_PROVIDER = os.getenv('SMS_PROVIDER', 'console').strip().lower()
SMS_REQUEST_TIMEOUT = float(os.getenv('SMS_REQUEST_TIMEOUT', '15'))
SMS_DEFAULT_COUNTRY_CODE = os.getenv('SMS_DEFAULT_COUNTRY_CODE', '63')

TEXTBEE_API_KEY = os.getenv('TEXTBEE_API_KEY', '')
TEXTBEE_DEVICE_ID = os.getenv('TEXTBEE_DEVICE_ID', '')
TEXTBEE_BASE_URL = os.getenv('TEXTBEE_BASE_URL', 'https://api.textbee.dev/api/v1')


# --- Logging -----------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {
        'sms_app': {'handlers': ['console'], 'level': 'INFO'},
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Development: print emails to the console.
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
