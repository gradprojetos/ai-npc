import pytest
from unittest.mock import AsyncMock, patch
from api.schemas.rpg import GameState, HeroState, MonsterState, NPCState, Message
from api.ai_core.turn_graph import (
    classify_intent,
    exploration_node,
    tactical_advice_node,
    combat_node,
    npc_node,
    route_intent,
    _exploration_counters,
    _last_monster_targets,
    _round_buffers,
)
from api.motor_rpg.session_service import finish_recruiting_for_session


@pytest.mark.asyncio
async def test_classify_intent_three_modes():
    """Valida o classificador de intenção reconhecendo os 3 modos de jogo."""
    # 1. Combate (ataque ou prontidão)
    assert await classify_intent("ataco com 18 no d20") == "combat"
    assert await classify_intent("estamos prontos para a fera") == "combat"
    assert await classify_intent("puxa a alavanca") == "combat"

    # 2. Conselho Tático
    assert await classify_intent("Loomis, qual o ponto fraco desse monstro?") == "tactical_advice"
    assert await classify_intent("como uso o poder da minha carta?") == "tactical_advice"

    # 3. Exploração e Lore
    assert await classify_intent("O que tem dentro daquele caldeirão borbulhante?") == "exploration"
    assert await classify_intent("Me conte mais sobre a história de Hesiod") == "exploration"


def test_exploration_progression_and_forced_trigger():
    """Testa a evolução do diálogo de exploração e o gatilho forçado de combate na 7ª mensagem."""
    session_id = "test_exp_session"
    _exploration_counters[session_id] = 0

    state = GameState(
        session_id=session_id,
        location="Clareira de Treino em Hesiod",
        players=[HeroState(player_id="p1", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)],
        monsters=[MonsterState(name="Bullette Faminto", cage_number=1, hp=8, max_hp=8, ac=15)],
    )

    # Mensagens 1 a 3: Acolhedor
    res1 = exploration_node(state)
    assert "Loomis acolhedor" in res1["last_context"]

    # Mensagens 4 a 6: Impaciente
    _exploration_counters[session_id] = 3
    res4 = exploration_node(state)
    assert "Loomis impaciente" in res4["last_context"]

    # Mensagem 7: Gatilho Forçado
    _exploration_counters[session_id] = 6
    res7 = exploration_node(state)
    assert "Gatilho Forçado de Combate" in res7["last_context"]
    assert "Jaula 1 Aberta" in state.location


@pytest.mark.asyncio
async def test_anti_dispersion_lock_during_combat():
    """Garante que tentativa de exploração livre durante combate ativo seja interceptada."""
    state = GameState(
        session_id="test_lock_session",
        location="Arena de Hesiod — Jaula 1 Aberta",
        players=[HeroState(player_id="p1", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)],
        monsters=[MonsterState(name="Bullette Faminto", cage_number=1, hp=8, max_hp=8, ac=15)],
        recent_messages=[
            Message(sender="Jogador", content="vou passear até a cabana e colher flores", role="user")
        ],
    )

    with patch("api.ai_core.turn_graph.classify_intent", new=AsyncMock(return_value="exploration")):
        routed = await route_intent(state)

    # Redirecionado para tactical_advice pela trava anti-dispersão
    assert routed == "tactical_advice"

    res = tactical_advice_node(state)
    assert "Alerta Anti-Dispersão" in res["last_context"]
    assert "não é hora de passear" in res["last_context"]


@pytest.mark.asyncio
async def test_selective_memory_exploration_vs_combat():
    """Verifica que o modo exploração inclui histórico recente de diálogo e combate mantém-se enxuto."""
    captured_messages = []

    async def mock_generate_reply(message, system_prompt, **kwargs):
        captured_messages.append(message)
        return "Firmeza, recrutas!"

    # 1. Modo Exploração
    exp_state = GameState(
        session_id="test_mem_exp",
        players=[HeroState(player_id="p1", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)],
        last_context="Ação Livre (Roleplay e Exploração na Clareira de Treino): Loomis acolhedor",
        recent_messages=[
            Message(sender="Jorick", content="O que é esta cabana?", role="user"),
            Message(sender="Loomis", content="É meu refúgio e depósito de armas.", role="assistant"),
            Message(sender="Jorick", content="E aquele caldeirão?", role="user"),
        ],
    )

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        await npc_node(exp_state)

    assert "Diálogo recente:" in captured_messages[-1]
    assert "O que é esta cabana?" in captured_messages[-1]

    # 2. Modo Combate
    combat_state = GameState(
        session_id="test_mem_combat",
        players=[HeroState(player_id="p1", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)],
        last_context="<b>Dungeon Master:</b>\n• Jorick acertou 1 de dano!",
        recent_messages=[
            Message(sender="Jorick", content="ataco com 17", role="user"),
        ],
    )

    with patch("api.ai_core.turn_graph.llm_client.generate_reply", side_effect=mock_generate_reply):
        await npc_node(combat_state)

    assert "Diálogo recente:" not in captured_messages[-1]
    assert "<b>Dungeon Master:</b>" in captured_messages[-1]


@pytest.mark.asyncio
async def test_acting_hero_identification_by_sender():
    """Garante que o ataque seja debitado no nome do herói correspondente ao remetente da mensagem."""
    jorick = HeroState(player_id="101", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)
    raen = HeroState(player_id="202", name="Raen", class_name="Bárbara", hp=7, max_hp=7, ac=9, attack_bonus=5)
    monster = MonsterState(name="Bullette Faminto", cage_number=1, hp=8, max_hp=8, ac=15)

    _round_buffers["test_hero_sender"] = []

    state = GameState(
        session_id="test_hero_sender",
        players=[jorick, raen],
        monsters=[monster],
        recent_messages=[
            Message(sender="202", content="ataco com 18", role="user")
        ],
    )

    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=18)):
        await combat_node(state)

    round_actions = _round_buffers.get("test_hero_sender", [])
    assert any("Raen" in act for act in round_actions)
    assert not any("Jorick" in act for act in round_actions)


@pytest.mark.asyncio
async def test_monster_counter_attack_target_alternation():
    """Garante a regra canônica: criatura não foca no mesmo alvo duas rodadas seguidas."""
    raen = HeroState(player_id="h1", name="Raen", class_name="Bárbara", hp=7, max_hp=7, ac=9)
    jorick = HeroState(player_id="h2", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)
    monster = MonsterState(name="Bullette Faminto", cage_number=1, hp=8, max_hp=8, ac=15)

    session_id = "test_alternation_session"
    _last_monster_targets[session_id] = None
    _round_buffers[session_id] = []

    state = GameState(
        session_id=session_id,
        players=[raen, jorick],
        monsters=[monster],
        recent_messages=[
            Message(sender="h1", content="ataco com 18", role="user"),
        ],
    )

    # Simula rodada completa com 1 herói ativo para disparar contra-ataque
    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=18)):
        state.players = [raen]  # 1 jogador para fechar a rodada
        res1 = await combat_node(state)

    # 1ª Rodada: Maior HP é Raen (7) -> Raen é o alvo
    assert "contra-atacou <b>Raen</b>" in res1["last_context"]
    assert _last_monster_targets[session_id] == "h1"

    # 2ª Rodada: Raen ainda tem mais vida que Jorick, mas foi atingida na rodada anterior
    raen.hp = 6  # Raen 6 HP vs Jorick 5 HP
    state.players = [jorick]
    state.recent_messages = [Message(sender="h2", content="ataco com 15", role="user")]

    with patch("api.ai_core.turn_graph.extract_d20", new=AsyncMock(return_value=15)):
        res2 = await combat_node(state)

    # Deve alternar para Jorick mesmo Raen tendo 6 HP > 5 HP de Jorick
    assert "contra-atacou <b>Jorick</b>" in res2["last_context"]
    assert _last_monster_targets[session_id] == "h2"


def test_onboarding_done_does_not_open_cage():
    """Garante que /done apresenta o prólogo na cabana e Loomis sem abrir a Jaula 1 imediatamente."""
    session_id = "test_done_session"
    hero = HeroState(player_id="u1", name="Jorick", class_name="Guerreiro", hp=5, max_hp=5, ac=13)

    state = GameState(
        session_id=session_id,
        players=[hero],
        monsters=[MonsterState(name="Bullette Faminto", cage_number=1, hp=8, max_hp=8, ac=15)],
        is_recruiting=True,
    )

    with patch("api.motor_rpg.session_service.get_or_create_session_state", return_value=state):
        with patch("api.motor_rpg.session_service.persist_session_state_to_db", return_value=True):
            ok, briefing, final_state = finish_recruiting_for_session(session_id)

    assert ok is True
    assert final_state.is_recruiting is False
    assert "Dungeon Master:" in briefing
    assert "Loomis:" in briefing
    assert "Três meses de suor nesta vila levaram a este dia" in briefing
    assert "quando estiverem prontos para a primeira fera, me digam 'estamos prontos'" in briefing
    # Não deve dizer que a jaula abriu de imediato
    assert "Jaula 1 Aberta!" not in briefing
