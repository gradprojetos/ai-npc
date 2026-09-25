import logging
import uuid
from typing import Any
from datetime import datetime, timezone

from api.schemas.rpg import (
    HeroState,
    MonsterState,
    RPGGraphState,
    ActionResult,
    ActionType,
    Message,
)
from api.motor_rpg.motor_rpg import (
    create_hero,
    get_cage_monster,
    resolve_hero_attack,
    resolve_monster_attack,
)
from db.models import Usuario, SessaoJogo, HistoricoMensagens, EstadoSessao
from db.session import SessionLocal

logger = logging.getLogger(__name__)

# Fallback em memória para execução sem banco ou ambiente de testes/desconectado
_MEMORY_SESSIONS: dict[str, RPGGraphState] = {}


def get_memory_session(session_id: str) -> RPGGraphState | None:
    """Recupera o estado em memória para uma sessão."""
    return _MEMORY_SESSIONS.get(session_id)


def set_memory_session(session_id: str, state: RPGGraphState) -> None:
    """Salva o estado em memória para uma sessão."""
    _MEMORY_SESSIONS[session_id] = state


def clear_memory_session(session_id: str) -> None:
    """Remove a sessão do armazenamento em memória."""
    _MEMORY_SESSIONS.pop(session_id, None)


def create_initial_rpg_state(
    session_id: str,
    initial_hero: HeroState | None = None,
) -> RPGGraphState:
    """Cria um novo estado do RPG com a Jaula 1 ativa."""
    cage_1_monster = get_cage_monster(1)
    players = [initial_hero] if initial_hero else []
    
    # Monstro age primeiro ou por iniciativa, conforme game_rules.md
    initial_turn = "monster"

    state = RPGGraphState(
        session_id=session_id,
        players=players,
        current_turn=initial_turn,
        current_monster=cage_1_monster,
        active_monsters=[cage_1_monster],
        cage_number=1,
        round_number=1,
        history=[],
        current_intent="conversar",
        loomis_response="",
        is_victory=False,
    )
    set_memory_session(session_id, state)
    return state


def add_or_update_player(
    state: RPGGraphState,
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

    # Se a vez for de um jogador e não houver quem agisse, ajusta a vez
    if state.current_turn != "monster" and (
        not any(p.player_id == state.current_turn for p in state.players)
    ):
        state.current_turn = state.players[0].player_id

    return hero


def advance_turn(state: RPGGraphState) -> str:
    """Avança o turno de acordo com a ordem de participantes (Turn vs Round).
    
    Ordem da Rodada:
    Monstro -> Herói 1 -> Herói 2 -> ... -> Fim da Rodada (+1) -> Monstro.
    """
    if not state.players:
        state.current_turn = "monster"
        return "monster"

    if state.current_turn == "monster":
        # Passa a vez para o primeiro herói ativo
        state.current_turn = state.players[0].player_id
        return state.current_turn

    # Se a vez for de um herói
    player_ids = [p.player_id for p in state.players]
    try:
        idx = player_ids.index(state.current_turn)
        if idx + 1 < len(player_ids):
            # Próximo herói do grupo
            state.current_turn = player_ids[idx + 1]
        else:
            # Todos os heróis agiram: fecha a rodada e passa a vez para o monstro
            state.current_turn = "monster"
            state.round_number += 1
    except ValueError:
        state.current_turn = player_ids[0]

    return state.current_turn


def execute_hero_turn(
    state: RPGGraphState,
    player_id: str,
    action_type: str = "atacar",
    is_far: bool = False,
    is_flanking: bool = False,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> ActionResult:
    """Executa a ação do herói contra o monstro ativo e atualiza o estado da partida."""
    hero = next((p for p in state.players if p.player_id == player_id), None)
    if not hero:
        raise ValueError(f"Jogador {player_id} não possui personagem cadastrado na sessão.")

    # Alvos secundários (se houver mais de um monstro na clareira)
    adjacent = [
        m for m in state.active_monsters
        if m.name != state.current_monster.name and not m.is_defeated
    ]

    result = resolve_hero_attack(
        hero=hero,
        monster=state.current_monster,
        active_monsters_count=len([m for m in state.active_monsters if not m.is_defeated]),
        is_far=is_far,
        is_flanking=is_flanking,
        adjacent_monsters=adjacent,
        forced_d20=forced_d20,
        forced_damage=forced_damage,
    )

    # Gatilho de liberação de próxima jaula em 50% de HP
    if result.loomis_cage_unlocked:
        new_cage = result.loomis_cage_unlocked
        state.cage_number = new_cage
        new_monster = get_cage_monster(new_cage)
        state.active_monsters.append(new_monster)

    # Verifica se o monstro atual foi derrotado
    if state.current_monster.is_defeated:
        # Se houver outros monstros ativos (ex: jaula destrancada anteriormente)
        undefeated = [m for m in state.active_monsters if not m.is_defeated]
        if undefeated:
            state.current_monster = undefeated[0]
        elif result.is_victory:
            state.is_victory = True
        elif state.cage_number < 4:
            # Passa para a próxima jaula
            state.cage_number += 1
            next_monster = get_cage_monster(state.cage_number)
            state.current_monster = next_monster
            state.active_monsters = [next_monster]

    if result.is_victory:
        state.is_victory = True

    # Registra no histórico do estado
    state.history.append(
        Message(
            role="jogador",
            content=f"{hero.name} executou {action_type}. {result.narrative_summary}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    # Garante que a vez reflita o herói antes de avançar para o próximo participante
    state.current_turn = hero.player_id
    advance_turn(state)
    set_memory_session(state.session_id, state)
    return result


def execute_monster_turn(
    state: RPGGraphState,
    target_player_id: str | None = None,
    forced_d20: int | None = None,
    forced_damage: int | None = None,
) -> ActionResult:
    """Executa a ação do monstro ativo contra um dos heróis do grupo."""
    if not state.players:
        raise ValueError("Não há heróis na sessão para o monstro atacar.")

    # Escolhe o herói alvo (específico, ou o primeiro consciente, ou o de menor vida)
    if target_player_id:
        target_hero = next((p for p in state.players if p.player_id == target_player_id), state.players[0])
    else:
        # Foca no herói com menor vida atual
        target_hero = min(state.players, key=lambda p: p.hp)

    result = resolve_monster_attack(
        monster=state.current_monster,
        hero=target_hero,
        forced_d20=forced_d20,
        forced_damage=forced_damage,
    )

    state.history.append(
        Message(
            role="monstro",
            content=f"{state.current_monster.name} atacou {target_hero.name}. {result.narrative_summary}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    # Garante que a vez reflita o monstro antes de avançar para o próximo participante
    state.current_turn = "monster"
    advance_turn(state)
    set_memory_session(state.session_id, state)
    return result


def get_or_create_session_state(
    session_id: str,
    telegram_id: int | None = None,
    player_name: str = "Aventureiro",
    default_archetype: str | None = None,
) -> RPGGraphState:
    """Recupera o estado do jogo do banco ou da memória, ou cria uma nova partida se não existir."""
    # 1. Tenta carregar do banco de dados se configurado
    try:
        with SessionLocal() as db:
            sessao_db = db.query(SessaoJogo).filter(SessaoJogo.id_sessao == uuid.UUID(session_id)).first()
            if sessao_db:
                estado_db = db.query(EstadoSessao).filter(EstadoSessao.id_sessao == sessao_db.id_sessao).first()
                if estado_db and estado_db.variaveis_jogo:
                    state = RPGGraphState.model_validate(estado_db.variaveis_jogo)
                    set_memory_session(session_id, state)
                    return state
    except Exception as e:
        logger.debug(f"Acesso ao banco ignorado ou indisponível ao carregar sessão {session_id}: {e}")

    # 2. Tenta recuperar da memória
    cached = get_memory_session(session_id)
    if cached:
        return cached

    # 3. Cria nova sessão inicial
    hero = create_hero(default_archetype, player_id=str(telegram_id or "player_1")) if default_archetype else None
    new_state = create_initial_rpg_state(session_id=session_id, initial_hero=hero)
    
    # Tenta persistir no banco caso a tabela e conexão existam
    persist_session_state_to_db(new_state)
    return new_state


def persist_session_state_to_db(state: RPGGraphState) -> bool:
    """Persiste o RPGGraphState atualizado na tabela EstadoSessao do PostgreSQL."""
    try:
        session_uuid = uuid.UUID(state.session_id)
        with SessionLocal() as db:
            estado = db.query(EstadoSessao).filter(EstadoSessao.id_sessao == session_uuid).first()
            if estado:
                estado.variaveis_jogo = state.model_dump()
                estado.ultima_atualizacao = datetime.now(timezone.utc)
                db.commit()
                return True
    except Exception as e:
        logger.debug(f"Não foi possível persistir estado no banco para session_id={state.session_id}: {e}")
    return False


def reset_player_session(telegram_id: int) -> bool:
    """Apaga o histórico de mensagens e reseta as variáveis do jogo para o jogador."""
    logger.info(f"Resetando sessão de jogo para telegram_id={telegram_id}")
    cleared = False
    try:
        with SessionLocal() as db:
            usuario = db.query(Usuario).filter(Usuario.telegram_id == telegram_id).first()
            if usuario:
                sessoes = db.query(SessaoJogo).filter(SessaoJogo.id_usuario == usuario.id_usuario).all()
                for sessao in sessoes:
                    db.query(HistoricoMensagens).filter(HistoricoMensagens.id_sessao == sessao.id_sessao).delete()
                    estado = db.query(EstadoSessao).filter(EstadoSessao.id_sessao == sessao.id_sessao).first()
                    if estado:
                        estado.variaveis_jogo = {}
                        estado.progresso_pedagogico = {}
                    clear_memory_session(str(sessao.id_sessao))
                db.commit()
                cleared = True
    except Exception as e:
        logger.warning(f"Erro ao resetar sessão no banco: {e}")

    # Limpa referências em memória com base no ID
    for sid, state in list(_MEMORY_SESSIONS.items()):
        if any(p.player_id == str(telegram_id) for p in state.players):
            clear_memory_session(sid)
            cleared = True

    logger.info(f"Sessão de jogo resetada com sucesso para telegram_id={telegram_id}")
    return cleared or True
