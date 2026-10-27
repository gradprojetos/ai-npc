import pytest
from fastapi.testclient import TestClient

from api.ai_core.orchestrator import process_npc_turn
from api.ai_core.turn_graph import (
    _exploration_counters,
    _last_monster_targets,
    _round_buffers,
)
from api.main import app
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    reset_game_session,
    select_hero_for_player,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_test_state():
    """Limpa estado em memória e banco antes de cada teste."""
    sessions = ["test_coop_e2e", "test_rest_session", "test_full_victory"]
    for s_id in sessions:
        reset_game_session(s_id)
        _round_buffers.pop(s_id, None)
        _last_monster_targets.pop(s_id, None)
        _exploration_counters.pop(s_id, None)
    yield
    for s_id in sessions:
        reset_game_session(s_id)
        _round_buffers.pop(s_id, None)
        _last_monster_targets.pop(s_id, None)
        _exploration_counters.pop(s_id, None)


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
    # Iniciativa canônica: Evindol (#1) antes de Raen (#2)
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
    # A jaula NÃO abre de imediato
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
    # Ação 1: Isaac (Evindol) ataca com 19
    reply_round1_p1 = await process_npc_turn(
        user_message="ataco a fera tirei 19 no dado",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )

    # Rodada ainda aberta aguardando ação de Pedro: não envia resumo de combate
    assert reply_round1_p1 == ""
    assert len(_round_buffers.get(session_id, [])) == 1
    assert "Evindol" in _round_buffers[session_id][0]

    # Ação 2: Pedro (Raen) ataca com 17 -> FECHA A RODADA
    reply_round1_p2 = await process_npc_turn(
        user_message="desfiro um machadada forte com 17",
        user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
    )

    assert "Dungeon Master:" in reply_round1_p2
    assert "Evindol" in reply_round1_p2
    assert "Raen" in reply_round1_p2
    # Contra-ataque: Raen tem 7 HP > Evindol 3 HP -> Monstro foca em Raen
    assert "contra-atacou <b>Raen</b>" in reply_round1_p2
    assert "Loomis:" in reply_round1_p2

    # =========================================================================
    # 6. Rodada 2: Alternância Canônica de Alvo do Monstro
    # =========================================================================
    # Isaac ataca
    await process_npc_turn(
        user_message="ataco com 18",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )

    # Pedro ataca e fecha a rodada 2
    reply_round2 = await process_npc_turn(
        user_message="golpeio com 16",
        user_info={"session_id": session_id, "telegram_id": "202", "first_name": "Pedro"},
    )

    # Regra canônica: criatura não foca em Raen novamente
    assert "contra-atacou <b>Evindol</b>" in reply_round2


def test_api_rest_endpoints_simulation():
    """Testa os novos endpoints REST (/game/*) simulando clientes HTTP externos sem Telegram."""
    session_id = "test_rest_session"

    # 1. /game/select para Player 1
    resp1 = client.post("/game/select", json={
        "session_id": session_id,
        "player_id": "u1",
        "player_name": "Lucas",
        "choice": 3,
    })
    assert resp1.status_code == 200
    assert resp1.json()["success"] is True
    assert "Jorick" in resp1.json()["message"]

    # 2. /game/done para finalizar recrutamento
    resp_done = client.post("/game/done", json={"session_id": session_id})
    assert resp_done.status_code == 200
    assert resp_done.json()["success"] is True
    assert "Dungeon Master:" in resp_done.json()["message"]

    # 3. /game/state para consultar o GameState
    resp_state = client.get(f"/game/state/{session_id}")
    assert resp_state.status_code == 200
    data = resp_state.json()
    assert data["session_id"] == session_id
    assert len(data["players"]) == 1
    assert data["players"][0]["name"] == "Jorick"

    # 4. /game/message com chamada real de IA
    resp_msg = client.post("/game/message", json={
        "session_id": session_id,
        "player_id": "u1",
        "player_name": "Lucas",
        "message": "Olá Loomis!",
    })
    assert resp_msg.status_code == 200
    assert "Loomis:" in resp_msg.json()["reply"]

    # 5. /game/reset
    resp_reset = client.post("/game/reset", json={"session_id": session_id})
    assert resp_reset.status_code == 200
    assert resp_reset.json()["success"] is True


@pytest.mark.asyncio
async def test_e2e_full_campaign_until_victory():
    """Simulação ponta a ponta completa de todas as 4 jaulas até a vitória final do grupo."""
    session_id = "test_full_victory"

    # 1. Alistamento de heróis via API REST
    client.post("/game/select", json={"session_id": session_id, "player_id": "101", "player_name": "Isaac", "choice": 1})
    client.post("/game/select", json={"session_id": session_id, "player_id": "202", "player_name": "Pedro", "choice": 2})

    # 2. Finaliza recrutamento
    resp_done = client.post("/game/done", json={"session_id": session_id})
    assert resp_done.status_code == 200

    # 3. Transição para combate
    await process_npc_turn(
        user_message="Estamos prontos para a arena!",
        user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
    )

    # 4. Batalha contínua até derrotar as 4 jaulas e atingir vitória
    max_rounds = 30
    victory_reached = False
    last_reply = ""

    for _ in range(max_rounds):
        # Isaac ataca
        await process_npc_turn(
            user_message="ataco a criatura com 20",
            user_info={"session_id": session_id, "telegram_id": "101", "first_name": "Isaac"},
        )

        # Pedro ataca e fecha a rodada
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
