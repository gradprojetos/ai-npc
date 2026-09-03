"""Create the Usuario and NPC tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_create_usuario_npc"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "usuario",
        sa.Column(
            "id_usuario",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            nullable=True,
            unique=True,
            index=True,
        ),
        sa.Column("nome", sa.String(length=255), nullable=False),
        # sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "data_criacao",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_usuario"),
        # sa.UniqueConstraint("email"),
    )
    op.create_table(
        "npc",
        sa.Column(
            "id_npc",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("objetivo_pedagogico", sa.Text(), nullable=False),
        sa.Column(
            "metadata_npc",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_npc"),
    )


def downgrade() -> None:
    op.drop_table("npc")
    op.drop_table("usuario")
