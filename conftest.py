import sys
import pytest
from pathlib import Path
from django.conf import settings
from django.template.context import BaseContext

# Compatibility patch for Python 3.14+ where copy(super()) in BaseContext fails
if sys.version_info >= (3, 14):
    def _patched_base_context_copy(self):
        duplicate = object.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _patched_base_context_copy


@pytest.fixture(autouse=True, scope="session")
def configure_local_test_media(tmp_path_factory):
    """Ensure MEDIA_ROOT is writable during local test execution."""
    try:
        Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    except (PermissionError, FileNotFoundError, OSError):
        settings.MEDIA_ROOT = tmp_path_factory.mktemp("test_media")


@pytest.fixture(autouse=True)
def configure_in_memory_email(settings):
    """Ensure emails are sent in-memory during tests to prevent external network timeouts."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
