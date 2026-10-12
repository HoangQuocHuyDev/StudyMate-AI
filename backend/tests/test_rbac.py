"""Tests for reusable USER/ADMIN role dependencies."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token
from app.dependencies.auth import require_roles
from app.models.user import User


rbac_app = FastAPI()


@rbac_app.get("/user-only")
def user_only(user: Annotated[User, Depends(require_roles("USER"))]):
    return {"role": user.role}


@rbac_app.get("/user-or-admin")
def user_or_admin(
    user: Annotated[User, Depends(require_roles("USER", "ADMIN"))],
):
    return {"role": user.role}


@rbac_app.get("/admin-only")
def admin_only(user: Annotated[User, Depends(require_roles("ADMIN"))]):
    return {"role": user.role}


@pytest.fixture
def rbac_client():
    with TestClient(rbac_app) as test_client:
        yield test_client
    rbac_app.dependency_overrides.clear()


def test_user_can_access_user_endpoint(
    rbac_client,
    override_db,
    fake_session_factory,
    active_user,
) -> None:
    override_db(fake_session_factory(get_result=active_user), rbac_app)
    token = create_access_token(active_user.id)

    response = rbac_client.get(
        "/user-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_admin_can_access_allowed_and_admin_endpoints(
    rbac_client,
    override_db,
    fake_session_factory,
    user_factory,
) -> None:
    admin = user_factory(user_id=7, username="admin_user", role="ADMIN")
    override_db(fake_session_factory(get_result=admin), rbac_app)
    token = create_access_token(admin.id)

    assert rbac_client.get(
        "/user-or-admin",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200
    assert rbac_client.get(
        "/admin-only",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200


def test_user_cannot_access_admin_endpoint(
    rbac_client,
    override_db,
    fake_session_factory,
    active_user,
) -> None:
    override_db(fake_session_factory(get_result=active_user), rbac_app)
    token = create_access_token(active_user.id)

    response = rbac_client.get(
        "/admin-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_rbac_without_or_with_invalid_token_returns_401(
    rbac_client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(), rbac_app)

    assert rbac_client.get("/user-only").status_code == 401
    assert rbac_client.get(
        "/user-only",
        headers={"Authorization": "Bearer invalid-token"},
    ).status_code == 401


def test_rbac_rejects_inactive_account(
    rbac_client,
    override_db,
    fake_session_factory,
    user_factory,
) -> None:
    inactive = user_factory(is_active=False)
    override_db(fake_session_factory(get_result=inactive), rbac_app)
    token = create_access_token(inactive.id)

    response = rbac_client.get(
        "/user-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_role_claim_cannot_escalate_database_role(
    rbac_client,
    override_db,
    fake_session_factory,
    active_user,
) -> None:
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    now = datetime.now(timezone.utc)
    forged_token = jwt.encode(
        {
            "sub": str(active_user.id),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "type": "access",
            "role": "ADMIN",
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    override_db(fake_session_factory(get_result=active_user), rbac_app)

    response = rbac_client.get(
        "/admin-only",
        headers={"Authorization": f"Bearer {forged_token}"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("roles", [(), ("EDITOR",), ("admin",), (None,)])
def test_invalid_allowed_roles_are_rejected(roles) -> None:
    with pytest.raises(ValueError):
        require_roles(*roles)
