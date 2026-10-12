import re
import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from api.schemas.rpg import GameState, Message
from llm_gateway.client import LLMClient
from api.motor_rpg.motor_rpg import resolve_hero_attack, resolve_monster_attack, get_cage_monster, create_hero

logger = logging.getLogger(__name__)
llm_client = LLMClient()

FALLBACK_LOOMIS_PROMPT = (
    "Você é Loomis, o lendário treinador da vila de Hesiod (sangue de ogro, forte, voz aguda e anasalada).\n"
    "Personalidade: pragmático, enérgico, exigente, protetor com os recrutas. Nunca quebre o personagem.\n\n"
    "[REGRAS DE CONDUTA]:\n"
    "1. Você é APENAS o treinador Loomis. Você NUNCA decide se um monstro morreu ou sofreu dano (a verdade mecânica é do Dungeon Master).\n"
    "2. Só comemore a derrota de uma fera se o contexto contiver '[MONSTRO DERROTADO]'. Se a fera tiver HP > 0, reaja a ela ainda viva!\n"
    "3. Fale SEMPRE em PRIMEIRA PESSOA, de forma concisa (1 a 3 frases enérgicas), direta e protetora.\n"
    "4. Responda apenas com a sua fala direta, sem rubricas narrativas entre asteriscos e sem prefixos como 'Loomis:'.\n"
    "5. Formate seu texto com tags HTML aceitas pelo Telegram (<b>negrito</b>, <i>itálico</i>). NUNCA use Markdown."
)


async def extract_d20(text: str) -> int | None:
    """Extrai a rolagem física de um d20 (1 a 20) informada pelo jogador."""
    if not text.strip():
        return None

    # Tenta padrão com indicador de rolagem: d20 [19], tirei 15, rolei 20, deu 18, com 14, dado 12, etc.
    match = re.search(
        r"\b(?:d20|tirei|rolei|deu|com|dado|número|numero)\s*[:=]?\s*([1-9]|1[0-9]|20)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return int(match.group(1))

    # Se a mensagem for simplesmente um número isolado entre 1 e 20 (ex: "19")
    stripped = text.strip()
    if stripped.isdigit() and 1 <= int(stripped) <= 20:
        return int(stripped)

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
        logger.warning(f"Falha ao classificar intenção via LLM ({repr(e)}), aplicando fallback por regex.")
        # Fallback por prefixos de ataque/combate
        combat_prefixes = r"\b(?:atac|golp|bater|lanç|lanc|tiro|atira|dispar|machad|magia|flech|acert|dano|d20|rol|tiro)\w*"
        if re.search(combat_prefixes, text, re.IGNORECASE):
            return "combat"
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
    return {
        "last_context": last_context,
    }


async def combat_node(state: GameState) -> dict:
    """Nó determinístico para resolução do combate, turno do monstro e resumo mecânico."""
    logger.info("Executando nó de combate determinístico...")

    last_user_message = state.get_last_user_message()
    d20 = await extract_d20(last_user_message)

    # Garante herói e monstro inicial se estado estiver vazio
    if not state.players:
        state.players.append(create_hero("jorick"))
    if not state.monsters:
        state.monsters.append(get_cage_monster(1))

    hero = state.players[0]
    # Identifica o monstro alvo (se houver mais de um e o jogador tiver citado o nome)
    monster = state.monsters[0]
    last_msg_lower = last_user_message.lower()
    for m in state.monsters:
        if not m.is_defeated and any(part in last_msg_lower for part in m.name.lower().split()):
            monster = m
            break

    # Se o d20 não foi informado: sinaliza para Loomis solicitar a rolagem física
    if d20 is None:
        lines = [
            "<b>Dungeon Master:</b>",
            f"• <b>{hero.name}</b> preparou um ataque, mas nenhuma rolagem de dado foi informada!",
            "• Declare o valor do seu <b>d20 físico</b> (ex: <i>\"ataco com 17\"</i>). [PENDENTE D20]",
        ]
        state.last_context = "\n".join(lines)
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
        }

    initial_monster_name = monster.name
    # initial_monster_cage = monster.cage_number
    # initial_monster_ac = monster.ac

    # 1. Ataque do Herói (Dungeon Master direto com nome do golpe e HP do alvo)
    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    if hero_res["is_critical"]:
        h_dmg = hero_res["damage_dealt"]
        hero_action_text = f"acertou criticamente {h_dmg} de dano! [{initial_monster_name} HP: {monster.hp}/{monster.max_hp}]"
    elif hero_res["is_hit"]:
        hero_action_text = f"acertou 1 de dano! [{initial_monster_name} HP: {monster.hp}/{monster.max_hp}]"
    else:
        hero_action_text = f"errou o golpe! [{initial_monster_name} HP: {monster.hp}/{monster.max_hp}]"

    dm_lines = [
        "<b>Dungeon Master:</b>",
        f"• <b>{hero.name}</b> atacou <b>{initial_monster_name}</b> com {hero.attack_name} e {hero_action_text}",
    ]

    # 2. Gatilho Loomis: Monstro em 50% de HP ou menos
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
        dm_lines.append(f"• <b>{new_beast.name}</b> entrou na arena! [{new_beast.name} HP: {new_beast.hp}/{new_beast.max_hp}]")

    # 3. Derrota do Monstro e transição entre combates
    monster_defeated_this_turn = monster.is_defeated
    if monster.is_defeated:
        undefeated = [m for m in state.monsters if not m.is_defeated]
        if undefeated:
            state.monsters.remove(undefeated[0])
            state.monsters.insert(0, undefeated[0])
        else:
            healed = []
            for h in state.players:
                if h.hp <= 2:
                    h.restore_full_hp()
                    healed.append(h.name)

            if healed:
                dm_lines.append(f"• Loomis curou {', '.join(healed)} com a poção!")

            if monster.cage_number >= 4:
                state.is_victory = True
                dm_lines.append("• Todas as 4 jaulas foram superadas!")
            else:
                next_cage = monster.cage_number + 1
                next_beast = get_cage_monster(next_cage)
                state.monsters = [next_beast]

    # 4. Contra-ataque da Fera (apenas se sobreviver e combate continuar)
    if not monster_defeated_this_turn and state.monsters and not state.monsters[0].is_defeated and not state.is_victory:
        active_beast = state.monsters[0]
        conscious = [h for h in state.players if not h.is_unconscious]
        if conscious:
            target_hero = max(conscious, key=lambda h: h.hp)
            monster_res = resolve_monster_attack(active_beast, target_hero)

            if monster_res["is_critical"]:
                m_dmg = monster_res["damage_dealt"]
                m_action_text = f"acertou criticamente {m_dmg} de dano! [{target_hero.name} HP: {target_hero.hp}/{target_hero.max_hp}]"
            elif monster_res["is_hit"]:
                m_action_text = f"acertou 1 de dano! [{target_hero.name} HP: {target_hero.hp}/{target_hero.max_hp}]"
            else:
                m_action_text = f"errou o golpe! [{target_hero.name} HP: {target_hero.hp}/{target_hero.max_hp}]"

            dm_lines.append(
                f"• <b>{active_beast.name}</b> contra-atacou <b>{target_hero.name}</b> com {active_beast.attack_name} e {m_action_text}"
            )
            if target_hero.is_unconscious:
                dm_lines.append(f"• <b>{target_hero.name}</b> caiu inconsciente!")

    # 5. Rotaciona a iniciativa dos heróis
    state.rotate_players()

    state.last_context = "\n".join(dm_lines)

    return {
        "last_context": state.last_context,
        "players": state.players,
        "monsters": state.monsters,
        "is_victory": state.is_victory,
        "recent_messages": state.recent_messages,
    }


async def npc_node(state: GameState) -> dict:
    """Nó principal de narração e diálogo do NPC Loomis em 1ª pessoa com trava anti-alucinação."""
    last_user_message = state.get_last_user_message()

    effective_system_prompt = (
        state.npcs[0].system_prompt
        if state.npcs and state.npcs[0].system_prompt
        else FALLBACK_LOOMIS_PROMPT
    )

    monster_fell = "HP: 0/" in (state.last_context or "") or any(m.is_defeated for m in state.monsters)
    defeated_tag = "\n[MONSTRO DERROTADO]" if monster_fell else ""

    prompt_context = (
        f"Contexto do Treino e Regras:\n{state.last_context}{defeated_tag}\n\nMensagem do jogador: {last_user_message}"
        if state.last_context
        else last_user_message
    )

    logger.info(f"Gerando resposta do Loomis via LLM para: '{prompt_context}'")
    try:
        resposta_texto = await llm_client.generate_reply(
            message=prompt_context,
            system_prompt=effective_system_prompt,
        )
    except Exception as e:
        logger.warning(f"Falha ao gerar fala do Loomis via LLM ({e}), usando fala padrão de treino.")
        if state.is_victory:
            resposta_texto = "Vocês conseguiram, recrutas! Todas as jaulas foram superadas! Vocês agora são os verdadeiros Heróis de Hesiod!"
        elif monster_fell:
            resposta_texto = "A fera caiu! Excelente golpe, recrutas! Mas mantenham o foco que a próxima jaula está à frente!"
        elif "[PENDENTE D20]" in (state.last_context or ""):
            resposta_texto = "De nada adianta empunhar a arma sem rolar os dados! Jogue seu d20 na mesa e me diga quanto tirou!"
        else:
            resposta_texto = "Fiquem atentos às fraquezas da fera e mantenham a formação! Hesiod conta com a coragem de vocês!"

    speech = resposta_texto.strip()

    # Compõe mensagem final com bloco do Dungeon Master se for combate
    if state.last_context and "Dungeon Master:" in state.last_context:
        final_content = f"{state.last_context}\n\n<b>Loomis:</b>\n\"{speech}\""
    else:
        final_content = f"<b>Loomis:</b>\n\"{speech}\""

    npc_message = Message(
        sender="Loomis",
        content=final_content,
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
    return await classify_intent(state.get_last_user_message())


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