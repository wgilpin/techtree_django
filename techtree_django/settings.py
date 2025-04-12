"""
Django settings for techtree_django project.

Generated by 'django-admin startproject' using Django 5.2.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path

import environ  # Import environ


# Initialize environ
env = environ.Env(
    # set casting, default value
    DEBUG=(bool, False)
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Take environment variables from .env file
environ.Env.read_env(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Raises Django's ImproperlyConfigured exception if SECRET_KEY not in os.environ
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
# False if not in os.environ, otherwise raises ImproperlyConfigured
DEBUG = env('DEBUG')

ALLOWED_HOSTS: list[str] = []


# Application definition

INSTALLED_APPS = [
    # Local apps first to override templates
    "core.apps.CoreConfig",
    "onboarding.apps.OnboardingConfig",
    "syllabus.apps.SyllabusConfig",
    "lessons.apps.LessonsConfig",
    "background_task",
    "taskqueue",

    # Django contrib apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "techtree_django.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Removed reference to old Flask templates dir. Templates are now in app dirs.
        "DIRS": [],
        "APP_DIRS": True, # Looks for templates in core/templates/, etc.
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "techtree_django.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/


# API Keys and Model Config from .env
GEMINI_API_KEY = env('GEMINI_API_KEY', default=None)
# Use specific model names from .env
FAST_MODEL = env('FAST_MODEL', default=None) # For onboarding, chat, etc.
LARGE_MODEL = env('LARGE_MODEL', default=None) # For generation tasks


# Logging Configuration
# https://docs.djangoproject.com/en/5.2/topics/logging/
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG', # Changed from INFO to DEBUG
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': BASE_DIR / 'techtree_django.log',
            'when': 'D',
            'interval': 1,
            'backupCount': 7,
            'formatter': 'standard',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        '': { # Root logger
            'handlers': ['console', 'file'],
            'level': 'DEBUG', # Reverted back to DEBUG
            'propagate': True,
        },
        'asyncio': {
            'handlers': ['file'],
            'level': 'WARNING',      # Set the desired level here
            'propagate': False,
        },
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'MARKDOWN': { # Changed case to match log output
            'handlers': ['console', 'file'],
            'level': 'INFO', # Set level to INFO to ignore DEBUG messages
            'propagate': False,
        },
        'urllib3.connectionpool': {
            'handlers': ['console', 'file'],
            'level': 'WARNING', # Set to WARNING to prevent DEBUG logs to LangSmith
            'propagate': False,
        },
        'httpcore': {
            'handlers': ['file'],
            'level': 'ERROR',      # Set the desired level here
            'propagate': False,
        },
        'background_task.management.commands.process_tasks': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}


# Onboarding Assessment Settings
ONBOARDING_DEFAULT_DIFFICULTY = 2 # Example: Scale 1-5
ONBOARDING_HARD_DIFFICULTY_THRESHOLD = 3 # Match constants.py (Advanced=3)
ASSESSMENT_STATE_KEY = 'assessment_state' # Session key

TAVILY_API_KEY = env('TAVILY_API_KEY', default=None)


STATIC_URL = "static/"

# Directories where Django will look for static files in addition to app 'static/' dirs
STATICFILES_DIRS = [
    BASE_DIR / "static", # Point to the project's root static directory
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Default URL to redirect to after successful login
LOGIN_REDIRECT_URL = 'dashboard'
# Django Background Tasks settings
MAX_ATTEMPTS = 3  # Number of times a task will be attempted
MAX_RUN_TIME = 3600  # Maximum running time in seconds (1 hour)
BACKGROUND_TASK_RUN_ASYNC = False  # Run tasks synchronously in the worker

# Fine-tuned worker process settings
BACKGROUND_TASK_ASYNC_THREADS = 4  # Number of async threads
BACKGROUND_TASK_PRIORITY_ORDERING = "-priority"  # Order tasks by priority (highest first)
BACKGROUND_TASK_QUEUE_LIMIT = 50  # Maximum number of tasks to process in one batch
BACKGROUND_TASK_SLEEP_SECONDS = 5.0  # Time to sleep between task queue polling

# Task queue monitoring
BACKGROUND_TASK_METRICS_INTERVAL = 15  # Minutes between metrics logging
BACKGROUND_TASK_METRICS_ENABLED = True  # Enable metrics collection

