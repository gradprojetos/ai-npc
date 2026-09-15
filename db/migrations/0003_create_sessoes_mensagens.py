"""Create game sessions, session state, and message history tables."""

from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_create_sessoes_mensagens"
down_revision: Union[str, Sequence[str], None] = "0002_create_usuario_npc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "sessao_jogo",
        sa.Column(
            "id_sessao",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("id_usuario", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id_usuario"], ["usuario.id_usuario"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_sessao"),
    )
    op.create_table(
        "estado_sessao",
        sa.Column("id_sessao", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "variaveis_jogo",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "progresso_pedagogico",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ultima_atualizacao",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id_sessao"], ["sessao_jogo.id_sessao"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_sessao"),
    )
    op.create_table(
        "historico_mensagens",
        sa.Column(
            "id_mensagem",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("id_sessao", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("remetente", sa.String(length=50), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id_sessao"], ["sessao_jogo.id_sessao"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id_mensagem"),
    )


def downgrade() -> None:
    op.drop_table("historico_mensagens")
    op.drop_table("estado_sessao")
    op.drop_table("sessao_jogo")
