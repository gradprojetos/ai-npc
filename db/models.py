from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=True,
    )
    location: Mapped[str] = mapped_column(
        String(255),
        default="Clareira de Treino em Hesiod",
        nullable=False,
    )
    is_victory: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    heroes: Mapped[list["Hero"]] = relationship(
        "Hero",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    monsters: Mapped[list["Monster"]] = relationship(
        "Monster",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Hero(Base):
    __tablename__ = "heroes"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    ac: Mapped[int] = mapped_column(Integer, nullable=False)
    attack_bonus: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    attack_name: Mapped[str] = mapped_column(String(255), default="Ataque Básico", nullable=False)
    special_power: Mapped[str] = mapped_column(Text, default="", nullable=False)

    session: Mapped["Session"] = relationship("Session", back_populates="heroes")


class Monster(Base):
    __tablename__ = "monsters"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cage_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    max_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    ac: Mapped[int] = mapped_column(Integer, nullable=False)
    attack_bonus: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    attack_name: Mapped[str] = mapped_column(String(255), default="Ataque da Criatura", nullable=False)
    abilities: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    is_defeated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    session: Mapped["Session"] = relationship("Session", back_populates="monsters")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    session: Mapped["Session"] = relationship("Session", back_populates="messages")


class NPC(Base):
    __tablename__ = "npcs"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)


# Model aliases
SessionModel = Session
HeroModel = Hero
MonsterModel = Monster
MessageModel = Message
NPCModel = NPC

# Backward compatibility aliases
SessaoJogo = Session
HeroiSessao = Hero
MonstroSessao = Monster
HistoricoMensagens = Message
