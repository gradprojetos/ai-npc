from api.motor_rpg.session_service import (
    create_initial_rpg_state,
    select_hero_for_player,
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


def test_session_reset():
    state = create_initial_rpg_state("test_session_1")
    hero = create_hero("jorick", player_id="999")
    state.players.append(hero)
    assert get_memory_session("test_session_1") is not None

    reset_player_session(999)
    assert get_memory_session("test_session_1") is None

