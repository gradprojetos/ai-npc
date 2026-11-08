import pytest

from api.ai_core.orchestrator import process_npc_turn
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    get_or_create_session_state,
    reset_game_session,
    select_hero_for_player,
)
from tests.recorder import clear_test_output, log_test_turn

ALL_PLAYERS = [
    ("101", "Isaac", 1, "Evindol"),
    ("202", "Pedro", 2, "Raen"),
    ("303", "Lucas", 3, "Jorick"),
    ("404", "Marina", 4, "Yarrow"),
]


async def execute_full_campaign_until_victory(session_id: str, players_config: list[tuple[str, str, int, str]], log_file: str):
    """Executa uma campanha completa do ZERO à VITÓRIA (Jaulas 1 a 4) 100% real com LLM."""
    reset_game_session(session_id)
    clear_test_output(log_file)

    num_players = len(players_config)
    log_test_turn(log_file, "INÍCIO DA CAMPANHA", "Sistema", f"Iniciando campanha para {num_players} jogador(es)", f"Jogadores: {[p[1] for p in players_config]}")

    # 1. Alistamento de heróis (/select)
    for p_id, p_name, card_num, hero_name in players_config:
        ok, msg, state = select_hero_for_player(session_id, player_id=p_id, player_name=p_name, choice=card_num)
        assert ok is True
        log_test_turn(log_file, f"Alistamento - {p_name}", p_name, f"/select {card_num}", msg)

    assert len(state.players) == num_players

    # 2. Finaliza recrutamento (/done)
    leader_name = players_config[0][1]
    ok_done, briefing, state = finish_recruiting_for_session(session_id)
    assert ok_done is True
    assert state.is_recruiting is False
    log_test_turn(log_file, "Recrutamento Concluído", leader_name, "/done", briefing)

    # 3. Transição voluntária para combate (abertura da Jaula 1)
    leader_id = players_config[0][0]
    r_ready = await process_npc_turn(
        user_message="Estamos prontos para a arena, Loomis! Puxe a alavanca!",
        user_info={"session_id": session_id, "telegram_id": leader_id, "first_name": leader_name},
    )
    assert "Dungeon Master:" in r_ready
    assert "Jaula 1 foi aberta" in r_ready
    assert "Bullette Faminto" in r_ready
    log_test_turn(log_file, "Abertura da Jaula 1", leader_name, "Estamos prontos para a arena, Loomis! Puxe a alavanca!", r_ready)

    # 4. Ciclo de Combate Rodada a Rodada até a Vitória Final
    max_rounds = 35
    victory_reached = False
    last_closing_reply = ""

    for round_num in range(1, max_rounds + 1):
        round_entries = []

        # Turnos dos jogadores na rodada (ordem de iniciativa canônica)
        for idx, (p_id, p_name, _, h_name) in enumerate(players_config, start=1):
            is_closing_action = (idx == num_players)
            reply = await process_npc_turn(
                user_message="ataco a fera com 20",
                user_info={"session_id": session_id, "telegram_id": p_id, "first_name": p_name},
            )
            if is_closing_action:
                last_closing_reply = reply
                round_entries.append(f"[{h_name} - FECHA RODADA]: ataco com 20\n{reply}")
            else:
                round_entries.append(f"[{h_name}]: ataco com 20\n{reply}")

        log_test_turn(log_file, f"Rodada {round_num}", f"Ações ({num_players} heróis)", "ataco com 20", "\n---\n".join(round_entries))

        st = get_or_create_session_state(session_id)
        if st.is_victory:
            victory_reached = True
            break

    # 5. Validações da Vitória
    assert victory_reached is True, f"Campanha para {num_players} jogador(es) não atingiu vitória em {max_rounds} rodadas."
    assert "Todas as 4 jaulas foram superadas" in last_closing_reply or "Heróis de Hesiod" in last_closing_reply

    final_st = get_or_create_session_state(session_id)
    assert final_st.is_victory is True
    assert len(final_st.players) == num_players
    defeated_cages = {m.cage_number for m in final_st.monsters if m.is_defeated or m.hp <= 0}
    assert {1, 2, 3, 4}.issubset(defeated_cages)

    log_test_turn(log_file, "VITÓRIA DA CAMPANHA", "Sistema / Loomis", "Fim da Partida", last_closing_reply)
    reset_game_session(session_id)


# =============================================================================
# Campanhas Reais do Zero ao Victory: 1, 2 e 4 Jogadores
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_campaign_1_player_until_victory():
    """Campanha completa do ZERO à VITÓRIA para 1 JOGADOR (Solo: Evindol)."""
    await execute_full_campaign_until_victory(
        session_id="campaign_1p_victory",
        players_config=ALL_PLAYERS[:1],
        log_file="campaign_1_player_victory.log",
    )


@pytest.mark.asyncio
async def test_e2e_campaign_2_players_until_victory():
    """Campanha completa do ZERO à VITÓRIA para 2 JOGADORES (Dupla: Evindol + Raen)."""
    await execute_full_campaign_until_victory(
        session_id="campaign_2p_victory",
        players_config=ALL_PLAYERS[:2],
        log_file="campaign_2_players_victory.log",
    )


@pytest.mark.asyncio
async def test_e2e_campaign_4_players_until_victory():
    """Campanha completa do ZERO à VITÓRIA para 4 JOGADORES (Grupo Cheio: Evindol + Raen + Jorick + Yarrow)."""
    await execute_full_campaign_until_victory(
        session_id="campaign_4p_victory",
        players_config=ALL_PLAYERS[:4],
        log_file="campaign_4_players_victory.log",
    )
