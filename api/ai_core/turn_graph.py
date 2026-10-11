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


def clean_loomis_speech(text: str) -> str:
    """Sanitiza a fala de Loomis, expurgando rubricas em 3ª pessoa e prefixos indesejados."""
    if not text:
        return "Loomis observa com firmeza, avaliando seu próximo movimento."

    cleaned = text.strip()
    # 1. Remove prefixos como "Loomis:", "🗣️ Loomis:", "**Loomis:**", "<b>Loomis:</b>", etc.
    cleaned = re.sub(r"^(?:🗣️\s*)?(?:\*\*|<b>)?\s*loomis\s*(?:\*\*|</b>)?\s*:\s*", "", cleaned, flags=re.IGNORECASE)

    # 2. Expurga rubricas narrativas em 3ª pessoa entre asteriscos ou parênteses
    cleaned = re.sub(r"\*[^*]*(?:loomis|cospe|sorri|olha|cruza|bate|move|grita|ri|acena|aponta|guincho|abaixa)[^*]*\*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\([^)]*(?:loomis|cospe|sorri|olha|cruza|bate|move|grita|ri|acena|aponta|guincho|abaixa)[^)]*\)", "", cleaned, flags=re.IGNORECASE)

    # 3. Converte Markdown remanescente para tags HTML aceitas pelo Telegram
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", cleaned)
    cleaned = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", cleaned)

    # 4. Remove espaços extras e aspas externas
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith('“') and cleaned.endswith('”')):
        cleaned = cleaned[1:-1].strip()

    return cleaned or "Mantenham o foco no combate, recrutas!"


async def extract_d20(text: str) -> int | None:
    """Extrai a rolagem física de um d20 (1 a 20) informada pelo jogador via LLM ou regex."""
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

    # Fallback determinístico por regex
    match = re.search(r"(?:d20\s*[:=]?\s*|tirei\s+|rolei\s+|com\s+|deu\s+)?\b([1-9]|1[0-9]|20)\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
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
        combat_keywords = [
            "atacar", "ataque", "ataco", "golpe", "golpear", "golpeio",
            "bater", "bato", "espada", "magia", "flecha", "machado",
            "lutar", "investida", "d20", "rolei", "tirei", "dado"
        ]
        if any(kw in text.lower() for kw in combat_keywords):
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
    state.combat_hud = None
    return {
        "last_context": last_context,
        "combat_hud": None,
    }


async def combat_node(state: GameState) -> dict:
    """Nó determinístico para resolução do combate, turno do monstro e montagem do HUD do Dungeon Master."""
    logger.info("Executando nó de combate determinístico...")

    last_user_message = ""
    for msg in reversed(state.recent_messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    d20 = await extract_d20(last_user_message)

    # Garante herói e monstro inicial se estado estiver vazio
    if not state.players:
        state.players.append(create_hero("jorick"))
    if not state.monsters:
        state.monsters.append(get_cage_monster(1))

    hero = state.players[0]
    monster = state.monsters[0]

    # Se o d20 não foi informado: sinaliza para Loomis solicitar a rolagem física com HUD informativo
    if d20 is None:
        hud_lines = [
            "🎲 <b>Dungeon Master:</b>",
            f"• <b>{hero.name}</b> preparou um ataque, mas nenhuma rolagem de dado foi informada!",
            "• Jogue seu <b>d20 físico</b> na mesa e declare o valor tirado (ex: <i>\"ataco com 17\"</i>).",
            "",
            "📊 <b>Arena de Hesiod:</b>",
            f"• Monstro: <b>{monster.name}</b> (Jaula {monster.cage_number}) [HP: {monster.hp}/{monster.max_hp} | CA: {monster.ac}]",
            f"• Heróis: {format_heroes_hud(state.players)}",
            "• Status: <i>Aguardando rolagem física do d20...</i>",
        ]
        combat_hud = "\n".join(hud_lines)
        state.combat_hud = combat_hud
        state.last_context = (
            f"[PENDENTE D20]\n"
            f"O recruta {hero.name} tentou atacar, mas NÃO informou o valor do d20 físico tirado na mesa!\n"
            f"Instrução para Loomis: Cobre com autoridade, energia e firmeza que o recruta jogue seu d20 físico "
            f"e diga quanto tirou para poder atingir a fera."
        )
        return {
            "last_context": state.last_context,
            "combat_hud": combat_hud,
        }

    initial_monster_name = monster.name
    initial_monster_cage = monster.cage_number
    initial_monster_ac = monster.ac

    # 1. Ataque do Herói (Dungeon Master determinístico)
    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    hit_label = "ACERTO CRÍTICO!" if hero_res.is_critical else ("ACERTOU!" if hero_res.is_hit else "ERROU!")
    damage_label = (
        f"{hero_res.damage_dealt} ponto." if hero_res.damage_dealt == 1 else f"{hero_res.damage_dealt} pontos."
    ) if hero_res.is_hit else "Nenhum."

    dm_lines = [
        "🎲 <b>Dungeon Master:</b>",
        f"• <b>{hero.name}</b> atacou <b>{initial_monster_name}</b> com {hero.attack_name}!",
        f"• Rolagem: d20 [{hero_res.d20_roll}] + {hero_res.attack_bonus} = {hero_res.total_attack} vs CA {initial_monster_ac} ({hit_label})",
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
    counter_attack_info = None
    if not monster_defeated_this_turn and state.monsters and not state.monsters[0].is_defeated and not state.is_victory:
        active_beast = state.monsters[0]
        conscious = [h for h in state.players if not h.is_unconscious]
        if conscious:
            # Monstro mira no herói consciente com maior HP
            target_hero = max(conscious, key=lambda h: h.hp)
            monster_res = resolve_monster_attack(active_beast, target_hero)
            counter_attack_info = (active_beast, target_hero, monster_res)

            m_hit_label = "ACERTO CRÍTICO!" if monster_res.is_critical else ("ACERTOU!" if monster_res.is_hit else "ERROU!")
            m_damage_label = (
                f"{monster_res.damage_dealt} ponto." if monster_res.damage_dealt == 1 else f"{monster_res.damage_dealt} pontos."
            ) if monster_res.is_hit else "Nenhum."

            counter_lines = [
                "⚔️ <b>Contra-ataque da Fera:</b>",
                f"• <b>{active_beast.name}</b> atacou <b>{target_hero.name}</b> com {active_beast.attack_name}!",
                f"• Rolagem: d20 [{monster_res.d20_roll}] + {monster_res.attack_bonus} = {monster_res.total_attack} vs CA {target_hero.ac} ({m_hit_label})",
                f"• Dano sofrido: {m_damage_label}",
            ]
            if target_hero.is_unconscious:
                counter_lines.append(f"• <b>{target_hero.name}</b> caiu a 0 HP e está inconsciente!")

    # 5. Rotaciona a iniciativa dos heróis
    state.rotate_players()

    # 6. Montagem do HUD da Arena de Hesiod
    arena_lines = ["📊 <b>Arena de Hesiod:</b>"]
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
        if monster_defeated_this_turn:
            arena_lines.append(f"• Status: <i>[MONSTRO DERROTADO] {initial_monster_name} tombou na arena! Próxima fera ativa!</i>")
        elif any(h.is_unconscious for h in state.players):
            arena_lines.append("• Status: <i>Herói caído na arena! Loomis aguarda a vitória para socorrer!</i>")
        elif curr_monster.hp < curr_monster.max_hp:
            arena_lines.append("• Status: <i>Fera ferida e furiosa na arena!</i>")
        else:
            arena_lines.append("• Status: <i>Fera ilesa e pronta para o combate!</i>")

    # Monta os blocos determinísticos do HUD completo (Passo 3)
    hud_sections = ["\n".join(dm_lines)]
    if counter_lines:
        hud_sections.append("\n".join(counter_lines))
    hud_sections.append("\n".join(arena_lines))
    combat_hud = "\n\n".join(hud_sections)
    state.combat_hud = combat_hud

    # Fatos inquestionáveis para Loomis reagir sem alucinar (Passo 4)
    curr_beast = state.monsters[0] if state.monsters else None
    context_lines = [
        "Fatos Mecânicos do Turno (Dungeon Master):",
        f"- {hero.name} atacou {initial_monster_name}: d20 [{hero_res.d20_roll}] + {hero_res.attack_bonus} = {hero_res.total_attack} vs CA {initial_monster_ac} ({hit_label}). Dano causado: {hero_res.damage_dealt}.",
    ]
    if counter_attack_info:
        ab, th, mr = counter_attack_info
        context_lines.append(f"- Contra-ataque de {ab.name} em {th.name}: {m_hit_label}, causou {mr.damage_dealt} de dano.")
    if state.is_victory:
        context_lines.append("- [MONSTRO DERROTADO] [VITÓRIA] Todas as 4 jaulas foram superadas! Os recrutas são Heróis de Hesiod!")
    elif monster_defeated_this_turn:
        context_lines.append(f"- [MONSTRO DERROTADO] {initial_monster_name} foi derrotado!")
        if curr_beast:
            context_lines.append(f"- Nova fera na arena: {curr_beast.name} (Jaula {curr_beast.cage_number}) [HP: {curr_beast.hp}/{curr_beast.max_hp}].")
    else:
        if curr_beast:
            context_lines.append(f"- A fera {curr_beast.name} continua VIVA e ameaçadora (HP: {curr_beast.hp}/{curr_beast.max_hp})!")

    state.last_context = "\n".join(context_lines)

    return {
        "last_context": state.last_context,
        "combat_hud": combat_hud,
        "players": state.players,
        "monsters": state.monsters,
        "is_victory": state.is_victory,
        "recent_messages": state.recent_messages,
    }


async def npc_node(state: GameState) -> dict:
    """Nó principal de narração e diálogo do NPC Loomis com trava anti-alucinação e persona em 1ª pessoa (Passo 4)."""
    last_user_message = ""
    for msg in reversed(state.recent_messages):
        if msg.role == "user":
            last_user_message = msg.content
            break

    npc_prompt = (
        state.npcs[0].system_prompt
        if state.npcs and state.npcs[0].system_prompt
        else DEFAULT_LOOMIS_PROMPT
    )

    format_instructions = (
        "\n\n[REGRAS INQUEBRÁVEIS DE SEGURANÇA E PERSONA - LOOMIS]:\n"
        "1. Você é APENAS o treinador Loomis. Você NUNCA decide se um monstro morreu ou sofreu dano. Toda a verdade mecânica pertence exclusivamente ao Dungeon Master.\n"
        "2. Você só comemora a derrota de uma fera se o contexto contiver expressamente '[MONSTRO DERROTADO]'. Se a fera tiver HP > 0, reaja a ela ainda viva e ameaçadora!\n"
        "3. Fale SEMPRE e estritamente em PRIMEIRA PESSOA como Loomis, de forma concisa (1 a 3 frases enérgicas), direta e protetora.\n"
        "4. É terminantemente PROIBIDO gerar rubricas narrativas em 3ª pessoa (como '*loomis cospe no chão*', '*ele sorri*', '*solta um guincho*'). Responda apenas com a fala que sai da sua boca.\n"
        "5. NUNCA inclua prefixos como 'Loomis:' ou 'Dungeon Master:' na resposta.\n"
        "6. Formate seu texto com tags HTML aceitas pelo Telegram (<b>negrito</b>, <i>itálico</i>). NUNCA use Markdown (como **, *, _, ###)."
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
        elif state.combat_hud:
            resposta_texto = "Bom golpe, garoto! Mas não baixe a guarda, essa carapaça de pedra ainda tem muita luta pela frente!"
        else:
            resposta_texto = "Fiquem atentos às fraquezas da fera e mantenham a formação! Hesiod conta com a coragem de vocês!"

    # Sanitização rígida de Persona (Passo 4)
    cleaned_speech = clean_loomis_speech(resposta_texto)

    # Composição do turno completo com HUD mecânico (Passo 3) e voz do NPC (Passo 4)
    if state.combat_hud:
        final_content = f"{state.combat_hud}\n\n🗣️ <b>Loomis:</b>\n\"{cleaned_speech}\""
    else:
        final_content = f"🗣️ <b>Loomis:</b>\n\"{cleaned_speech}\""

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
        "combat_hud": state.combat_hud,
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