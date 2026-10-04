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
    resolve_hero_attack,
    resolve_monster_attack,
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
) -> GameState:
    """Cria um novo estado do jogo com a Jaula 1 ativa e Loomis como treinador."""
    cage_1_monster = get_cage_monster(1)
    players = [initial_hero] if initial_hero else []

    state = GameState(
        session_id=session_id,
        location="Clareira de Treino em Hesiod",
        players=players,
        monsters=[cage_1_monster],
        npcs=[NPCState(name="Loomis", system_prompt="")],
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


def advance_turn(state: GameState) -> str:
    """Rotaciona a fila de iniciativa dos heróis (players[0] é sempre a vez)."""
    next_hero = state.rotate_players()
    return next_hero.player_id if next_hero else "monster"


def execute_hero_turn(
    state: GameState,
    player_id: str | None = None,
    action_type: str = "atacar",
    is_far: bool = False,
    is_flanking: bool = False,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> dict:
    """Executa a ação do herói contra o monstro ativo e atualiza o estado."""
    if not state.players:
        raise ValueError("Não há heróis cadastrados na sessão.")

    # Se player_id for especificado, localiza o herói; caso contrário, usa players[0]
    hero = None
    if player_id:
        hero = next((p for p in state.players if p.player_id == player_id), None)
    if not hero:
        hero = state.players[0]

    if not state.monsters:
        raise ValueError("Não há monstros ativos na arena.")

    active_monster = state.monsters[0]

    # Monstros secundários para habilidades em área (ex.: Bet)
    adjacent = [m for m in state.monsters[1:] if not m.is_defeated]

    result = resolve_hero_attack(
        hero=hero,
        monster=active_monster,
        active_monsters_count=len([m for m in state.monsters if not m.is_defeated]),
        heroes_team=state.players,
        is_far=is_far,
        is_flanking=is_flanking,
        adjacent_monsters=adjacent,
        forced_d20=forced_d20,
        forced_damage=forced_damage,
    )

    # Registra a ação do herói no buffer de mensagens recentes
    state.recent_messages.append(
        Message(
            sender="Jogador",
            role="user",
            content=f"{hero.name} atacou. {result.get('narrative_summary', '')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    # Gatilho de destrancar jaula em 50% de HP durante a luta (se não houver herói caído)
    if result.get("loomis_cage_unlocked"):
        new_cage = result["loomis_cage_unlocked"]
        new_monster = get_cage_monster(new_cage)
        state.monsters.append(new_monster)
        state.recent_messages.append(
            Message(
                sender="Loomis",
                role="assistant",
                content=(
                    f"A fera sangra a menos de metade de sua vitalidade! "
                    f"Loomis destranca a Jaula {new_cage} e {new_monster.name} ruge ao entrar na arena!"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    # Resolução de derrota de monstro e transição entre combates
    if active_monster.is_defeated:
        undefeated = [m for m in state.monsters if not m.is_defeated]
        if undefeated:
            # Se ainda houver outro monstro na arena (jaula aberta no meio do combate), avança para ele
            state.monsters.remove(undefeated[0])
            state.monsters.insert(0, undefeated[0])
        else:
            # TODOS os monstros ativos foram derrotados: fim do combate atual!
            # Regra Canônica: Loomis administra poção para heróis com <= 2 HP
            loomis = next((n for n in state.npcs if n.name == "Loomis"), None) or NPCState(name="Loomis", system_prompt="")
            healed_heroes: list[str] = []
            for h in state.players:
                if h.hp <= 2:
                    loomis.heal(h)
                    healed_heroes.append(h.name)

            if healed_heroes:
                state.recent_messages.append(
                    Message(
                        sender="Loomis",
                        role="assistant",
                        content=(
                            f"Loomis retira um frasco cintilante de líquido límpido da bolsa: "
                            f"“É melhor beberem tudo antes da próxima luta!” "
                            f"O líquido tem sabor refrescante de menta e limão. "
                            f"{', '.join(healed_heroes)} recuperaram todos os pontos de vida!"
                        ),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )

            if active_monster.cage_number >= 4:
                state.is_victory = True
                result["is_victory"] = True
                state.recent_messages.append(
                    Message(
                        sender="Loomis",
                        role="assistant",
                        content="“Incrível! Vocês superaram todas as 4 jaulas e conquistaram a insígnia de Heróis de Hesiod!”",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )
            else:
                next_cage = active_monster.cage_number + 1
                next_monster = get_cage_monster(next_cage)
                state.monsters = [next_monster]
                state.recent_messages.append(
                    Message(
                        sender="Loomis",
                        role="assistant",
                        content=(
                            f"“Estão melhores agora? Ótimo! É hora do próximo desafio!” "
                            f"Loomis puxa a trava da Jaula {next_cage}. A porta se abre num estrondo e {next_monster.name} avança!"
                        ),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )

    if result.get("is_victory"):
        state.is_victory = True

    # Rotaciona a fila de heróis
    advance_turn(state)
    set_memory_session(state.session_id, state)
    return result


def execute_monster_turn(
    state: GameState,
    target_player_id: str | None = None,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> dict:
    """Executa a ação do monstro ativo contra um dos heróis conforme as regras de Hesiod."""
    if not state.players:
        raise ValueError("Não há heróis na sessão para o monstro atacar.")
    if not state.monsters:
        raise ValueError("Não há monstros ativos para atacar.")

    active_monster = state.monsters[0]

    # Heróis conscientes (HP > 0)
    conscious_heroes = [p for p in state.players if not p.is_unconscious]
    if not conscious_heroes:
        # Todos caíram inconscientes
        target_hero = state.players[0]
    elif target_player_id:
        target_hero = next((p for p in state.players if p.player_id == target_player_id), conscious_heroes[0])
    else:
        # Regra Canônica de Hesiod:
        # 1. Monstros gostam de desafios e atacam o herói com MAIOR HP atual.
        # 2. Quase nunca atacam o mesmo herói duas vezes seguidas se houver outra opção.
        last_attacked_name: str | None = None
        for msg in reversed(state.recent_messages):
            if msg.sender == "Monstro" and "atacou " in msg.content:
                parts = msg.content.split("atacou ")
                if len(parts) > 1:
                    last_attacked_name = parts[1].split(".")[0].strip()
                    break

        candidates = [h for h in conscious_heroes if h.name != last_attacked_name]
        if not candidates:
            candidates = conscious_heroes

        target_hero = max(candidates, key=lambda p: p.hp)

    result = resolve_monster_attack(
        monster=active_monster,
        hero=target_hero,
        forced_d20=forced_d20,
        forced_damage=forced_damage,
    )

    state.recent_messages.append(
        Message(
            sender="Monstro",
            role="assistant",
            content=f"{active_monster.name} atacou {target_hero.name}. {result.get('narrative_summary', '')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    set_memory_session(state.session_id, state)
    return result


def get_or_create_session_state(
    session_id: str,
    user_info: dict | None = None,
    default_archetype: str | None = None,
) -> GameState:
    """Recupera o GameState do PostgreSQL ou da memória, ou cria uma nova partida."""
    # 1. Tenta carregar do banco de dados relacional normalizado
    try:
        session_uuid = uuid.UUID(session_id)
        with SessionLocal() as db:
            session_db = db.query(Session).filter_by(session_id=session_uuid).first()
            if session_db:
                # Carrega heróis da sessão
                db_heroes = db.query(Hero).filter_by(session_id=session_uuid).all()
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
                db_monsters = db.query(Monster).filter_by(session_id=session_uuid).all()
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
                    .filter_by(session_id=session_uuid)
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
                return state
    except Exception as e:
        logger.debug(f"Acesso ao banco ignorado ou indisponível ao carregar session_id={session_id}: {e}")

    # 2. Tenta recuperar da memória
    cached = get_memory_session(session_id)
    if cached:
        return cached

    # 3. Cria nova sessão inicial
    chat_id = user_info.get("chat_id") if user_info else None
    player_id = str(user_info.get("player_id") or chat_id or "player_1") if user_info else "player_1"
    archetype = default_archetype or (user_info.get("archetype") if user_info else None) or "Jorick"

    initial_hero = create_hero(archetype, player_id=player_id)
    new_state = create_initial_rpg_state(session_id=session_id, initial_hero=initial_hero)

    # Tenta persistir no banco relacional
    persist_session_state_to_db(new_state, chat_id=chat_id)
    return new_state


def persist_session_state_to_db(state: GameState, chat_id: int | None = None) -> bool:
    """Persiste o GameState nas tabelas relacionais explícitas (sessions, heroes, monsters, messages)."""
    try:
        session_uuid = uuid.UUID(state.session_id)
        with SessionLocal() as db:
            # 1. Atualiza ou insere session
            session_record = db.query(Session).filter_by(session_id=session_uuid).first()
            if not session_record:
                session_record = Session(
                    session_id=session_uuid,
                    chat_id=chat_id,
                    location=state.location,
                    is_victory=state.is_victory,
                )
                db.add(session_record)
            else:
                session_record.location = state.location
                session_record.is_victory = state.is_victory

            # 2. Atualiza ou insere heroes
            for hero in state.players:
                db_hero = db.query(Hero).filter_by(session_id=session_uuid, player_id=hero.player_id).first()
                if not db_hero:
                    db_hero = Hero(
                        session_id=session_uuid,
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
                    session_id=session_uuid,
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


def reset_player_session(chat_id: int) -> bool:
    """Apaga os dados da sessão do jogador no banco e na memória."""
    logger.info(f"Resetando sessão de jogo para chat_id={chat_id}")
    cleared = False
    try:
        with SessionLocal() as db:
            session_db = db.query(Session).filter_by(chat_id=chat_id).first()
            if session_db:
                session_id_str = str(session_db.session_id)
                db.delete(session_db)
                db.commit()
                clear_memory_session(session_id_str)
                cleared = True
    except Exception as e:
        logger.warning(f"Erro ao resetar sessão no banco: {e}")

    # Limpa da memória caso o ID do chat seja a chave ou esteja nos jogadores
    for sid, state in list(_MEMORY_SESSIONS.items()):
        if sid == str(chat_id) or any(p.player_id == str(chat_id) for p in state.players):
            clear_memory_session(sid)
            cleared = True

    return cleared or True
