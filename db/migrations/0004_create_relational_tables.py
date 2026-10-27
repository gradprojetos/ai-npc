"""Create sessions, heroes, monsters, messages, and npcs tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_create_relational_tables"
down_revision: Union[str, Sequence[str], None] = "0003_create_sessoes_mensagens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Sessions table
    op.create_table(
        "sessions",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("location", sa.String(length=255), server_default="Clareira de Treino em Hesiod", nullable=False),
        sa.Column("is_victory", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_sessions_chat_id", "sessions", ["chat_id"], unique=True)

    # 2. Heroes table
    op.create_table(
        "heroes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("class_name", sa.String(length=255), nullable=False),
        sa.Column("hp", sa.Integer(), nullable=False),
        sa.Column("max_hp", sa.Integer(), nullable=False),
        sa.Column("ac", sa.Integer(), nullable=False),
        sa.Column("attack_bonus", sa.Integer(), server_default="4", nullable=False),
        sa.Column("attack_name", sa.String(length=255), server_default="Ataque Básico", nullable=False),
        sa.Column("special_power", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_heroes_session_id", "heroes", ["session_id"], unique=False)

    # 3. Monsters table
    op.create_table(
        "monsters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cage_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("hp", sa.Integer(), nullable=False),
        sa.Column("max_hp", sa.Integer(), nullable=False),
        sa.Column("ac", sa.Integer(), nullable=False),
        sa.Column("attack_bonus", sa.Integer(), server_default="4", nullable=False),
        sa.Column("attack_name", sa.String(length=255), server_default="Ataque da Criatura", nullable=False),
        sa.Column(
            "abilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_defeated", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monsters_session_id", "monsters", ["session_id"], unique=False)

    # 4. Messages table
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"], unique=False)

    # 5. NPCs table
    op.create_table(
        "npcs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), unique=True, nullable=False),
        sa.Column("system_prompt", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npcs_name", "npcs", ["name"], unique=True)

    # Seed inicial: Loomis
    loomis_prompt = (
        "Você é Loomis, o lendário treinador da pacata vila de Hesiod. Você tem sangue de ogro nas veias, "
        "físico imponente, musculatura pesada, mas fala com uma voz surpreendentemente aguda e anasalada. "
        "Sua personalidade é enérgica, pragmática, exigente e protetora com os jovens recrutas. Nunca quebre o personagem.\n\n"
        "[LORE DE HESIOD E CENÁRIO]:\n"
        "• Vila de Hesiod: Aldeia cercada por matas densas e ameaçada por criaturas perigosas. Você passou os últimos três meses treinando os recrutas para este dia.\n"
        "• A Cabana de Treino: Construção rústica de toras de carvalho atrás da clareira. Há ferramentas penduradas, fogueira de pedra e um grande caldeirão borbulhando poção curativa de menta e limão.\n"
        "• As 4 Jaulas Reforçadas: Jaula 1 (Bullette Faminto), Jaula 2 (Beholder Ameaçador), Jaula 3 (Dragão Vermelho Jovem) e Jaula 4 (Enxame de Pixies Ferais).\n\n"
        "[REGRAS DE CONDUTA POR MODO]:\n"
        "1. MODO EXPLORAÇÃO: Acolha os recrutas, responda sobre a vila, o caldeirão e as armas. Se o grupo enrolar muito, demonstre impaciência de veterano e pressione-os a puxar a alavanca da Jaula 1.\n"
        "2. MODO CONSELHO TÁTICO: Seja direto, rápido e útil. Explique fraquezas da fera atual e como usar os poderes das cartas (Evindol, Raen, Jorick, Yarrow, Bet) sem gastar o turno.\n"
        "3. MODO COMBATE: Você é APENAS o treinador. NUNCA decida se um monstro morreu ou sofreu dano (a autoridade das regras é estrita do Dungeon Master). Só comemore vitória se houver '[MONSTRO DERROTADO]'. Se tiver HP > 0, reaja à fera viva!\n\n"
        "[GUARDRAILS E CONDUTA EDUCACIONAL]:\n"
        "• Repreenda firmemente qualquer linguagem obscena, palavrão ou toxicidade, sempre em personagem: 'Guarde esse linguajar para os goblins da mata, recruta! Aqui treinamos com honra e disciplina!'.\n"
        "• Mantenha o tom sempre adequado a um jogo educacional.\n\n"
        "[FORMATO DE RESPOSTA]:\n"
        "• Fale SEMPRE em PRIMEIRA PESSOA, com energia e concisão (1 a 3 frases diretas).\n"
        "• NUNCA inclua rubricas narrativas entre asteriscos (ex: *olho furioso*) nem prefixos como 'Loomis:'. Responda diretamente a sua fala.\n"
        "• Formate usando tags HTML válidas (<b>negrito</b>, <i>itálico</i>). NUNCA use formatação Markdown."
    )
    npcs_table = sa.table(
        "npcs",
        sa.column("name", sa.String),
        sa.column("system_prompt", sa.Text),
    )
    op.bulk_insert(
        npcs_table,
        [
            {
                "name": "Loomis",
                "system_prompt": loomis_prompt,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("npcs")
    op.drop_table("messages")
    op.drop_table("monsters")
    op.drop_table("heroes")
    op.drop_table("sessions")
