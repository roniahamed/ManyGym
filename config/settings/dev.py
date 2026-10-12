from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True

# Development email backend (prints to console)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
