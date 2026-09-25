import pytest
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
    assert state.cage_number == 1
    assert state.current_monster.name == "Bullette Faminto"
    assert state.round_number == 1
    assert state.current_turn == "monster"
    assert len(state.players) == 0
    assert len(state.active_monsters) == 1


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


def test_turn_and_round_progression_singleplayer():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")

    # Início: vez do monstro
    assert state.current_turn == "monster"
    assert state.round_number == 1

    # Monstro age -> passa para p1
    next_turn = advance_turn(state)
    assert next_turn == "p1"
    assert state.current_turn == "p1"
    assert state.round_number == 1

    # p1 age -> todos agiram, passa para o monstro e fecha a rodada (+1)
    next_turn = advance_turn(state)
    assert next_turn == "monster"
    assert state.current_turn == "monster"
    assert state.round_number == 2


def test_turn_and_round_progression_cooperative_group():
    state = create_initial_rpg_state("test_session_coop")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")
    add_or_update_player(state, player_id="p2", hero_archetype_or_name="raen")
    add_or_update_player(state, player_id="p3", hero_archetype_or_name="bet")

    # Ciclo: monster -> p1 -> p2 -> p3 -> monster (Round 2)
    assert state.current_turn == "monster"
    assert state.round_number == 1

    advance_turn(state)
    assert state.current_turn == "p1"
    assert state.round_number == 1

    advance_turn(state)
    assert state.current_turn == "p2"
    assert state.round_number == 1

    advance_turn(state)
    assert state.current_turn == "p3"
    assert state.round_number == 1

    advance_turn(state)
    assert state.current_turn == "monster"
    assert state.round_number == 2


def test_execute_hero_turn_combat_and_history():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="p1", hero_archetype_or_name="jorick")

    # Força acerto no Bullette (CA 15)
    result = execute_hero_turn(state, player_id="p1", forced_d20=15)
    assert result.is_hit
    assert result.damage_dealt == 1
    assert state.current_monster.hp == 7

    # Verifica se histórico da sessão foi atualizado
    assert len(state.history) == 1
    assert "Jorick" in state.history[0].content
    assert state.history[0].role == "jogador"

    # Vez deve ter avançado para o monstro
    assert state.current_turn == "monster"


def test_execute_monster_turn_and_loomis_potion():
    state = create_initial_rpg_state("test_session_1")
    hero = add_or_update_player(state, player_id="p1", hero_archetype_or_name="evindol")  # HP = 3
    hero.hp = 1  # Deixa com 1 de vida

    # Monstro ataca e zera a vida do herói
    result = execute_monster_turn(state, target_player_id="p1", forced_d20=15)
    assert result.is_hit
    assert result.loomis_potion_used is True

    # Vida deve ser restaurada pelo Loomis para o máximo do Evindol (3)
    assert hero.hp == 3
    assert len(state.history) == 1
    assert state.history[0].role == "monstro"


def test_session_reset():
    state = create_initial_rpg_state("test_session_1")
    add_or_update_player(state, player_id="999", hero_archetype_or_name="jorick")
    assert get_memory_session("test_session_1") is not None

    reset_player_session(999)
    assert get_memory_session("test_session_1") is None
