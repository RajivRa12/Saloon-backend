from pathlib import Path
import os
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INSECURE_SECRET = 'django-insecure-gcaz)x)()re4ubw+)qro1wx_ymnk%cx(&2=h2pbs$4y92v=qg^'
SECRET_KEY = os.environ.get('SECRET_KEY', DEFAULT_INSECURE_SECRET)
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')
DEBUG = os.environ.get('DEBUG', 'True' if ENVIRONMENT == 'development' else 'False').lower() in ('true', '1', 'yes')

if not DEBUG and SECRET_KEY == DEFAULT_INSECURE_SECRET:
    import warnings
    warnings.warn(
        "CRITICAL SECURITY ALERT: Running in production with the default template SECRET_KEY! "
        "Define SECRET_KEY in your production environment variables to protect JWT token signing.",
        RuntimeWarning
    )
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '*').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    'https://api.sancharitribe.com',
    'https://web.sancharitribe.com',
    'https://store.sancharitribe.com',
    'https://sancharitribe.com',
    'https://os44ok800w8kkkkks4wwcs0s.93.127.185.74.sslip.io',
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1:8000',
    'http://localhost:8000',
]
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
MESSAGE_CENTRAL_CUSTOMER_ID = os.environ.get('MESSAGE_CENTRAL_CUSTOMER_ID', '')
MESSAGE_CENTRAL_AUTH_TOKEN = os.environ.get('MESSAGE_CENTRAL_AUTH_TOKEN', '')
MESSAGE_CENTRAL_SENDER_ID = os.environ.get('MESSAGE_CENTRAL_SENDER_ID', 'NRBYME')
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'django_filters',
    'apps.core',
    'apps.authentication',
    'apps.master_admin',
    'apps.store_erp',
    'apps.customers',
    'apps.staff',
    'apps.therapist_app',
]
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
WSGI_APPLICATION = 'config.wsgi.application'
import os
import urllib.parse
db_url = os.environ.get('DATABASE_URL')
if db_url:
    url = urllib.parse.urlparse(db_url)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': url.path[1:],
            'USER': url.username,
            'PASSWORD': url.password,
            'HOST': url.hostname,
            'PORT': url.port or '5432',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'nearbyme'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASS', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }

if 'test' in sys.argv and not os.environ.get('USE_POSTGRES_TEST_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
JAZZMIN_SETTINGS = {
    "site_title": "Nearbyme Admin",
    "site_header": "Nearbyme",
    "site_brand": "Nearbyme ERP",
    "welcome_sign": "Welcome to Nearbyme Staff & ERP Admin",
    "copyright": "Nearbyme Inc",
    "search_model": ["core.User", "core.Store"],
    "show_ui_builder": False,
    "custom_css": "css/custom_admin.css",
    "topmenu_links": [
        {"name": "Home",  "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "core.User"},
    ],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "core.Store": "fas fa-store",
        "core.Service": "fas fa-cut",
        "core.Appointment": "fas fa-calendar-check",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
}
JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "navbar": "navbar-dark",
}
AUTH_USER_MODEL = 'core.User'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '120/minute',
        'user': '600/minute',
        'auth': '20/minute',
        'otp': '5/minute',
    },
}
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'UPDATE_LAST_LOGIN': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    'JTI_CLAIM': 'jti',
}
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    'https://sancharitribe.com',
    'https://web.sancharitribe.com',
    'https://api.sancharitribe.com',
    'https://store.sancharitribe.com',
    'https://os44ok800w8kkkkks4wwcs0s.93.127.185.74.sslip.io',
    'http://localhost:3000',
    'http://localhost:8080',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8080',
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.sancharitribe\.com$",
    r"^https://.*\.vercel\.app$",
]
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + ['x-store-id', 'x-impersonation-token']
import os
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
BOOKING_AUTO_ASSIGN_STRATEGY = 'fewest_bookings_today'
BOOKING_OVERRIDE_TOKEN_MAX_AGE_SECONDS = 600
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# Reverse Proxy SSL & Security Headers
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False

if not DEBUG:
    # Reverse proxy (Nginx / Cloudflare / Coolify) handles SSL termination & HTTPS redirect
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

