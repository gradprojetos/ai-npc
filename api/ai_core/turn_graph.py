import re
import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from api.schemas.rpg import GameState, Message
from llm_gateway.client import LLMClient
from api.motor_rpg.motor_rpg import resolve_hero_attack, resolve_monster_attack, get_cage_monster, create_hero

logger = logging.getLogger(__name__)
llm_client = LLMClient()

DEFAULT_LOOMIS_PROMPT = (
    "Você é Loomis, o lendário e dedicado treinador da vila de Hesiod.\n"
    "Você tem traços de sangue de ogro, é forte e intimidador, mas tem uma voz estranhamente aguda e anasalada.\n"
    "Sua personalidade: pragmático, enérgico, exigente, mas muito protetor e encorajador com seus recrutas.\n"
    "Você nunca deixa nenhum aluno morrer na arena de treino.\n"
    "Fale sempre em primeira pessoa, de forma concisa e direta, reagindo às ações do herói ou dando conselhos táticos breves sobre os monstros nas jaulas.\n"
    "Nunca quebre o personagem."
)


def format_heroes_hud(players: list) -> str:
    """Formata a linha de heróis da Arena de Hesiod com HP e status."""
    if not players:
        return "Nenhum herói ativo"
    return ", ".join(
        f"<b>{h.name}</b> [HP: {h.hp}/{h.max_hp}{' - Inconsciente' if h.is_unconscious else ''}]"
        for h in players
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
        logger.warning(f"Falha ao classificar intenção via LLM ({e}), adotando tactical_advice.")
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
    monster = state.monsters[0]

    # Se o d20 não foi informado: sinaliza para Loomis solicitar a rolagem física
    if d20 is None:
        lines = [
            "<b>Dungeon Master:</b>",
            f"• <b>{hero.name}</b> preparou um ataque, mas nenhuma rolagem de dado foi informada!",
            "• Jogue seu <b>d20 físico</b> na mesa e declare o valor tirado (ex: <i>\"ataco com 17\"</i>).",
            "",
            "<b>Arena de Hesiod:</b>",
            f"• Monstro: <b>{monster.name}</b> (Jaula {monster.cage_number}) [HP: {monster.hp}/{monster.max_hp} | CA: {monster.ac}]",
            f"• Heróis: {format_heroes_hud(state.players)}",
            "• Status: <i>[PENDENTE D20] Aguardando rolagem física do d20...</i>",
        ]
        state.last_context = "\n".join(lines)
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
        }

    initial_monster_name = monster.name
    initial_monster_cage = monster.cage_number
    initial_monster_ac = monster.ac

    # 1. Ataque do Herói (Dungeon Master determinístico)
    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    hit_label = "ACERTO CRÍTICO!" if hero_res["is_critical"] else ("ACERTOU!" if hero_res["is_hit"] else "ERROU!")
    damage_label = (
        f"{hero_res['damage_dealt']} ponto." if hero_res["damage_dealt"] == 1 else f"{hero_res['damage_dealt']} pontos."
    ) if hero_res["is_hit"] else "Nenhum."

    dm_lines = [
        "<b>Dungeon Master:</b>",
        f"• <b>{hero.name}</b> atacou <b>{initial_monster_name}</b> com {hero.attack_name}!",
        f"• Rolagem: d20 [{hero_res['d20_roll']}] + {hero_res['attack_bonus']} = {hero_res['total_attack']} vs CA {initial_monster_ac} ({hit_label})",
        f"• Dano: {damage_label}",
    ]

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
        dm_lines.append(
            f"• Gatilho Loomis: {initial_monster_name} caiu para metade da vida! "
            f"Loomis destranca a Jaula {next_cage} e {new_beast.name} entra na arena!"
        )

    # 3. Derrota do Monstro e transição entre combates
    monster_defeated_this_turn = monster.is_defeated
    if monster.is_defeated:
        dm_lines.append(f"• <b>{initial_monster_name}</b> foi derrotado!")
        undefeated = [m for m in state.monsters if not m.is_defeated]
        if undefeated:
            state.monsters.remove(undefeated[0])
            state.monsters.insert(0, undefeated[0])
        else:
            # Todos os monstros derrotados: fim da luta! Loomis cura quem tem <= 2 HP
            healed = []
            for h in state.players:
                if h.hp <= 2:
                    h.restore_full_hp()
                    healed.append(h.name)

            if healed:
                dm_lines.append(
                    f"• Fim do combate: Loomis distribui a poção de menta e limão ({', '.join(healed)} recuperaram vida máxima)!"
                )

            if monster.cage_number >= 4:
                state.is_victory = True
            else:
                next_cage = monster.cage_number + 1
                next_beast = get_cage_monster(next_cage)
                state.monsters = [next_beast]

    # 4. Contra-ataque da Fera (executado apenas se a fera atacada sobreviver e o combate continuar)
    counter_lines = []
    if not monster_defeated_this_turn and state.monsters and not state.monsters[0].is_defeated and not state.is_victory:
        active_beast = state.monsters[0]
        conscious = [h for h in state.players if not h.is_unconscious]
        if conscious:
            # Monstro mira no herói consciente com maior HP
            target_hero = max(conscious, key=lambda h: h.hp)
            monster_res = resolve_monster_attack(active_beast, target_hero)

            m_hit_label = "ACERTO CRÍTICO!" if monster_res["is_critical"] else ("ACERTOU!" if monster_res["is_hit"] else "ERROU!")
            m_damage_label = (
                f"{monster_res['damage_dealt']} ponto." if monster_res["damage_dealt"] == 1 else f"{monster_res['damage_dealt']} pontos."
            ) if monster_res["is_hit"] else "Nenhum."

            counter_lines = [
                "<b>Contra-ataque da Fera:</b>",
                f"• <b>{active_beast.name}</b> atacou <b>{target_hero.name}</b> com {active_beast.attack_name}!",
                f"• Rolagem: d20 [{monster_res['d20_roll']}] + {monster_res['attack_bonus']} = {monster_res['total_attack']} vs CA {target_hero.ac} ({m_hit_label})",
                f"• Dano sofrido: {m_damage_label}",
            ]
            if target_hero.is_unconscious:
                counter_lines.append(f"• <b>{target_hero.name}</b> caiu a 0 HP e está inconsciente!")

    # 5. Rotaciona a iniciativa dos heróis
    state.rotate_players()

    # 6. Resumo da Arena de Hesiod
    arena_lines = ["<b>Arena de Hesiod:</b>"]
    if state.is_victory:
        arena_lines.append("• Monstro: <i>Nenhum (Todas as 4 jaulas superadas!)</i>")
        arena_lines.append(f"• Heróis: {format_heroes_hud(state.players)}")
        arena_lines.append("• Status: <i>[MONSTRO DERROTADO] Todas as jaulas foram superadas! Os recrutas são Heróis de Hesiod!</i>")
    else:
        curr_monster = state.monsters[0]
        arena_lines.append(
            f"• Monstro: <b>{curr_monster.name}</b> (Jaula {curr_monster.cage_number}) [HP: {curr_monster.hp}/{curr_monster.max_hp} | CA: {curr_monster.ac}]"
        )
        arena_lines.append(f"• Heróis: {format_heroes_hud(state.players)}")
        if len(state.players) > 1:
            arena_lines.append(f"• Próximo a agir: <b>{state.players[0].name}</b>")
        if monster_defeated_this_turn:
            arena_lines.append(f"• Status: <i>[MONSTRO DERROTADO] {initial_monster_name} tombou na arena! Próxima fera ativa!</i>")
        elif any(h.is_unconscious for h in state.players):
            arena_lines.append("• Status: <i>Herói caído na arena! Loomis aguarda a vitória para socorrer!</i>")
        elif curr_monster.hp < curr_monster.max_hp:
            arena_lines.append("• Status: <i>Fera ferida e furiosa na arena!</i>")
        else:
            arena_lines.append("• Status: <i>Fera ilesa e pronta para o combate!</i>")

    sections = ["\n".join(dm_lines)]
    if counter_lines:
        sections.append("\n".join(counter_lines))
    sections.append("\n".join(arena_lines))
    state.last_context = "\n\n".join(sections)

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

    npc_prompt = (
        state.npcs[0].system_prompt
        if state.npcs and state.npcs[0].system_prompt
        else DEFAULT_LOOMIS_PROMPT
    )

    format_instructions = (
        "\n\n[REGRAS DE PERSONA - LOOMIS]:\n"
        "1. Você é APENAS o treinador Loomis. Você NUNCA decide se um monstro morreu ou sofreu dano. Toda a verdade mecânica pertence exclusivamente ao Dungeon Master.\n"
        "2. Você só comemora a derrota de uma fera se o contexto contiver expressamente '[MONSTRO DERROTADO]'. Se a fera tiver HP > 0, reaja a ela ainda viva e ameaçadora!\n"
        "3. Fale SEMPRE em PRIMEIRA PESSOA como Loomis, de forma concisa (1 a 3 frases enérgicas), direta e protetora.\n"
        "4. Responda apenas com a sua fala direta, sem rubricas narrativas entre asteriscos e sem prefixos como 'Loomis:'.\n"
        "5. Formate seu texto com tags HTML aceitas pelo Telegram (<b>negrito</b>, <i>itálico</i>). NUNCA use Markdown."
    )
    effective_system_prompt = (npc_prompt + format_instructions).strip()

    prompt_context = (
        f"Contexto do Treino e Regras:\n{state.last_context}\n\nMensagem do jogador: {last_user_message}"
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
        elif "[MONSTRO DERROTADO]" in (state.last_context or ""):
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