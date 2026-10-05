from api.motor_rpg.session_service import (
    create_initial_rpg_state,
    add_or_update_player,
    advance_turn,
    execute_hero_turn,
    execute_monster_turn,
    get_memory_session,
    clear_memory_session,
    reset_player_session,
)
from api.motor_rpg.motor_rpg import create_hero


def setup_function():
    # Limpa sessões de teste antes de cada caso
    clear_memory_session("test_session_1")
    clear_memory_session("test_session_coop")


def test_create_initial_state():
    state = create_initial_rpg_state("test_session_1")
    assert state.session_id == "test_session_1"
    assert state.location == "Clareira de Treino em Hesiod"
    assert len(state.monsters) == 1
    assert state.monsters[0].name == "Bullette Faminto"
    assert state.monsters[0].cage_number == 1
    assert len(state.players) == 0
    assert not state.is_victory


def test_add_and_update_player():
    state = create_initial_rpg_state("test_session_1")
    hero = add_or_update_player(state, player_id="user_123", hero_archetype_or_name="jorick")
    assert hero.name == "Jorick"
    assert len(state.players) == 1
    assert state.players[0].player_id == "user_123"

    # Atualiza o herói do mesmo jogador para Bet
    updated_hero = add_or_update_player(state, player_id="user_123", hero_archetype_or_name="bet")
    assert updated_hero.name == "Bet"
    assert len(state.players) == 1
    assert state.players[0].name == "Bet"


def test_turn_progression_singleplayer():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")

    # Inicialmente, o jogador ativo é o p1
    assert state.players[0].player_id == "p1"

    # Ao avançar o turno, ele rotaciona na fila
    next_id = advance_turn(state)
    assert next_id == "p1"
    assert state.players[0].player_id == "p1"


def test_turn_progression_cooperative_group():
    state = create_initial_rpg_state("test_session_coop")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")
    add_or_update_player(state, player_id="p2", hero_archetype_or_name="raen")
    add_or_update_player(state, player_id="p3", hero_archetype_or_name="bet")

    # Fila inicial: p1 -> p2 -> p3
    assert state.players[0].player_id == "p1"

    # Turno 1 -> passa para p2
    next_id = advance_turn(state)
    assert next_id == "p2"
    assert state.players[0].player_id == "p2"

    # Turno 2 -> passa para p3
    next_id = advance_turn(state)
    assert next_id == "p3"
    assert state.players[0].player_id == "p3"

    # Turno 3 -> rotaciona de volta para p1
    next_id = advance_turn(state)
    assert next_id == "p1"
    assert state.players[0].player_id == "p1"


def test_execute_hero_turn_combat_and_history():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")

    # Força acerto no Bullette (CA 15)
    result = execute_hero_turn(state, player_id="p1", forced_d20=15)
    assert result["is_hit"] is True
    assert result["damage_dealt"] == 1
    assert state.monsters[0].hp == 7

    # Verifica se histórico da sessão foi atualizado
    assert len(state.recent_messages) == 1
    assert "Jorick" in state.recent_messages[0].content
    assert state.recent_messages[0].role == "user"


def test_execute_monster_turn_and_loomis_potion():
    state = create_initial_rpg_state("test_session_1")
    hero = add_or_update_player(state, player_id="p1", hero_archetype_or_name="evindol")  # max_hp = 3
    hero.hp = 1  # Deixa com 1 de vida

    # Monstro ataca e zera a vida do herói
    result = execute_monster_turn(state, target_player_id="p1", forced_d20=15)
    assert result["is_hit"] is True
    assert result["loomis_potion_used"] is True

    # Vida deve ser restaurada pelo Loomis para o máximo do Evindol (3)
    assert hero.hp == 3
    assert len(state.recent_messages) == 1
    assert state.recent_messages[0].role == "assistant"


def test_session_reset():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="999", hero_archetype_or_name="jorick")
    assert get_memory_session("test_session_1") is not None

    reset_player_session(999)
    assert get_memory_session("test_session_1") is None
