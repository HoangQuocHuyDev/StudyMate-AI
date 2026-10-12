"""Security-focused tests for the API CORS policy."""

import pytest


ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_preflight_allows_configured_frontend_origins(client, origin: str) -> None:
    response = client.options(
        "/auth/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "true" != response.headers.get("access-control-allow-credentials")


def test_preflight_exposes_only_required_http_methods(client) -> None:
    response = client.options(
        "/auth/register",
        headers={
            "Origin": ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "POST",
        },
    )

    allowed_methods = {
        method.strip()
        for method in response.headers["access-control-allow-methods"].split(",")
    }

    assert response.status_code == 200
    assert allowed_methods == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def test_disallowed_origin_does_not_receive_allow_origin_header(client) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_disallowed_preflight_is_rejected_without_allow_origin_header(client) -> None:
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
