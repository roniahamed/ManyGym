import pytest
from rest_framework.test import APIClient
from django.urls import reverse


@pytest.mark.django_db
def test_health_check_endpoint():
    client = APIClient()
    url = reverse("common:health-check")
    response = client.get(url)

    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "components" in data
    assert "database" in data["components"]
    assert "redis_cache" in data["components"]


@pytest.mark.django_db
def test_openapi_schema_endpoint():
    client = APIClient()
    url = reverse("schema")
    response = client.get(url)

    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").startswith("application/vnd.oai.openapi") or "application/json" in response.headers.get("Content-Type", "")


@pytest.mark.django_db
def test_swagger_ui_endpoint():
    client = APIClient()
    url = reverse("swagger-ui")
    response = client.get(url)

    assert response.status_code == 200
