import pytest
from fastapi.testclient import TestClient

from api.ai_core.orchestrator import is_noise_input, process_npc_turn
from api.ai_core.turn_graph import extract_d20, has_invalid_d20
from api.main import app
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    reset_game_session,
    select_hero_for_player,
)
from llm_gateway.client import GroqAdapter, ICUnicampAdapter, LLMClient, OpenRouterAdapter, create_llm_adapter
from tests.recorder import clear_test_output, log_test_turn

client = TestClient(app)


def test_api_rest_endpoints_simulation():
    """Testa os endpoints REST (/game/*) simulando clientes HTTP externos sem Telegram."""
    session_id = "test_rest_session"
    log_file = "e2e_rest_endpoints.log"
    clear_test_output(log_file)
    reset_game_session(session_id)

    resp1 = client.post("/game/select", json={"session_id": session_id, "player_id": "u1", "player_name": "Lucas", "choice": 3})
    assert resp1.status_code == 200
    assert "Jorick" in resp1.json()["message"]
    log_test_turn(log_file, "POST /game/select", "Lucas (u1)", "choice: 3", resp1.json()["message"])

    resp_done = client.post("/game/done", json={"session_id": session_id})
    assert resp_done.status_code == 200
    assert "Dungeon Master:" in resp_done.json()["message"]
    log_test_turn(log_file, "POST /game/done", "Lucas", "/game/done", resp_done.json()["message"])

    resp_state = client.get(f"/game/state/{session_id}")
    assert resp_state.status_code == 200
    assert len(resp_state.json()["players"]) == 1
    log_test_turn(log_file, "GET /game/state", "Cliente", "Consulta", str(resp_state.json()))

    resp_msg = client.post("/game/message", json={"session_id": session_id, "player_id": "u1", "player_name": "Lucas", "message": "Olá Loomis!"})
    assert resp_msg.status_code == 200
    assert "Loomis:" in resp_msg.json()["reply"]
    log_test_turn(log_file, "POST /game/message", "Lucas", "Olá Loomis!", resp_msg.json()["reply"])

    resp_reset = client.post("/game/reset", json={"session_id": session_id})
    assert resp_reset.status_code == 200
    log_test_turn(log_file, "POST /game/reset", "Cliente", "Reset", str(resp_reset.json()))
    reset_game_session(session_id)


@pytest.mark.asyncio
async def test_regressions_and_guardrails():
    """Valida guardrails pré-grafo, d20 inválido/1 dígito, adapters LLM e persistência de estado."""
    log_file = "e2e_regressions_and_guardrails.log"
    clear_test_output(log_file)
    session_id = "test_regressions"
    reset_game_session(session_id)

    # Unitário de d20 e ruído
    assert has_invalid_d20("ataco com 50") is True
    assert has_invalid_d20("rolei 0") is True
    assert has_invalid_d20("-5") is True
    assert has_invalid_d20("tenho 2 espadas e 30 moedas") is False
    assert has_invalid_d20("estamos prontos 100%") is False

    assert await extract_d20("7") == 7
    assert await extract_d20("ataco com 15") == 15
    assert await extract_d20("ataco com 50") is None

    assert is_noise_input(".") is True
    assert is_noise_input("7") is False
    assert is_noise_input("ok") is False

    # Adapters LLM
    assert isinstance(create_llm_adapter(provider="groq"), GroqAdapter)
    assert isinstance(create_llm_adapter(provider="openrouter"), OpenRouterAdapter)
    assert isinstance(create_llm_adapter(provider="ic"), ICUnicampAdapter)

    # Sessão: Ruído e Ofensa
    select_hero_for_player(session_id, "101", "Isaac", 4)
    finish_recruiting_for_session(session_id)

    r_noise = await process_npc_turn(".", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Fale com clareza" in r_noise
    log_test_turn(log_file, "Ruído", "Isaac", ".", r_noise)

    r_prof = await process_npc_turn("vai se ferrar", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Olha a boca na minha arena" in r_prof
    log_test_turn(log_file, "Ofensa", "Isaac", "vai se ferrar", r_prof)

    # d20 inválido não abre jaula
    r_inv1 = await process_npc_turn("ataco com 50", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Valor inválido! O d20 físico possui apenas valores de 1 a 20" in r_inv1
    assert "Jaula 1 foi aberta" not in r_inv1

    # d20 1 dígito resolve ataque
    r_single = await process_npc_turn("7", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Dungeon Master:" in r_single
    assert "Yarrow" in r_single
    assert "atacou" in r_single
    log_test_turn(log_file, "d20 1 Dígito (7)", "Isaac", "7", r_single)
    reset_game_session(session_id)
