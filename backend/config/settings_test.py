"""Settings for the automated test suite (pytest and CI). Never use in production."""

from .settings import *  # noqa: F403

SECRET_KEY = "test-only-secret-key"  # noqa: S105
DEBUG = False
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast hashing in tests
# Tests check production behaviour, whatever DJANGO_DEBUG says in a local .env.
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,  # noqa: F405
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
