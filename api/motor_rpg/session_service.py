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
    HERO_CARDS,
    CARD_BY_NAME,
    HERO_ARCHETYPES,
    get_hero_card_number,
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


def select_hero_for_player(
    session_id: str,
    player_id: str,
    player_name: str,
    choice: str | int,
) -> tuple[bool, str, GameState]:
    """Vincula um jogador a um dos 5 heróis canônicos e ordena a iniciativa no GameState."""
    state = get_or_create_session_state(session_id)

    raw = str(choice).strip().lower()
    card_num = None
    if raw.isdigit():
        card_num = int(raw)
    else:
        card_num = CARD_BY_NAME.get(raw)

    if not card_num or card_num not in HERO_CARDS:
        return False, "Escolha inválida! Digite um número de 1 a 5 (ex: <code>/select 1</code>).", state

    arch_key = HERO_CARDS[card_num]
    arch_data = HERO_ARCHETYPES[arch_key]
    arch_name = arch_data["name"]

    # Verifica se outro jogador no grupo já escolheu esse herói
    for p in state.players:
        if p.player_id != str(player_id) and arch_name.lower() in p.name.lower():
            return False, f"A carta #{card_num} <b>{arch_name}</b> já foi escolhida por outro recruta!", state

    # Cria a ficha do herói com nome do jogador
    hero = create_hero(arch_key, player_id=str(player_id), player_name=player_name)

    # Substitui se o mesmo jogador já tinha um herói escolhido
    existing_idx = next((i for i, p in enumerate(state.players) if p.player_id == str(player_id)), None)
    if existing_idx is not None:
        state.players[existing_idx] = hero
    else:
        # Se havia apenas o herói genérico inicial sem dono, substitui
        if len(state.players) == 1 and state.players[0].player_id in ["default", "player_1", ""]:
            state.players[0] = hero
        else:
            state.players.append(hero)

    # Ordena canonicamente a iniciativa (#1 a #5)
    state.players.sort(key=lambda h: get_hero_card_number(h.name))

    # Persiste na memória e no banco
    set_memory_session(session_id, state)
    persist_session_state_to_db(state)

    msg = (
        f"<b>Recruta Alistado!</b>\n"
        f"• Jogador: <b>{player_name}</b>\n"
        f"• Carta #{card_num}: <b>{arch_name}</b> ({hero.class_name})\n"
        f"• Vida: {hero.hp}/{hero.max_hp} | CA: {hero.ac} | Ataque: +{hero.attack_bonus} ({hero.attack_name})\n\n"
        f"<i>Quando todos tiverem escolhido, use <code>/done</code> para iniciar o combate!</i>"
    )
    return True, msg, state


def finish_recruiting_for_session(session_id: str) -> tuple[bool, str, GameState]:
    """Finaliza a fase de recrutamento (/done) e abre a arena para combate."""
    state = get_or_create_session_state(session_id)
    if not state.is_recruiting:
        return False, "O combate já foi iniciado!", state

    if not state.players:
        return False, "Nenhum recruta foi alistado ainda! Usem <code>/select &lt;1-5&gt;</code> antes de <code>/done</code>.", state

    state.is_recruiting = False
    set_memory_session(session_id, state)
    persist_session_state_to_db(state)

    first_hero = state.players[0]
    monster = state.monsters[0] if state.monsters else get_cage_monster(1)

    briefing = (
        "<b>Treinamento Iniciado — Jaula 1 Aberta!</b>\n\n"
        f"Loomis gira a manivela enferrujada e as grades sobem com um rangido metálico!\n"
        f"<b>{monster.name}</b> entra na arena rosnando [HP: {monster.hp}/{monster.max_hp} | CA: {monster.ac}].\n\n"
        f"<b>Ordem de Ação:</b>\n"
        + "\n".join(f"{i+1}. <b>{p.name}</b> ({p.class_name})" for i, p in enumerate(state.players))
        + f"\n\n👉 Vez de <b>{first_hero.name}</b>! Declare sua ação no chat (ex: <i>\"ataco com 17\"</i>) ou peça conselho ao Loomis."
    )
    return True, briefing, state


def normalize_session_id(identifier: int | str) -> tuple[int | None, uuid.UUID]:
    """Retorna chat_id_int (se numérico) e session_uuid consistente para o banco."""
    chat_id_int = None
    raw_str = str(identifier)
    if raw_str.lstrip("-").isdigit():
        try:
            chat_id_int = int(raw_str)
        except (ValueError, TypeError):
            pass

    try:
        session_uuid = uuid.UUID(raw_str)
    except (ValueError, TypeError, AttributeError):
        session_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, raw_str)

    return chat_id_int, session_uuid


def resolve_session_uuid(session_id: str) -> uuid.UUID:
    """Garante um UUID válido para chaves primárias do PostgreSQL."""
    _, session_uuid = normalize_session_id(session_id)
    return session_uuid


def get_or_create_session_state(
    session_id: str,
    user_info: dict | None = None,
    default_archetype: str | None = None,
) -> GameState:
    """Recupera o GameState do PostgreSQL ou da memória, ou cria uma nova partida."""
    chat_id_int, session_uuid = normalize_session_id(session_id)
    if chat_id_int is None and user_info and user_info.get("chat_id") is not None:
        try:
            chat_id_int = int(user_info["chat_id"])
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
        norm_chat_id, session_uuid = normalize_session_id(state.session_id)
        chat_id_int = chat_id if chat_id is not None else norm_chat_id

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

            # 4. Registra apenas mensagens recentes ainda não persistidas
            if state.recent_messages:
                last_msg = state.recent_messages[-1]
                last_db_msg = (
                    db.query(MessageDB)
                    .filter_by(session_id=session_record.session_id)
                    .order_by(MessageDB.timestamp.desc())
                    .first()
                )
                if not last_db_msg or last_db_msg.content != last_msg.content:
                    db_msg = MessageDB(
                        session_id=session_record.session_id,
                        sender=last_msg.sender,
                        role=last_msg.role,
                        content=last_msg.content,
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
    chat_id_int, session_uuid = normalize_session_id(identifier)

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

    return cleared


# Mantém alias para compatibilidade com outros módulos e testes
reset_player_session = reset_game_session
