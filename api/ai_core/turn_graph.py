import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from api.schemas.rpg import GameState, Message
from llm_gateway.client import LLMClient
from api.motor_rpg.motor_rpg import resolve_hero_attack, resolve_monster_attack, get_cage_monster

logger = logging.getLogger(__name__)
llm_client = LLMClient()


async def extract_d20(text: str) -> int | None:
    """Extrai a rolagem física de um d20 (1 a 20) informada pelo jogador via LLM."""
    if not text.strip():
        return None
    try:
        response = await llm_client.generate_reply(
            message=text,
            system_prompt=(
                "Extraia o valor da rolagem de dado d20 (número de 1 a 20) mencionado pelo jogador.\n"
                "Exemplos:\n"
                "- 'ataco com 19' -> 19\n"
                "- 'rolei 15' -> 15\n"
                "- 'deu 20 no dado' -> 20\n"
                "- 'dou um golpe com minha espada' -> null\n"
                "Responda estritamente APENAS o número inteiro ou 'null'."
            ),
            temperature=0.0,
            max_tokens=10,
        )
        cleaned = response.strip()
        if cleaned.isdigit() and 1 <= int(cleaned) <= 20:
            return int(cleaned)
    except Exception as e:
        logger.warning(f"Falha ao extrair d20 via LLM: {e}")
    return None


async def classify_intent(text: str) -> str:
    """Classifica a intenção da mensagem via LLM ('combat' ou 'tactical_advice')."""
    if not text.strip():
        return "tactical_advice"

    prompt = (
        "Você é o classificador de ações de um RPG de mesa textual.\n"
        "Analise a mensagem do jogador e decida se a ação é de COMBATE (atacar, golpear, atirar flecha, magia ofensiva, rolar dados de ataque) "
        "ou se é CONSELHO TÁTICO / CONVERSA (pedir dica, perguntar fraquezas, tirar dúvidas, conversar com o treinador).\n"
        "Responda APENAS 'combat' ou 'tactical_advice'."
    )
    try:
        response = await llm_client.generate_reply(
            message=text,
            system_prompt=prompt,
            temperature=0.0,
            max_tokens=10,
        )
        decision = response.strip().lower()
        if "combat" in decision:
            return "combat"
        return "tactical_advice"
    except Exception as e:
        logger.warning(f"Falha ao classificar intenção via LLM ({e}), direcionando para tactical_advice.")
        return "tactical_advice"


def tactical_advice_node(state: GameState) -> dict:
    """Nó para preparar conselho pedagógico ou dica tática sobre o monstro atual.

    Ação Livre: Não consome turno nem rotaciona a lista de jogadores.
    """
    logger.info("Executando nó de conselho tático...")
    hero = state.players[0] if state.players else None
    monster = state.monsters[0] if state.monsters else None

    context_parts: list[str] = [
        "Ação Livre (Conselho Tático): O recruta está pedindo orientação ou conversando."
    ]

    if hero:
        context_parts.append(
            f"Recruta ativo: {hero.name} ({hero.class_name}). Poder especial: '{hero.special_power}'."
        )

    if monster and not monster.is_defeated:
        abilities_str = ", ".join(monster.abilities) if monster.abilities else "nenhuma habilidade incomum"
        context_parts.append(
            f"Fera na arena: {monster.name} (Jaula {monster.cage_number}, CA {monster.ac}, HP {monster.hp}/{monster.max_hp}). "
            f"Habilidades da criatura: {abilities_str}."
        )
        context_parts.append(
            "Instrução para Loomis: Ofereça uma dica tática enérgica e prática explicando como aproveitar "
            "o poder especial do recruta contra os pontos fracos da criatura, incentivando o próximo ataque."
        )
    elif state.is_victory:
        context_parts.append("Todas as jaulas foram superadas! Parabenize os novos Heróis de Hesiod!")

    last_context = "\n".join(context_parts)
    state.last_context = last_context
    return {"last_context": last_context}


async def combat_node(state: GameState) -> dict:
    """Nó para resolução determinística de combate e rolagem de dados."""
    logger.info("Executando nó de combate...")

    last_user_message = ""
    for msg in reversed(state.recent_messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    d20 = await extract_d20(last_user_message)

    # Se o d20 não foi informado: sinaliza para Loomis solicitar a rolagem física
    if d20 is None:
        state.last_context = (
            "O herói declarou um ataque, mas NÃO informou o resultado da rolagem física do d20 na mesa! "
            "Loomis deve cobrar com energia e autoridade que o recruta jogue seu d20 físico "
            "e informe o número tirado para definir o golpe."
        )
        return {"last_context": state.last_context}

    if not state.players or not state.monsters:
        state.last_context = "Arena vazia ou sem heróis ativos para combate."
        return {"last_context": state.last_context}

    hero = state.players[0]
    monster = state.monsters[0]

    # 1. Ataque do Herói
    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    summary_parts = [hero_res.narrative_summary]

    # 2. Gatilho Loomis: Monstro em 50% de HP ou menos (se só houver 1 na arena e nenhum herói caído)
    has_fallen_hero = any(h.is_unconscious for h in state.players)
    if (
        monster.is_half_hp_or_less
        and len([m for m in state.monsters if not m.is_defeated]) == 1
        and monster.cage_number < 4
        and not has_fallen_hero
    ):
        next_cage = monster.cage_number + 1
        new_beast = get_cage_monster(next_cage)
        state.monsters.append(new_beast)
        summary_parts.append(
            f"Gatilho Loomis: {monster.name} caiu para metade da vida! "
            f"Loomis destranca a Jaula {next_cage} e {new_beast.name} entra na arena!"
        )

    # 3. Derrota do Monstro e transição entre combates
    if monster.is_defeated:
        undefeated = [m for m in state.monsters if not m.is_defeated]
        if undefeated:
            state.monsters.remove(undefeated[0])
            state.monsters.insert(0, undefeated[0])
            summary_parts.append(
                f"{monster.name} foi derrotado! O próximo alvo na arena é {state.monsters[0].name}!"
            )
        else:
            # Todos os monstros derrotados: fim da luta! Loomis cura quem tem <= 2 HP
            healed = []
            for h in state.players:
                if h.hp <= 2:
                    h.restore_full_hp()
                    healed.append(h.name)

            if healed:
                summary_parts.append(
                    f"Fim do combate! Loomis distribui a poção de menta e limão: "
                    f"{', '.join(healed)} recuperaram vida máxima!"
                )

            if monster.cage_number >= 4:
                state.is_victory = True
                summary_parts.append("Vitória! Todas as 4 jaulas foram superadas! Os recrutas são Heróis de Hesiod!")
            else:
                next_cage = monster.cage_number + 1
                next_beast = get_cage_monster(next_cage)
                state.monsters = [next_beast]
                summary_parts.append(f"Loomis abre a Jaula {next_cage}: {next_beast.name} avança faminto!")

    # 4. Contra-ataque da Fera (se ainda ativa e combate não encerrado)
    if state.monsters and not state.monsters[0].is_defeated and not state.is_victory:
        active_beast = state.monsters[0]
        conscious = [h for h in state.players if not h.is_unconscious]
        if conscious:
            # Monstro mira no herói consciente com maior HP
            target_hero = max(conscious, key=lambda h: h.hp)
            monster_res = resolve_monster_attack(active_beast, target_hero)
            summary_parts.append(monster_res.narrative_summary)

    # 5. Rotaciona a iniciativa dos heróis
    state.rotate_players()

    last_context = "\n".join(summary_parts)
    state.last_context = last_context
    return {
        "last_context": last_context,
        "players": state.players,
        "monsters": state.monsters,
        "is_victory": state.is_victory,
        "recent_messages": state.recent_messages,
    }


async def npc_node(state: GameState) -> dict:
    """Nó principal de narração e diálogo do NPC Loomis em primeira pessoa."""
    last_user_message = ""
    for msg in reversed(state.recent_messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    npc_prompt = (
        state.npcs[0].system_prompt
        if state.npcs and state.npcs[0].system_prompt
        else ""
    )

    format_instructions = (
        "\n\n[DIRETRIZ DE FORMATAÇÃO]:\n"
        "- Responda formatando seu texto exclusivamente com tags HTML aceitas pelo Telegram (ex: <b>negrito</b>, <i>itálico</i>, <code>código</code>).\n"
        "- NUNCA use Markdown (como **, *, _, ou ### para títulos).\n"
        "- Fale sempre em primeira pessoa como Loomis, de forma concisa e direta."
    )
    effective_system_prompt = (npc_prompt + format_instructions).strip()

    prompt_context = (
        f"Contexto do Treino e Regras:\n{state.last_context}\n\nMensagem do jogador: {last_user_message}"
        if state.last_context
        else last_user_message
    )

    logger.info(f"Gerando resposta do Loomis via LLM para: '{prompt_context}'")
    resposta_texto = await llm_client.generate_reply(
        message=prompt_context,
        system_prompt=effective_system_prompt,
    )

    npc_message = Message(
        sender="Loomis",
        content=resposta_texto,
        role="assistant",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    state.recent_messages.append(npc_message)

    return {
        "recent_messages": state.recent_messages,
        "last_context": state.last_context,
    }


async def route_intent(state: GameState) -> str:
    """Roteia o fluxo entre combate e dica tática chamando a classificação."""
    last_user_message = ""
    for msg in reversed(state.recent_messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    return await classify_intent(last_user_message)


def build_turn_graph():
    """Compila e retorna o fluxo do LangGraph para o ciclo de turno."""
    workflow = StateGraph(GameState)

    # Registro dos nós
    workflow.add_node("combat", combat_node)
    workflow.add_node("tactical_advice", tactical_advice_node)
    workflow.add_node("npc", npc_node)

    # Bifurcação direta a partir do START
    workflow.add_conditional_edges(
        START,
        route_intent,
        {
            "combat": "combat",
            "tactical_advice": "tactical_advice",
        },
    )
    workflow.add_edge("combat", "npc")
    workflow.add_edge("tactical_advice", "npc")
    workflow.add_edge("npc", END)

    return workflow.compile()


turn_graph = build_turn_graph()