import pytest
from api.ai_core.orchestrator import process_npc_turn
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    reset_game_session,
    select_hero_for_player,
)
from tests.recorder import clear_test_output, log_test_turn


@pytest.mark.asyncio
async def test_exploration_curiosity_and_potions_without_combat_spoil():
    """Valida perguntas sobre cenário, poções e exploração prolongada sem spoiler de combate nem corte precoce."""
    session_id = "test_edge_exploration"
    log_file = "edge_cases_exploration.log"
    clear_test_output(log_file)
    reset_game_session(session_id)

    select_hero_for_player(session_id, "u1", "Isaac", 3)  # Jorick
    select_hero_for_player(session_id, "u2", "Let", 2)    # Raen
    finish_recruiting_for_session(session_id)

    # 1. Pergunta sobre o que tem na clareira
    r1 = await process_npc_turn("o que tem na clareira?", {"session_id": session_id, "telegram_id": "u1", "first_name": "Isaac"})
    log_test_turn(log_file, "Cenário 1", "Isaac", "o que tem na clareira?", r1)
    assert "Loomis:" in r1
    assert "jaulas" in r1.lower() or "cabana" in r1.lower()

    # 2. Pergunta sobre pessoas ao redor
    r2 = await process_npc_turn("Tem alguém mais aqui perto?", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Cenário 2", "Let", "Tem alguém mais aqui perto?", r2)
    assert "Loomis:" in r2

    # 3. Pergunta sobre poção de cura antes do combate (NÃO deve alucinar combate nem Bullette!)
    r3 = await process_npc_turn("Tem alguma poção de cura?", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Cenário 3 (Poção pré-combate)", "Let", "Tem alguma poção de cura?", r3)
    assert "Loomis:" in r3
    assert "bullette" not in r3.lower(), f"Loomis deu spoil do Bullette antes da jaula abrir: {r3}"
    assert "ácido" not in r3.lower(), f"Loomis alucinou combate com ácido: {r3}"

    # 4. Continuação de conversa sobre a poção (NÃO deve cortar bruscamente no 4º turno com grosseria repetida)
    r4 = await process_npc_turn("Quero saber mais sobre essa poção de menta e limão", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Cenário 4 (Detalhe poção)", "Let", "Quero saber mais sobre essa poção de menta e limão", r4)
    assert "Loomis:" in r4
    assert "amarelar" not in r4.lower(), f"Loomis cortou bruscamente a exploração muito cedo: {r4}"

    # 5. Confirmação de abertura sem papagaio
    r5 = await process_npc_turn("vamos abrir a jaula", {"session_id": session_id, "telegram_id": "u1", "first_name": "Isaac"})
    log_test_turn(log_file, "Cenário 5 (Abertura)", "Isaac", "vamos abrir a jaula", r5)
    assert "Jaula 1 foi aberta" in r5
    assert "Bullette Faminto" in r5


@pytest.mark.asyncio
async def test_in_battle_roleplay_and_tactical_edge_cases():
    """Testa declarações narrativas sem d20 em combate, pedido de poção com vida e coerência de armas."""
    session_id = "test_edge_battle"
    log_file = "edge_cases_battle.log"
    clear_test_output(log_file)
    reset_game_session(session_id)

    select_hero_for_player(session_id, "u1", "Isaac", 3)  # Jorick (Guerreiro, Espada Larga)
    select_hero_for_player(session_id, "u2", "Let", 2)    # Raen (Bárbara, Machado Pesado)
    finish_recruiting_for_session(session_id)

    # Abre combate
    r_open = await process_npc_turn("estamos prontos", {"session_id": session_id, "telegram_id": "u1", "first_name": "Isaac"})
    assert "Jaula 1 foi aberta" in r_open

    # 1. Ataque de Jorick
    r_j1 = await process_npc_turn("ataco com 18", {"session_id": session_id, "telegram_id": "u1", "first_name": "Isaac"})
    log_test_turn(log_file, "Jorick ataca", "Isaac", "ataco com 18", r_j1)
    assert "Próximo a agir:" in r_j1 and "Raen" in r_j1

    # 2. Raen faz roleplay defensivo sem número: "Eu quero segurar minha guarda e defender no meu turno"
    # Deve responder sem alucinar que Raen usa espada ou investida
    r_def = await process_npc_turn("Eu quero segurar minha guarda e defender no meu turno", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Raen tenta defender", "Let", "Eu quero segurar minha guarda e defender no meu turno", r_def)
    assert "espada" not in r_def.lower(), f"Loomis trocou o Machado de Raen por espada: {r_def}"
    assert "investida" not in r_def.lower(), f"Loomis deu o poder do Jorick (investida) para Raen: {r_def}"

    # 3. Raen pede para beber poção em combate com HP cheio
    r_pot = await process_npc_turn("Quero beber minha poção de cura", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Raen pede poção em combate", "Let", "Quero beber minha poção de cura", r_pot)
    assert "espada" not in r_pot.lower(), f"Loomis citou espada para Raen ao falar de poção: {r_pot}"

    # 4. Raen ataca com valor inválido acima de 20
    r_inv = await process_npc_turn("Ataco com 23", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Raen d20 inválido (23)", "Let", "Ataco com 23", r_inv)
    assert "Valor inválido" in r_inv
    assert "1 a 20" in r_inv

    # 5. Raen ataca válido com Machado Pesado
    r_r1 = await process_npc_turn("ataco com 16", {"session_id": session_id, "telegram_id": "u2", "first_name": "Let"})
    log_test_turn(log_file, "Raen ataca válido", "Let", "ataco com 16", r_r1)
    assert "Machado Pesado" in r_r1


@pytest.mark.asyncio
async def test_multi_monster_no_infighting_hallucination():
    """Garante que Loomis nunca narre monstros atacando uns aos outros quando há múltiplas feras na arena."""
    session_id = "test_edge_monsters"
    log_file = "edge_cases_monsters.log"
    clear_test_output(log_file)
    reset_game_session(session_id)

    select_hero_for_player(session_id, "u1", "Isaac", 3)
    select_hero_for_player(session_id, "u2", "Let", 2)
    finish_recruiting_for_session(session_id)

    await process_npc_turn("estamos prontos", {"session_id": session_id, "telegram_id": "u1"})

    # Causa dano crítico no Bullette para forçar Jaula 2 (Beholder) a entrar
    r_crit = await process_npc_turn("ataco com 20", {"session_id": session_id, "telegram_id": "u1"})
    r_turn2 = await process_npc_turn("ataco com 15", {"session_id": session_id, "telegram_id": "u2"})

    full_output = f"{r_crit} {r_turn2}"
    log_test_turn(log_file, "Round com 2 monstros", "Grupo", "Golpes conjuntos", full_output)

    # Loomis não pode narrar fogo amigo entre monstros
    assert "atacou o beholder" not in full_output.lower()
    assert "lançou raios no beholder" not in full_output.lower()
    assert "soprou fogo no beholder" not in full_output.lower()
