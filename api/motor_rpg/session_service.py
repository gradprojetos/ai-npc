import logging
import uuid
from datetime import datetime, timezone

from api.schemas.rpg import (
    HeroState,
    MonsterState,
    NPCState,
    GameState,
    Message,
)
from api.motor_rpg.motor_rpg import (
    create_hero,
    get_cage_monster,
)
from db.models import Session, Hero, Monster, Message as MessageDB, NPC
from db.session import SessionLocal

logger = logging.getLogger(__name__)

# Fallback em memória para execução rápida ou ambiente de testes/desconectado
_MEMORY_SESSIONS: dict[str, GameState] = {}


def get_memory_session(session_id: str) -> GameState | None:
    """Recupera o estado em memória para uma sessão."""
    return _MEMORY_SESSIONS.get(session_id)


def set_memory_session(session_id: str, state: GameState) -> None:
    """Salva o estado em memória para uma sessão."""
    _MEMORY_SESSIONS[session_id] = state


def clear_memory_session(session_id: str) -> None:
    """Remove a sessão do armazenamento em memória."""
    _MEMORY_SESSIONS.pop(session_id, None)


def create_initial_rpg_state(
    session_id: str,
    initial_hero: HeroState | None = None,
    npc_prompt: str | None = None,
) -> GameState:
    """Cria um novo estado do jogo com a Jaula 1 ativa e Loomis como treinador."""
    cage_1_monster = get_cage_monster(1)
    players = [initial_hero] if initial_hero else []

    system_prompt = npc_prompt or ""
    if not system_prompt:
        try:
            with SessionLocal() as db:
                db_npc = db.query(NPC).filter_by(name="Loomis").first()
                if db_npc:
                    system_prompt = db_npc.system_prompt
        except Exception:
            pass

    state = GameState(
        session_id=session_id,
        location="Clareira de Treino em Hesiod",
        players=players,
        monsters=[cage_1_monster],
        npcs=[NPCState(name="Loomis", system_prompt=system_prompt)],
        last_context=None,
        recent_messages=[],
        is_victory=False,
    )
    set_memory_session(session_id, state)
    return state


def add_or_update_player(
    state: GameState,
    player_id: str,
    hero_archetype_or_name: str,
) -> HeroState:
    """Adiciona um novo herói ao grupo ou atualiza o personagem de um jogador existente."""
    hero = create_hero(hero_archetype_or_name, player_id=player_id)
    existing_index = next(
        (i for i, p in enumerate(state.players) if p.player_id == player_id),
        None,
    )
    if existing_index is not None:
        state.players[existing_index] = hero
    else:
        state.players.append(hero)

    return hero





def resolve_session_uuid(session_id: str) -> uuid.UUID:
    """Garante um UUID válido para chaves primárias do PostgreSQL."""
    try:
        return uuid.UUID(session_id)
    except (ValueError, TypeError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(session_id))


def get_or_create_session_state(
    session_id: str,
    user_info: dict | None = None,
    default_archetype: str | None = None,
) -> GameState:
    """Recupera o GameState do PostgreSQL ou da memória, ou cria uma nova partida."""
    session_uuid = resolve_session_uuid(session_id)
    chat_id_int = None
    if user_info and user_info.get("chat_id") is not None:
        try:
            chat_id_int = int(user_info["chat_id"])
        except (ValueError, TypeError):
            pass
    elif str(session_id).lstrip("-").isdigit():
        try:
            chat_id_int = int(session_id)
        except (ValueError, TypeError):
            pass

    # 1. Tenta carregar do banco de dados relacional normalizado
    try:
        with SessionLocal() as db:
            session_db = None
            if chat_id_int is not None:
                session_db = db.query(Session).filter_by(chat_id=chat_id_int).first()
            if not session_db:
                session_db = db.query(Session).filter_by(session_id=session_uuid).first()

            if session_db:
                # Carrega heróis da sessão
                db_heroes = db.query(Hero).filter_by(session_id=session_db.session_id).all()
                players = [
                    HeroState(
                        player_id=h.player_id,
                        name=h.name,
                        class_name=h.class_name,
                        hp=h.hp,
                        max_hp=h.max_hp,
                        ac=h.ac,
                        attack_bonus=h.attack_bonus,
                        attack_name=h.attack_name,
                        special_power=h.special_power,
                    )
                    for h in db_heroes
                ]

                # Carrega monstros da sessão
                db_monsters = db.query(Monster).filter_by(session_id=session_db.session_id).all()
                monsters = [
                    MonsterState(
                        name=m.name,
                        cage_number=m.cage_number,
                        hp=m.hp,
                        max_hp=m.max_hp,
                        ac=m.ac,
                        attack_bonus=m.attack_bonus,
                        attack_name=m.attack_name,
                        abilities=m.abilities or [],
                        is_defeated=m.is_defeated,
                    )
                    for m in db_monsters
                ]

                # Carrega mensagens recentes
                db_messages = (
                    db.query(MessageDB)
                    .filter_by(session_id=session_db.session_id)
                    .order_by(MessageDB.timestamp.desc())
                    .limit(5)
                    .all()
                )
                recent_messages = [
                    Message(
                        sender=msg.sender,
                        role=msg.role,  # type: ignore
                        content=msg.content,
                        timestamp=msg.timestamp.isoformat() if msg.timestamp else None,
                    )
                    for msg in reversed(db_messages)
                ]

                # Carrega persona do Loomis de npcs se existir
                db_npc = db.query(NPC).filter_by(name="Loomis").first()
                system_prompt = db_npc.system_prompt if db_npc else ""

                state = GameState(
                    session_id=str(session_db.session_id),
                    location=session_db.location,
                    players=players,
                    monsters=monsters if monsters else [get_cage_monster(1)],
                    npcs=[NPCState(name="Loomis", system_prompt=system_prompt)],
                    last_context=None,
                    recent_messages=recent_messages,
                    is_victory=session_db.is_victory,
                )
                set_memory_session(session_id, state)
                set_memory_session(str(session_db.session_id), state)
                return state
    except Exception as e:
        logger.debug(f"Acesso ao banco ignorado ou indisponível ao carregar session_id={session_id}: {e}")

    # 2. Tenta recuperar da memória
    cached = get_memory_session(session_id)
    if not cached and str(session_uuid) != session_id:
        cached = get_memory_session(str(session_uuid))
    if cached:
        return cached

    # 3. Cria nova sessão inicial
    player_id = str(user_info.get("player_id") or chat_id_int or "player_1") if user_info else "player_1"
    archetype = default_archetype or (user_info.get("archetype") if user_info else None) or "Jorick"

    initial_hero = create_hero(archetype, player_id=player_id)
    new_state = create_initial_rpg_state(session_id=session_id, initial_hero=initial_hero)

    # Tenta persistir no banco relacional
    persist_session_state_to_db(new_state, chat_id=chat_id_int)
    return new_state


def persist_session_state_to_db(state: GameState, chat_id: int | None = None) -> bool:
    """Persiste o GameState nas tabelas relacionais explícitas (sessions, heroes, monsters, messages)."""
    try:
        session_uuid = resolve_session_uuid(state.session_id)
        chat_id_int = chat_id
        if chat_id_int is None and str(state.session_id).lstrip("-").isdigit():
            try:
                chat_id_int = int(state.session_id)
            except (ValueError, TypeError):
                pass

        with SessionLocal() as db:
            # 1. Atualiza ou insere session
            session_record = None
            if chat_id_int is not None:
                session_record = db.query(Session).filter_by(chat_id=chat_id_int).first()
            if not session_record:
                session_record = db.query(Session).filter_by(session_id=session_uuid).first()

            if not session_record:
                session_record = Session(
                    session_id=session_uuid,
                    chat_id=chat_id_int,
                    location=state.location,
                    is_victory=state.is_victory,
                )
                db.add(session_record)
            else:
                session_record.location = state.location
                session_record.is_victory = state.is_victory
                if chat_id_int is not None:
                    session_record.chat_id = chat_id_int

            # 2. Atualiza ou insere heroes
            for hero in state.players:
                db_hero = db.query(Hero).filter_by(session_id=session_record.session_id, player_id=hero.player_id).first()
                if not db_hero:
                    db_hero = Hero(
                        session_id=session_record.session_id,
                        player_id=hero.player_id,
                        name=hero.name,
                        class_name=hero.class_name,
                        hp=hero.hp,
                        max_hp=hero.max_hp,
                        ac=hero.ac,
                        attack_bonus=hero.attack_bonus,
                        attack_name=hero.attack_name,
                        special_power=hero.special_power,
                    )
                    db.add(db_hero)
                else:
                    db_hero.name = hero.name
                    db_hero.class_name = hero.class_name
                    db_hero.hp = hero.hp
                    db_hero.max_hp = hero.max_hp
                    db_hero.ac = hero.ac
                    db_hero.attack_bonus = hero.attack_bonus
                    db_hero.attack_name = hero.attack_name
                    db_hero.special_power = hero.special_power

            # 3. Atualiza ou insere monsters
            for monster in state.monsters:
                db_monster = db.query(Monster).filter_by(session_id=session_uuid, name=monster.name).first()
                if not db_monster:
                    db_monster = Monster(
                        session_id=session_uuid,
                        name=monster.name,
                        cage_number=monster.cage_number,
                        hp=monster.hp,
                        max_hp=monster.max_hp,
                        ac=monster.ac,
                        attack_bonus=monster.attack_bonus,
                        attack_name=monster.attack_name,
                        abilities=monster.abilities,
                        is_defeated=monster.is_defeated,
                    )
                    db.add(db_monster)
                else:
                    db_monster.hp = monster.hp
                    db_monster.max_hp = monster.max_hp
                    db_monster.ac = monster.ac
                    db_monster.attack_bonus = monster.attack_bonus
                    db_monster.attack_name = monster.attack_name
                    db_monster.abilities = monster.abilities
                    db_monster.is_defeated = monster.is_defeated

            # 4. Registra mensagens recentes não persistidas
            for msg in state.recent_messages[-3:]:
                db_msg = MessageDB(
                    session_id=session_record.session_id,
                    sender=msg.sender,
                    role=msg.role,
                    content=msg.content,
                )
                db.add(db_msg)

            db.commit()
            return True
    except Exception as e:
        logger.debug(f"Não foi possível persistir no banco para session_id={state.session_id}: {e}")
        return False


def reset_game_session(identifier: int | str) -> bool:
    """Apaga completamente a sessão do jogo (arena, monstros, todos os heróis e histórico) no banco e na memória."""
    logger.info(f"Resetando sessão completa de jogo para identifier={identifier}")
    cleared = False

    chat_id_int = None
    if str(identifier).lstrip("-").isdigit():
        try:
            chat_id_int = int(identifier)
        except (ValueError, TypeError):
            pass

    session_uuid = resolve_session_uuid(str(identifier))

    try:
        with SessionLocal() as db:
            sessions = []
            if chat_id_int is not None:
                sessions = db.query(Session).filter(
                    (Session.chat_id == chat_id_int) | (Session.session_id == session_uuid)
                ).all()
            else:
                sessions = db.query(Session).filter_by(session_id=session_uuid).all()

            for s in sessions:
                logger.info(f"Excluindo sessão {s.session_id} (chat_id={s.chat_id}) e seus relacionamentos do banco.")
                db.delete(s)
                cleared = True
            db.commit()
    except Exception as e:
        logger.warning(f"Erro ao resetar sessão no banco: {e}")

    # Limpa da memória todas as chaves associadas a essa sessão
    keys_to_clear = {str(identifier), str(session_uuid)}
    if chat_id_int is not None:
        keys_to_clear.add(str(chat_id_int))

    for k in keys_to_clear:
        clear_memory_session(k)

    for sid, state in list(_MEMORY_SESSIONS.items()):
        if sid in keys_to_clear or any(p.player_id in keys_to_clear for p in state.players):
            clear_memory_session(sid)
            cleared = True

    return cleared or True


# Mantém alias para compatibilidade com outros módulos e testes
reset_player_session = reset_game_session
