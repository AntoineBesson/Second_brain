"""add user_preferences table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-21 00:00:01.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column(
            "timezone",
            sa.Text(),
            nullable=False,
            server_default="Europe/Paris",
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
