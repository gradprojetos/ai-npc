import pytest
from fastapi.testclient import TestClient

from api.ai_core.orchestrator import is_noise_input, process_npc_turn
from api.ai_core.turn_graph import (
    _round_buffers,
    extract_d20,
    has_invalid_d20,
)
from api.main import app
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    get_or_create_session_state,
    reset_game_session,
    select_hero_for_player,
)
from llm_gateway.client import GroqAdapter, ICUnicampAdapter, LLMClient, OpenRouterAdapter, create_llm_adapter

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_test_state():
    """Limpa estado em memória e banco antes e depois de cada teste."""
    sessions = ["test_coop_e2e", "test_rest_session", "test_full_victory", "test_regressions"]
    for s_id in sessions:
        reset_game_session(s_id)
    yield
    for s_id in sessions:
        reset_game_session(s_id)


@pytest.mark.asyncio
async def test_e2e_cooperative_multiplayer_flow():
    """Simulação ponta a ponta de uma sessão cooperativa completa entre 2 jogadores.
    
    Cobre:
    1. Seleção de 2 cartas por jogadores distintos e ordem de iniciativa canônica.
    2. Encerramento de recrutamento (/done) e prólogo na cabana (jaula fechada).
    3. Diálogo de exploração livre e lore com Loomis.
    4. Confirmação voluntária de prontidão para abrir a Jaula 1.
    5. Rodada fechada de combate: Jogador 1 ataca -> Jogador 2 ataca -> DM resolve e Monstro ataca.
    6. Alternância de alvo do monstro na rodada 2 (evitando foco consecutivo na mesma vítima).
    """
    session_id = "test_coop_e2e"

    # =========================================================================
    # 1. Seleção de Heróis: Isaac (#1 Evindol) e Pedro (#2 Raen)
    # =========================================================================
    ok1, msg1, state = select_hero_for_player(
        session_id=session_id,
        player_id="101",
        player_name="Isaac",
        choice="1",
    )
    assert ok1 is True
    assert state.players[0].name == "Evindol"
    assert len(state.players) == 1

    ok2, msg2, state = select_hero_for_player(
        session_id=session_id,
        player_id="202",
        player_name="Pedro",
        choice="2",
    )
    assert ok2 is True
    assert len(state.players) == 2
    assert "Evindol" in state.players[0].name
    assert "Raen" in state.players[1].name

    # =========================================================================
    # 2. Finalização de Recrutamento (/done)
    # =========================================================================
    ok_done, briefing, state = finish_recruiting_for_session(session_id)
    assert ok_done is True
    assert state.is_recruiting is False
    assert "Dungeon Master:" in briefing
    assert "Loomis:" in briefing
    assert "quando estiverem prontos para a primeira fera, me digam 'estamos prontos'" in briefing
    assert "Jaula 1 Aberta!" not in briefing

    # =========================================================================
    # 3. Fase de Exploração: Isaac pergunta sobre o caldeirão (chamada real de LLM)
    # =========================================================================
    reply_exp = await process_npc_turn(
        user_message="Loomis, o que você está cozinhando naquele caldeirão grande?",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )
    assert "Loomis:" in reply_exp
    assert len(reply_exp) > 20

    # =========================================================================
    # 4. Transição para Combate: Pedro diz "estamos prontos" (chamada real de LLM)
    # =========================================================================
    reply_ready = await process_npc_turn(
        user_message="Estamos prontos para a fera, Loomis! Puxe a alavanca!",
        user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
    )
    assert "Dungeon Master:" in reply_ready
    assert "Jaula 1 foi aberta" in reply_ready
    assert "Bullette Faminto" in reply_ready
    assert "Loomis:" in reply_ready

    # =========================================================================
    # 5. Rodada 1 de Combate (Fechada, chamada real de LLM)
    # =========================================================================
    reply_round1_p1 = await process_npc_turn(
        user_message="ataco a fera tirei 19 no dado",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )

    assert "Dungeon Master:" in reply_round1_p1
    assert "Evindol" in reply_round1_p1
    assert "Próximo a agir: <b>Raen</b>" in reply_round1_p1
    assert "Loomis:" not in reply_round1_p1
    assert len(_round_buffers.get(session_id, [])) == 1
    assert "Evindol" in _round_buffers[session_id][0]

    reply_dup = await process_npc_turn(
        user_message="ataco de novo com 20",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )
    assert "já realizou sua ação nesta rodada" in reply_dup
    assert "É a vez de <b>Raen</b>" in reply_dup

    reply_round1_p2 = await process_npc_turn(
        user_message="desfiro um machadada forte com 17",
        user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
    )

    assert "Dungeon Master:" in reply_round1_p2
    assert "Evindol" in reply_round1_p2
    assert "Raen" in reply_round1_p2
    assert "contra-atacou <b>Raen</b>" in reply_round1_p2
    assert "Loomis:" in reply_round1_p2

    # =========================================================================
    # 6. Rodada 2: Alternância Canônica de Alvo do Monstro
    # =========================================================================
    reply_round2_p1 = await process_npc_turn(
        user_message="ataco com 18",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )
    assert "Dungeon Master:" in reply_round2_p1
    assert "Próximo a agir: <b>Raen</b>" in reply_round2_p1
    assert "Loomis:" not in reply_round2_p1

    reply_round2 = await process_npc_turn(
        user_message="golpeio com 16",
        user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
    )

    assert "contra-atacou <b>Evindol</b>" in reply_round2


def test_api_rest_endpoints_simulation():
    """Testa os novos endpoints REST (/game/*) simulando clientes HTTP externos sem Telegram."""
    session_id = "test_rest_session"

    resp1 = client.post("/game/select", json={
        "session_id": session_id,
        "player_id": "u1",
        "player_name": "Lucas",
        "choice": 3,
    })
    assert resp1.status_code == 200
    assert resp1.json()["success"] is True
    assert "Jorick" in resp1.json()["message"]

    resp_done = client.post("/game/done", json={"session_id": session_id})
    assert resp_done.status_code == 200
    assert resp_done.json()["success"] is True
    assert "Dungeon Master:" in resp_done.json()["message"]

    resp_state = client.get(f"/game/state/{session_id}")
    assert resp_state.status_code == 200
    data = resp_state.json()
    assert data["session_id"] == session_id
    assert len(data["players"]) == 1
    assert data["players"][0]["name"] == "Jorick"

    resp_msg = client.post("/game/message", json={
        "session_id": session_id,
        "player_id": "u1",
        "player_name": "Lucas",
        "message": "Olá Loomis!",
    })
    assert resp_msg.status_code == 200
    assert "Loomis:" in resp_msg.json()["reply"]

    resp_reset = client.post("/game/reset", json={"session_id": session_id})
    assert resp_reset.status_code == 200
    assert resp_reset.json()["success"] is True


@pytest.mark.asyncio
async def test_e2e_full_campaign_until_victory():
    """Simulação ponta a ponta completa de todas as 4 jaulas até a vitória final do grupo."""
    session_id = "test_full_victory"

    client.post("/game/select", json={"session_id": session_id, "player_id": "101", "player_name": "Isaac", "choice": 1})
    client.post("/game/select", json={"session_id": session_id, "player_id": "202", "player_name": "Pedro", "choice": 2})

    resp_done = client.post("/game/done", json={"session_id": session_id})
    assert resp_done.status_code == 200

    await process_npc_turn(
        user_message="Estamos prontos para a arena!",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )

    max_rounds = 30
    victory_reached = False
    last_reply = ""

    for _ in range(max_rounds):
        await process_npc_turn(
            user_message="ataco a criatura com 20",
            user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
        )

        last_reply = await process_npc_turn(
            user_message="golpeio a fera com 20",
            user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
        )

        state_resp = client.get(f"/game/state/{session_id}")
        assert state_resp.status_code == 200
        state_data = state_resp.json()

        if state_data["is_victory"]:
            victory_reached = True
            break

    assert victory_reached is True
    assert "Todas as 4 jaulas foram superadas" in last_reply


@pytest.mark.asyncio
async def test_regressions_and_guardrails():
    """Valida guardrails pré-grafo, d20 inválido/1 dígito, adapters LLM e persistência de estado."""
    # 1. Validação unitária de has_invalid_d20, extract_d20 e is_noise_input
    assert has_invalid_d20("ataco com 50") is True
    assert has_invalid_d20("rolei 0") is True
    assert has_invalid_d20("-5") is True
    assert has_invalid_d20("tenho 2 espadas e 30 moedas") is False
    assert has_invalid_d20("estamos prontos 100%") is False
    assert has_invalid_d20("goblin-2") is False

    assert await extract_d20("7") == 7
    assert await extract_d20("ataco com 15") == 15
    assert await extract_d20("ataco com 50") is None

    assert is_noise_input(".") is True
    assert is_noise_input("?!") is True
    assert is_noise_input("7") is False
    assert is_noise_input("ok") is False

    # 2. Validação dos Adapters LLM e LLM_PROVIDER
    assert isinstance(create_llm_adapter(provider="groq"), GroqAdapter)
    assert isinstance(create_llm_adapter(provider="openrouter"), OpenRouterAdapter)
    assert isinstance(create_llm_adapter(provider="ic"), ICUnicampAdapter)
    groq_client = LLMClient(provider="groq", api_key="test_k", model="llama-3.3-70b-versatile")
    payload = groq_client.adapter.build_payload(
        messages=[{"role": "user", "content": "oi"}],
        temperature=0.4,
        max_tokens=60,
    )
    assert "options" not in payload
    assert payload["model"] == "llama-3.3-70b-versatile"

    # 3. Fluxo de sessão com ruído, ofensa, d20 inválido repetido e d20 de 1 dígito
    session_id = "test_regressions"
    select_hero_for_player(session_id, "101", "Isaac", 4)  # Yarrow
    finish_recruiting_for_session(session_id)

    # Ruído e ofensa não alteram estado nem abrem jaula
    r_noise = await process_npc_turn(".", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Fale com clareza" in r_noise

    r_prof = await process_npc_turn("vai se ferrar", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Olha a boca na minha arena" in r_prof

    # Dois d20 inválidos seguidos: não anunciam abertura de jaula e ambos são persistidos no banco
    r_inv1 = await process_npc_turn("ataco com 50", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Valor inválido! O d20 físico possui apenas valores de 1 a 20" in r_inv1
    assert "Jaula 1 foi aberta" not in r_inv1

    r_inv2 = await process_npc_turn("ataco com 40", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Valor inválido! O d20 físico possui apenas valores de 1 a 20" in r_inv2

    st_after_inv = get_or_create_session_state(session_id)
    user_contents = [m.content for m in st_after_inv.recent_messages if m.role == "user"]
    assert "ataco com 50" in user_contents
    assert "ataco com 40" in user_contents
    assert st_after_inv.location == "Clareira de Treino em Hesiod"

    # Rolagem numérica curta de 1 dígito ("7") resolve o ataque normalmente
    r_single = await process_npc_turn("7", user_info={"session_id": session_id, "telegram_id": "101"})
    assert "Dungeon Master:" in r_single
    assert "Yarrow" in r_single
    assert "atacou" in r_single
