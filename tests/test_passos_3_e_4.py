import pytest
from unittest.mock import AsyncMock, patch
from api.schemas.rpg import GameState, HeroState, MonsterState, NPCState, Message
from api.ai_core.turn_graph import (
    combat_node,
    npc_node,
    tactical_advice_node,
    clean_loomis_speech,
    format_heroes_hud,
    DEFAULT_LOOMIS_PROMPT,
)
from telegram_bot.telegram_service import format_to_telegram_html


def test_clean_loomis_speech_removes_third_person_rubrics():
    """Passo 4: Garante que rubricas narrativas em 3ª pessoa e prefixos indesejados são expurgados."""
    raw = 'Loomis: *loomis cospe no chão* "Bom golpe, recruta! *ele sorri com orgulho* Não baixe a guarda!"'
    cleaned = clean_loomis_speech(raw)
    assert "loomis cospe" not in cleaned.lower()
    assert "ele sorri" not in cleaned.lower()
    assert "Loomis:" not in cleaned
    assert "Bom golpe, recruta!" in cleaned
    assert "Não baixe a guarda!" in cleaned


def test_clean_loomis_speech_converts_markdown_to_html():
    """Passo 4: Garante que markdown remanescente vira tags HTML do Telegram sem aspas duplicadas."""
    raw = '🗣️ **Loomis**: Excelente investida! Use **Espada Larga** e role `d20`.'
    cleaned = clean_loomis_speech(raw)
    assert "**" not in cleaned
    assert "<b>Espada Larga</b>" in cleaned
    assert "<code>d20</code>" in cleaned


@pytest.mark.asyncio
async def test_passo_3_combat_hud_hit_and_counter_attack():
    """Passo 3: Template fixo de combate com acerto, contra-ataque e HUD da arena."""
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

    hud = res["combat_hud"]
    assert "🎲 <b>Dungeon Master:</b>" in hud
    assert "• <b>Jorick</b> atacou <b>Bullette Faminto</b> com Espada Larga!" in hud
    assert "• Rolagem: d20 [19] + 4 = 23 vs CA 15 (ACERTOU!)" in hud
    assert "• Dano: 1 ponto." in hud

    assert "⚔️ <b>Contra-ataque da Fera:</b>" in hud
    assert "• <b>Bullette Faminto</b> atacou <b>Jorick</b> com Escavar e Engolir!" in hud

    assert "📊 <b>Arena de Hesiod:</b>" in hud
    assert "Bullette Faminto" in hud
    assert "Jorick" in hud
    assert "• Status: <i>Fera ferida e furiosa na arena!</i>" in hud


@pytest.mark.asyncio
async def test_passo_3_combat_hud_missing_d20():
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

    hud = res["combat_hud"]
    assert "🎲 <b>Dungeon Master:</b>" in hud
    assert "nenhuma rolagem de dado foi informada" in hud
    assert "<b>d20 físico</b>" in hud
    assert "📊 <b>Arena de Hesiod:</b>" in hud
    assert "Aguardando rolagem física do d20..." in hud
    assert "[PENDENTE D20]" in res["last_context"]


@pytest.mark.asyncio
async def test_passo_3_combat_hud_monster_defeated_omits_counter_attack():
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

    hud = res["combat_hud"]
    assert "<b>Bullette Faminto</b> foi derrotado!" in hud
    # Monstro derrotado não contra-ataca
    assert "⚔️ <b>Contra-ataque da Fera:</b>" not in hud
    assert "[MONSTRO DERROTADO]" in hud
    assert "[MONSTRO DERROTADO]" in res["last_context"]


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
        combat_hud="🎲 <b>Dungeon Master:</b>\n• Teste de combate\n\n📊 <b>Arena de Hesiod:</b>\n• Fera ativa",
        last_context="Fatos do Turno: A fera continua VIVA e ameaçadora (HP: 6/8)!",
        recent_messages=[
            Message(sender="Jogador", content="ataco com 19", role="user")
        ],
    )

    captured_prompt = {}

    async def mock_generate_reply(message, system_prompt, **kwargs):
        captured_prompt["system_prompt"] = system_prompt
        captured_prompt["message"] = message
        return '*loomis cospe no chão* "Excelente golpe! A carapaça dele ainda é dura, continue atacando!"'

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        res = await npc_node(state)

    # Verifica trava rígida no system prompt
    sys_prompt = captured_prompt["system_prompt"]
    assert "[REGRAS INQUEBRÁVEIS DE SEGURANÇA E PERSONA - LOOMIS]" in sys_prompt
    assert "Você NUNCA decide se um monstro morreu" in sys_prompt
    assert "[MONSTRO DERROTADO]" in sys_prompt
    assert "terminantemente PROIBIDO gerar rubricas narrativas em 3ª pessoa" in sys_prompt

    # Verifica mensagem final gerada para o Telegram
    final_message = res["recent_messages"][-1].content
    assert "🎲 <b>Dungeon Master:</b>" in final_message
    assert "📊 <b>Arena de Hesiod:</b>" in final_message
    assert "🗣️ <b>Loomis:</b>" in final_message
    assert '"Excelente golpe! A carapaça dele ainda é dura, continue atacando!"' in final_message
    assert "loomis cospe" not in final_message


def test_telegram_html_formatting():
    """Verifica conversão de markdown e proteção de tags HTML válidas."""
    raw = "🎲 **Dungeon Master:**\n• *Ataque* com 1 < 3 & `d20`."
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
    assert "🎲 <b>Dungeon Master:</b>" in last_msg
    assert "• <b>Jorick</b> atacou <b>Bullette Faminto</b> com Espada Larga!" in last_msg
    assert "• Rolagem: d20 [19] + 4 = 23 vs CA 15 (ACERTOU!)" in last_msg
    assert "⚔️ <b>Contra-ataque da Fera:</b>" in last_msg
    assert "📊 <b>Arena de Hesiod:</b>" in last_msg
    assert "🗣️ <b>Loomis:</b>" in last_msg
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
    assert "🎲 <b>Dungeon Master:</b>" not in last_msg
    assert "⚔️ <b>Contra-ataque da Fera:</b>" not in last_msg
    assert "🗣️ <b>Loomis:</b>" in last_msg
    assert '"Mire na barriga! A carapaça superior resiste a quase tudo, mas o ventre é vulnerável!"' in last_msg

