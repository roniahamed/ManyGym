from django.conf import settings
from config.celery import app as celery_app
from common.enums import UserStatus, TokenContextType, GymTypeEnum


def test_celery_configuration():
    assert celery_app.main == "manygym"
    assert "CELERY_BROKER_URL" in dir(settings)
    assert settings.CELERY_TIMEZONE == "UTC"


def test_database_settings():
    assert "default" in settings.DATABASES
    assert "ENGINE" in settings.DATABASES["default"]
    assert "NAME" in settings.DATABASES["default"]


def test_cache_settings():
    assert "default" in settings.CACHES
    assert "BACKEND" in settings.CACHES["default"]
    assert "LOCATION" in settings.CACHES["default"]


def test_common_enums():
    assert UserStatus.ACTIVE == "active"
    assert TokenContextType.GYM == "gym"
    assert TokenContextType.PERSONAL == "personal"
    assert GymTypeEnum.GENERAL_FITNESS == "general_fitness_gym"
