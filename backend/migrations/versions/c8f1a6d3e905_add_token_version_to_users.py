"""add_token_version_to_users

Revision ID: c8f1a6d3e905
Revises: b7d2e9f4c816
Create Date: 2026-10-13

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c8f1a6d3e905"
down_revision: str | Sequence[str] | None = "b7d2e9f4c816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the non-negative user token generation used for revocation."""

    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_token_version_nonnegative",
        "users",
        "token_version >= 0",
    )


def downgrade() -> None:
    """Remove only the token revocation generation."""

    op.drop_constraint(
        "ck_users_token_version_nonnegative",
        "users",
        type_="check",
    )
    op.drop_column("users", "token_version")
