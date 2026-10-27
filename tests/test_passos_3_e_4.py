import pytest
from unittest.mock import AsyncMock, patch
from api.schemas.rpg import GameState, HeroState, MonsterState, NPCState, Message
from api.ai_core.turn_graph import (
    combat_node,
    npc_node,
    tactical_advice_node,
)
from telegram_bot.telegram_service import format_to_telegram_html


@pytest.mark.asyncio
async def test_passo_3_combat_summary_hit_and_counter_attack():
    """Passo 3: Template fixo de combate com acerto, contra-ataque e estado da arena."""
    hero = HeroState(
        player_id="p1",
        name="Jorick",
        class_name="Guerreiro Humano",
        hp=5,
        max_hp=5,
        ac=13,
        attack_bonus=4,
        attack_name="Espada Larga",
    )
    monster = MonsterState(
        name="Bullette Faminto",
        cage_number=1,
        hp=8,
        max_hp=8,
        ac=15,
        attack_bonus=4,
        attack_name="Escavar e Engolir",
    )
    state = GameState(
        session_id="test_session",
        players=[hero],
        monsters=[monster],
        recent_messages=[
            Message(sender="Jogador", content="ataco com 19", role="user")
        ],
    )

    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=19)):
        res = await combat_node(state)

    summary = res["last_context"]
    assert "<b>Dungeon Master:</b>" in summary
    assert "• <b>Jorick</b> atacou <b>Bullette Faminto</b> com Espada Larga!" in summary
    assert "• Rolagem: d20 [19] + 4 = 23 vs CA 15 (ACERTOU!)" in summary
    assert "• Dano: 1 ponto." in summary

    assert "<b>Contra-ataque da Fera:</b>" in summary
    assert "• <b>Bullette Faminto</b> atacou <b>Jorick</b> com Escavar e Engolir!" in summary

    assert "<b>Arena de Hesiod:</b>" in summary
    assert "Bullette Faminto" in summary
    assert "Jorick" in summary
    assert "• Status: <i>Fera ferida e furiosa na arena!</i>" in summary


@pytest.mark.asyncio
async def test_passo_3_combat_missing_d20():
    """Passo 3: Quando o d20 não é informado, Dungeon Master orienta a rolagem física."""
    hero = HeroState(
        player_id="p1",
        name="Jorick",
        class_name="Guerreiro Humano",
        hp=5,
        max_hp=5,
        ac=13,
    )
    monster = MonsterState(
        name="Bullette Faminto",
        cage_number=1,
        hp=8,
        max_hp=8,
        ac=15,
    )
    state = GameState(
        session_id="test_session",
        players=[hero],
        monsters=[monster],
        recent_messages=[
            Message(sender="Jogador", content="vou atacar a fera com a espada", role="user")
        ],
    )

    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=None)):
        res = await combat_node(state)

    summary = res["last_context"]
    assert "<b>Dungeon Master:</b>" in summary
    assert "nenhuma rolagem de dado foi informada" in summary
    assert "<b>d20 físico</b>" in summary
    assert "<b>Arena de Hesiod:</b>" in summary
    assert "Aguardando rolagem física do d20..." in summary
    assert "[PENDENTE D20]" in summary


@pytest.mark.asyncio
async def test_passo_3_combat_monster_defeated_omits_counter_attack():
    """Passo 3: Quando a fera morre, não há contra-ataque e a vitória/próxima jaula é reportada."""
    hero = HeroState(
        player_id="p1",
        name="Bet",
        class_name="Maga Elfa",
        hp=4,
        max_hp=4,
        ac=7,
        attack_bonus=7,
        attack_name="Bola de Fogo",
    )
    monster = MonsterState(
        name="Bullette Faminto",
        cage_number=1,
        hp=1,
        max_hp=8,
        ac=15,
    )
    state = GameState(
        session_id="test_session",
        players=[hero],
        monsters=[monster],
        recent_messages=[
            Message(sender="Jogador", content="ataco com 15", role="user")
        ],
    )

    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=15)):
        res = await combat_node(state)

    summary = res["last_context"]
    assert "<b>Bullette Faminto</b> foi derrotado!" in summary
    # Monstro derrotado não contra-ataca
    assert "<b>Contra-ataque da Fera:</b>" not in summary
    assert "[MONSTRO DERROTADO]" in summary


@pytest.mark.asyncio
async def test_passo_4_npc_node_persona_and_anti_hallucination():
    """Passo 4: Verifica a trava anti-alucinação no prompt e a composição da resposta com voz do Loomis."""
    hero = HeroState(
        player_id="p1",
        name="Jorick",
        class_name="Guerreiro Humano",
        hp=4,
        max_hp=5,
        ac=13,
    )
    state = GameState(
        session_id="test_session",
        players=[hero],
        last_context="<b>Dungeon Master:</b>\n• Teste de combate\n\n<b>Arena de Hesiod:</b>\n• Fera ativa",
        recent_messages=[
            Message(sender="Jogador", content="ataco com 19", role="user")
        ],
    )

    captured_prompt = {}

    async def mock_generate_reply(message, system_prompt, **kwargs):
        captured_prompt["system_prompt"] = system_prompt
        captured_prompt["message"] = message
        return '"Excelente golpe! A carapaça dele ainda é dura, continue atacando!"'

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        res = await npc_node(state)

    sys_prompt = captured_prompt["system_prompt"]
    assert "[REGRAS DE PERSONA - LOOMIS]" in sys_prompt
    assert "Você NUNCA decide se um monstro morreu" in sys_prompt
    assert "[MONSTRO DERROTADO]" in sys_prompt

    # Verifica mensagem final gerada para o Telegram
    final_message = res["recent_messages"][-1].content
    assert "<b>Dungeon Master:</b>" in final_message
    assert "<b>Arena de Hesiod:</b>" in final_message
    assert "<b>Loomis:</b>" in final_message
    assert '"Excelente golpe! A carapaça dele ainda é dura, continue atacando!"' in final_message


def test_telegram_html_formatting():
    """Verifica conversão de markdown e proteção de tags HTML válidas."""
    raw = "**Dungeon Master:**\n• *Ataque* com 1 < 3 & `d20`."
    formatted = format_to_telegram_html(raw)
    assert "<b>Dungeon Master:</b>" in formatted
    assert "<i>Ataque</i>" in formatted
    assert "<code>d20</code>" in formatted
    assert "&lt;" in formatted
    assert "&amp;" in formatted


@pytest.mark.asyncio
async def test_end_to_end_turn_graph_combat():
    """Garante a execução completa do LangGraph com a bifurcação de combate."""
    from api.ai_core.turn_graph import turn_graph

    hero = HeroState(
        player_id="p1",
        name="Jorick",
        class_name="Guerreiro Humano",
        hp=5,
        max_hp=5,
        ac=13,
        attack_bonus=4,
        attack_name="Espada Larga",
    )
    monster = MonsterState(
        name="Bullette Faminto",
        cage_number=1,
        hp=8,
        max_hp=8,
        ac=15,
        attack_bonus=4,
        attack_name="Escavar e Engolir",
    )
    state = GameState(
        session_id="test_e2e_combat",
        players=[hero],
        monsters=[monster],
        recent_messages=[
            Message(sender="Jogador", content="dou um golpe forte com 19 no dado", role="user")
        ],
    )

    async def mock_generate_reply(message, system_prompt, **kwargs):
        if "classificador de ações" in system_prompt.lower():
            return "combat"
        if "extraia o valor da rolagem" in system_prompt.lower():
            return "19"
        return "Firme o passo, recruta! Bom impacto na carapaça!"

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        result = await turn_graph.ainvoke(state)

    final_state = GameState(**result) if isinstance(result, dict) else result
    last_msg = final_state.recent_messages[-1].content
    assert "<b>Dungeon Master:</b>" in last_msg
    assert "• <b>Jorick</b> atacou <b>Bullette Faminto</b> com Espada Larga!" in last_msg
    assert "• Rolagem: d20 [19] + 4 = 23 vs CA 15 (ACERTOU!)" in last_msg
    assert "<b>Contra-ataque da Fera:</b>" in last_msg
    assert "<b>Arena de Hesiod:</b>" in last_msg
    assert "<b>Loomis:</b>" in last_msg
    assert '"Firme o passo, recruta! Bom impacto na carapaça!"' in last_msg


@pytest.mark.asyncio
async def test_end_to_end_turn_graph_tactical_advice():
    """Garante que conselho tático não gera HUD mecânico de combate e preserva a voz do Loomis."""
    from api.ai_core.turn_graph import turn_graph

    hero = HeroState(
        player_id="p1",
        name="Jorick",
        class_name="Guerreiro Humano",
        hp=5,
        max_hp=5,
        ac=13,
    )
    monster = MonsterState(
        name="Bullette Faminto",
        cage_number=1,
        hp=8,
        max_hp=8,
        ac=15,
    )
    state = GameState(
        session_id="test_e2e_advice",
        players=[hero],
        monsters=[monster],
        recent_messages=[
            Message(sender="Jogador", content="Loomis, quais são os pontos fracos dessa criatura?", role="user")
        ],
    )

    async def mock_generate_reply(message, system_prompt, **kwargs):
        if "classificador de ações" in system_prompt.lower():
            return "tactical_advice"
        return "Mire na barriga! A carapaça superior resiste a quase tudo, mas o ventre é vulnerável!"

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        result = await turn_graph.ainvoke(state)

    final_state = GameState(**result) if isinstance(result, dict) else result
    last_msg = final_state.recent_messages[-1].content
    # Em dica tática não deve ter bloco de ataque ou rolagem mecânica
    assert "<b>Dungeon Master:</b>" not in last_msg
    assert "<b>Contra-ataque da Fera:</b>" not in last_msg
    assert "<b>Loomis:</b>" in last_msg
    assert '"Mire na barriga! A carapaça superior resiste a quase tudo, mas o ventre é vulnerável!"' in last_msg

