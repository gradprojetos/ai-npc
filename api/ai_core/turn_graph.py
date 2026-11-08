import re
import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from api.schemas.rpg import GameState, HeroState, Message, MonsterState
from llm_gateway.client import LLMClient
from api.motor_rpg.motor_rpg import resolve_hero_attack, resolve_monster_attack, get_cage_monster, create_hero
from api.ai_core.prompts import EXPLORATION_PROMPT, COMBAT_PROMPT, TACTICAL_PROMPT

logger = logging.getLogger(__name__)
llm_client = LLMClient()

_round_buffers: dict[str, list[str]] = {}
_acted_heroes: dict[str, list[str]] = {}
_last_monster_targets: dict[str, str] = {}
_exploration_counters: dict[str, int] = {}
_combat_started: dict[str, bool] = {}

_ROLL_INDICATOR_PATTERN = re.compile(
    r"\b(?:d20|tirei|rolei|deu|com|c|dado|número|numero|ataco|ataque|golpe|acerto)\s*[:=]?\s*(-?\d+)\b",
    flags=re.IGNORECASE,
)


def clear_round_state(session_id: str) -> None:
    """Limpa buffers temporários em memória da sessão."""
    _round_buffers.pop(session_id, None)
    _acted_heroes.pop(session_id, None)
    _last_monster_targets.pop(session_id, None)
    _exploration_counters.pop(session_id, None)
    _combat_started.pop(session_id, None)


def _get_active_monster(state: GameState) -> MonsterState | None:
    """Retorna o primeiro monstro vivo da sessão ou o último da lista caso todos tenham caído."""
    if not state.monsters:
        return None
    return next((m for m in state.monsters if not m.is_defeated and m.hp > 0), state.monsters[-1])


def _find_sender_hero(state: GameState) -> HeroState | None:
    """Identifica o herói correspondente ao autor da última mensagem do usuário."""
    last_user_msg = next((m for m in reversed(state.recent_messages) if m.role == "user"), None)
    if last_user_msg and state.players:
        sender = last_user_msg.sender
        for p in state.players:
            if p.player_id == sender or (sender and sender in p.name):
                return p
    return None


def _is_combat_active(state: GameState) -> bool:
    """Verifica se a jaula já foi aberta e o combate está em andamento na sessão (sem efeito colateral)."""
    if state.is_victory:
        return False
    if _combat_started.get(state.session_id, False):
        return True
    if len(state.monsters) > 1 or any(m.hp < m.max_hp or m.is_defeated for m in state.monsters):
        return True
    combat_markers = ("foi aberta e", "atacou", "informe o resultado do seu d20", "Valor inválido! O d20")
    if any(
        any(marker in m.content for marker in combat_markers)
        for m in state.recent_messages
        if m.role == "assistant"
    ):
        return True
    return False


def has_invalid_d20(text: str) -> bool:
    """Detecta se o jogador informou uma rolagem de d20 fora do intervalo válido de 1 a 20."""
    if not text or not text.strip():
        return False
    cleaned = re.sub(r"\bjaulas?\s+\d+\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b1?d20\b", "d20", cleaned, flags=re.IGNORECASE)

    standalone = re.fullmatch(r"\s*(-?\d+)\s*", cleaned)
    if standalone:
        val = int(standalone.group(1))
        return val < 1 or val > 20

    indicator_matches = [int(m) for m in _ROLL_INDICATOR_PATTERN.findall(cleaned)]
    if indicator_matches:
        return any(val < 1 or val > 20 for val in indicator_matches) and not any(
            1 <= val <= 20 for val in indicator_matches
        )
    return False


async def extract_d20(text: str) -> int | None:
    """Extrai a rolagem física de um d20 (1 a 20) informada pelo jogador."""
    if not text or not text.strip() or has_invalid_d20(text):
        return None

    cleaned = re.sub(r"\bjaulas?\s+\d+\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b1?d20\b", "d20", cleaned, flags=re.IGNORECASE)

    for raw_val in _ROLL_INDICATOR_PATTERN.findall(cleaned):
        val = int(raw_val)
        if 1 <= val <= 20:
            return val

    numbers = re.findall(r"(?<![-\w])([1-9]|1[0-9]|20)\b", cleaned)
    if numbers:
        return int(numbers[-1])

    return None


async def classify_intent(text: str) -> str:
    """Classifica a intenção da mensagem via LLM ('combat', 'tactical_advice' ou 'exploration')."""
    if not text.strip():
        return "exploration"

    prompt = (
        "Classifique a mensagem do jogador de RPG em APENAS UMA categoria ('combat', 'tactical_advice' ou 'exploration'):\n"
        "- 'combat': Ataques, golpes, magias ofensivas, qualquer rolagem numérica ou número isolado (ex: '7', '15', 'ataco com 20', 'ataco com 50'), "
        "OU avisar que estão prontos / pedir para Loomis puxar a alavanca ou abrir a jaula (ex: 'estamos prontos', 'puxe a alavanca', 'vamos lutar', 'solte a fera').\n"
        "- 'tactical_advice': Dúvidas sobre regras, fraquezas do monstro ou como usar poderes da ficha.\n"
        "- 'exploration': Conversa sobre a vila de Hesiod, cabana, caldeirão, lore, ou tentar arrombar a jaula escondido sem autorização.\n"
        "Responda APENAS uma palavra: combat, tactical_advice ou exploration."
    )
    try:
        response = await llm_client.generate_reply(
            message=text,
            system_prompt=prompt,
            temperature=0.0,
            max_tokens=15,
        )
        decision = response.strip().lower()
        if "combat" in decision:
            return "combat"
        if "tactical" in decision or "advice" in decision:
            return "tactical_advice"
        return "exploration"
    except Exception as e:
        logger.warning(f"Falha ao classificar intenção via LLM ({repr(e)}), aplicando fallback por regex.")
        d20 = await extract_d20(text)
        if d20 is not None or has_invalid_d20(text):
            return "combat"
        ready_pattern = r"\b(?:estamos pront[oa]s?|vamos lutar|puxa a alavanca|bora começar|começar treino)\b"
        combat_pattern = r"\b(?:atac|golp|bater|lanç|lanc|tiro|atira|dispar|machad|magia|flech|acert|dano)\w*"
        if re.search(ready_pattern, text, re.IGNORECASE) or re.search(combat_pattern, text, re.IGNORECASE):
            return "combat"
        tactical_pattern = r"\b(?:fraqueza|dica|conselho|como us|ponto fraco|poder|habilidade)\b"
        if re.search(tactical_pattern, text, re.IGNORECASE):
            return "tactical_advice"
        return "exploration"


def tactical_advice_node(state: GameState) -> dict:
    """Nó para conselho tático pedagógico e advertência anti-dispersão durante o combate."""
    logger.info("Executando nó de conselho tático...")
    hero = _find_sender_hero(state) or (state.players[0] if state.players else None)
    monster = _get_active_monster(state)

    last_msg = state.get_last_user_message().lower()
    is_dispersion = any(w in last_msg for w in ["cabana", "passear", "riacho", "olhar", "investigar", "procurar", "sair"])

    context_parts: list[str] = []
    if monster and not monster.is_defeated and monster.hp > 0 and is_dispersion:
        context_parts.append(
            f"Alerta Anti-Dispersão: O recruta tentou dispersão enquanto a fera está atacando!\n"
            f"Instrução para Loomis: Adverta energicamente em personagem: 'Atenção, recruta! O {monster.name} "
            f"está investindo contra você com mandíbulas abertas, não é hora de passear! Mantenha a guarda e ataque!'"
        )
    else:
        context_parts.append("Ação Livre (Conselho Tático): O recruta está pedindo orientação ou tirando dúvidas de combate.")
        if hero:
            context_parts.append(
                f"Recruta ativo: {hero.name} ({hero.class_name}). Poder especial: '{hero.special_power}'."
            )
        if monster and not monster.is_defeated and monster.hp > 0:
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

    if state.npcs:
        state.npcs[0].system_prompt = TACTICAL_PROMPT

    last_context = "\n".join(context_parts)
    state.last_context = last_context
    return {
        "last_context": last_context,
        "npcs": state.npcs,
    }


def exploration_node(state: GameState) -> dict:
    """Nó para roleplay livre, investigação do cenário e diálogo com Loomis na clareira."""
    logger.info("Executando nó de exploração...")
    count = _exploration_counters.get(state.session_id, 0) + 1
    _exploration_counters[state.session_id] = count

    if count >= 7:
        beast = _get_active_monster(state) or get_cage_monster(1)
        _combat_started[state.session_id] = True
        _exploration_counters[state.session_id] = 0
        context_parts = [
            "<b>Dungeon Master:</b>",
            f"• A Jaula {beast.cage_number} foi aberta e <b>{beast.name}</b> entrou na arena [HP: {beast.hp}/{beast.max_hp} | CA: {beast.ac}]!",
            f"Gatilho Forçado de Combate: Loomis perdeu a paciência com o grupo após {count} mensagens de conversa, puxou a alavanca da Jaula 1 e mandou os recrutas assumirem formação!",
        ]
    elif count >= 4:
        context_parts = [
            "Ação Livre (Roleplay e Exploração na Clareira de Treino):",
            "Loomis impaciente: Responda brevemente ao que foi perguntado, mas corte a conversa mole e pressione com firmeza: "
            "'Chega de conversa mole e de passar a mão na madeira da cabana, recrutas! As feras estão farejando o almoço. Vamos abrir a Jaula 1 ou vocês vão amarelar?'",
        ]
    else:
        context_parts = [
            "Ação Livre (Roleplay e Exploração na Clareira de Treino):",
            "Loomis acolhedor: Responda com simpatia e experiência de veterano às perguntas sobre a vila de Hesiod, "
            "as ferramentas, a cabana rústica e o caldeirão de poção revigorante de menta e limão. Lembre-os amigavelmente de avisar quando estiverem prontos.",
        ]

    if state.npcs:
        state.npcs[0].system_prompt = EXPLORATION_PROMPT

    last_context = "\n".join(context_parts)
    state.last_context = last_context
    return {
        "last_context": last_context,
        "npcs": state.npcs,
    }


async def combat_node(state: GameState) -> dict:
    """Nó determinístico para resolução do combate, turno do monstro e resumo mecânico."""
    logger.info("Executando nó de combate determinístico...")

    if state.npcs:
        state.npcs[0].system_prompt = COMBAT_PROMPT

    if state.is_victory:
        state.last_context = "Todas as 4 jaulas foram superadas! Parabenize os novos Heróis de Hesiod!"
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "is_victory": state.is_victory,
            "recent_messages": state.recent_messages,
            "npcs": state.npcs,
        }

    last_user_message = state.get_last_user_message()
    d20 = await extract_d20(last_user_message)

    if not state.players:
        state.players.append(create_hero("jorick"))
    if not state.monsters:
        state.monsters.append(get_cage_monster(1))

    active_monsters = [m for m in state.monsters if not m.is_defeated and m.hp > 0]
    if not active_monsters:
        fallback_m = _get_active_monster(state)
        active_monsters = [fallback_m] if fallback_m else [get_cage_monster(1)]

    target_monster = None
    last_msg_lower = last_user_message.lower()
    for m in active_monsters:
        if any(part in last_msg_lower for part in m.name.lower().split()):
            target_monster = m
            break
    if not target_monster:
        target_monster = min(active_monsters, key=lambda m: m.hp)
    monster = target_monster

    combat_already_started = _is_combat_active(state)

    conscious_heroes = [h for h in state.players if not h.is_unconscious]
    acted = _acted_heroes.setdefault(state.session_id, [])
    pending_heroes = [h for h in conscious_heroes if h.player_id not in acted]

    hero = _find_sender_hero(state)
    if not hero:
        hero = pending_heroes[0] if pending_heroes else (conscious_heroes[0] if conscious_heroes else state.players[0])

    if d20 is None:
        if has_invalid_d20(last_user_message):
            state.last_context = (
                f"<b>Dungeon Master:</b>\n"
                f"• Valor inválido! O d20 físico possui apenas valores de 1 a 20. Role novamente e informe um valor válido, <b>{hero.name}</b>!"
            )
        elif not combat_already_started:
            _combat_started[state.session_id] = True
            _exploration_counters[state.session_id] = 0
            lines = [
                "<b>Dungeon Master:</b>",
                f"• A Jaula {monster.cage_number} foi aberta e <b>{monster.name}</b> entrou na arena [HP: {monster.hp}/{monster.max_hp} | CA: {monster.ac}]!",
                f"• <b>{hero.name}</b>, declare sua ação e o valor do seu d20 físico (ex: \"ataco com 17\")!",
            ]
            state.last_context = "\n".join(lines)
        else:
            state.last_context = (
                f"<b>Dungeon Master:</b>\n"
                f"• <b>{hero.name}</b>, informe o resultado do seu d20 físico de 1 a 20 para resolver o seu ataque (ex: \"ataco com 17\")!"
            )
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
            "npcs": state.npcs,
        }

    _combat_started[state.session_id] = True
    _exploration_counters[state.session_id] = 0

    if hero.is_unconscious:
        next_hero_name = pending_heroes[0].name if pending_heroes else "seus aliados"
        state.last_context = (
            f"<b>Dungeon Master:</b>\n"
            f"• <b>{hero.name}</b> está inconsciente e não pode atacar! É a vez de <b>{next_hero_name}</b> agir."
        )
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
            "npcs": state.npcs,
        }

    if hero.player_id in acted:
        next_hero_name = pending_heroes[0].name if pending_heroes else "seus aliados"
        state.last_context = (
            f"<b>Dungeon Master:</b>\n"
            f"• <b>{hero.name}</b> já realizou sua ação nesta rodada! É a vez de <b>{next_hero_name}</b> agir."
        )
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
            "npcs": state.npcs,
        }

    initial_monster_name = monster.name
    round_actions = _round_buffers.setdefault(state.session_id, [])

    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    if hero_res["is_critical"]:
        h_dmg = hero_res["damage_dealt"]
        hero_action_text = f"acertou criticamente {h_dmg} de dano! [Monstro HP: {monster.hp}/{monster.max_hp}]"
    elif hero_res["is_hit"]:
        hero_action_text = f"acertou 1 de dano! [Monstro HP: {monster.hp}/{monster.max_hp}]"
    else:
        hero_action_text = f"errou o golpe! [Monstro HP: {monster.hp}/{monster.max_hp}]"

    action_text = f"• <b>{hero.name}</b> atacou <b>{initial_monster_name}</b> com {hero.attack_name} e {hero_action_text}"
    round_actions.append(action_text)
    acted.append(hero.player_id)

    has_fallen_hero = any(h.is_unconscious for h in state.players)
    new_beast = None
    if (
        monster.is_half_hp_or_less
        and len([m for m in state.monsters if not m.is_defeated and m.hp > 0]) == 1
        and monster.cage_number < 4
        and not has_fallen_hero
    ):
        next_cage = monster.cage_number + 1
        new_beast = get_cage_monster(next_cage)
        state.monsters.append(new_beast)
        round_actions.append(f"• <b>{new_beast.name}</b> entrou na arena! [Monstro HP: {new_beast.hp}/{new_beast.max_hp}]")

    if monster.is_defeated or monster.hp <= 0:
        undefeated = [m for m in state.monsters if not m.is_defeated and m.hp > 0]
        if not undefeated:
            healed = []
            for h in state.players:
                if h.hp <= 2:
                    h.restore_full_hp()
                    healed.append(h.name)
            if healed:
                round_actions.append(f"• Loomis curou {', '.join(healed)} com a poção!")

            max_cage = max(m.cage_number for m in state.monsters) if state.monsters else monster.cage_number
            if max_cage >= 4:
                state.is_victory = True
                round_actions.append("• Todas as 4 jaulas foram superadas!")
            else:
                next_cage = max_cage + 1
                next_beast = get_cage_monster(next_cage)
                state.monsters.append(next_beast)
                round_actions.append(f"• <b>{next_beast.name}</b> entrou na arena! [Monstro HP: {next_beast.hp}/{next_beast.max_hp}]")

    conscious_heroes = [h for h in state.players if not h.is_unconscious]
    remaining_heroes = [h for h in conscious_heroes if h.player_id not in acted]
    round_finished = len(remaining_heroes) == 0 or state.is_victory

    if not round_finished:
        next_hero = remaining_heroes[0]
        dm_mid_lines = [
            "<b>Dungeon Master:</b>",
            action_text,
        ]
        if new_beast:
            dm_mid_lines.append(f"• <b>{new_beast.name}</b> entrou na arena! [Monstro HP: {new_beast.hp}/{new_beast.max_hp}]")
        dm_mid_lines.append(f"• Próximo a agir: <b>{next_hero.name}</b>, declare sua ação e o valor do seu d20 físico!")

        state.last_context = "\n".join(dm_mid_lines)
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "is_victory": state.is_victory,
            "recent_messages": state.recent_messages,
            "npcs": state.npcs,
        }

    _acted_heroes.pop(state.session_id, None)
    dm_lines = ["<b>Dungeon Master:</b>"] + round_actions
    _round_buffers.pop(state.session_id, None)

    if not state.is_victory:
        alive_beasts = [m for m in state.monsters if not m.is_defeated and m.hp > 0]
        active_conscious = [h for h in state.players if not h.is_unconscious]
        last_target_id = _last_monster_targets.get(state.session_id)

        for beast in alive_beasts:
            if not active_conscious:
                break
            candidates = [h for h in active_conscious if h.player_id != last_target_id] if len(active_conscious) > 1 else active_conscious
            target_hero = max(candidates, key=lambda h: h.hp)
            last_target_id = target_hero.player_id
            _last_monster_targets[state.session_id] = target_hero.player_id

            m_res = resolve_monster_attack(beast, target_hero)

            if m_res["is_critical"]:
                m_dmg = m_res["damage_dealt"]
                m_text = f"acertou criticamente {m_dmg} de dano! [Herói HP: {target_hero.hp}/{target_hero.max_hp}]"
            elif m_res["is_hit"]:
                m_text = f"acertou 1 de dano! [Herói HP: {target_hero.hp}/{target_hero.max_hp}]"
            else:
                m_text = f"errou o golpe! [Herói HP: {target_hero.hp}/{target_hero.max_hp}]"

            dm_lines.append(
                f"• <b>{beast.name}</b> contra-atacou <b>{target_hero.name}</b> com {beast.attack_name} e {m_text}"
            )
            if target_hero.is_unconscious:
                dm_lines.append(f"• <b>{target_hero.name}</b> caiu inconsciente!")
                active_conscious.remove(target_hero)

        # Regra de Hesiod: se todo o grupo tombar, Loomis arremessa a poção e reanima os heróis para o treino continuar
        if not active_conscious and state.players:
            healed_names = []
            for h in state.players:
                h.restore_full_hp()
                healed_names.append(h.name)
            dm_lines.append(
                f"• Loomis interveio arremessando sua poção de menta e limão, reanimando {', '.join(healed_names)} para continuar a luta!"
            )

    state.last_context = "\n".join(dm_lines)

    return {
        "last_context": state.last_context,
        "players": state.players,
        "monsters": state.monsters,
        "is_victory": state.is_victory,
        "recent_messages": state.recent_messages,
        "npcs": state.npcs,
    }


async def npc_node(state: GameState) -> dict:
    """Nó principal de narração e diálogo do NPC Loomis em 1ª pessoa com trava anti-alucinação."""
    last_user_message = state.get_last_user_message()

    if state.last_context is None and not state.is_victory:
        return {
            "recent_messages": state.recent_messages,
        }

    is_mid_round_turn = (
        "Próximo a agir:" in (state.last_context or "")
        or "já realizou sua ação nesta rodada" in (state.last_context or "")
        or "está inconsciente e não pode atacar" in (state.last_context or "")
        or "Valor inválido! O d20 físico possui apenas valores de 1 a 20" in (state.last_context or "")
        or "informe o resultado do seu d20 físico de 1 a 20" in (state.last_context or "")
    )
    if is_mid_round_turn:
        npc_message = Message(
            sender="Dungeon Master",
            content=state.last_context,
            role="assistant",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        state.recent_messages.append(npc_message)
        return {
            "recent_messages": state.recent_messages,
            "last_context": state.last_context,
        }

    effective_system_prompt = (
        state.npcs[0].system_prompt
        if state.npcs and state.npcs[0].system_prompt
        else EXPLORATION_PROMPT
    )

    active_monster = _get_active_monster(state)
    monster_fell = "Monstro HP: 0/" in (state.last_context or "") or (
        active_monster is not None and active_monster.is_defeated
    )
    defeated_tag = "\n[MONSTRO DERROTADO]" if monster_fell else ""

    sender_hero = _find_sender_hero(state)
    hero_name = sender_hero.name if sender_hero else "Recruta"
    if hero_name == "Recruta":
        last_user_msg = next((m for m in reversed(state.recent_messages) if m.role == "user"), None)
        if last_user_msg and last_user_msg.sender and not last_user_msg.sender.isdigit() and last_user_msg.sender != "Jogador":
            hero_name = last_user_msg.sender

    is_exploration = "Roleplay e Exploração" in (state.last_context or "")
    if is_exploration and len(state.recent_messages) > 1:
        dialogue_history = "\n".join(
            f"{m.sender}: {m.content}" for m in state.recent_messages[-6:-1]
        )
        prompt_context = (
            f"Contexto do Treino e Ambiente:\n{state.last_context}\n\n"
            f"Diálogo recente:\n{dialogue_history}\n\n"
            f"Última mensagem enviada por {hero_name}: \"{last_user_message}\""
        )
    elif state.last_context:
        prompt_context = (
            f"Contexto do Treino e Regras:\n{state.last_context}{defeated_tag}\n\n"
            f"Última mensagem enviada por {hero_name}: \"{last_user_message}\""
        )
    else:
        prompt_context = f"Última mensagem enviada por {hero_name}: \"{last_user_message}\""

    logger.info(f"Gerando resposta do Loomis via LLM para: '{prompt_context}'")
    try:
        resposta_texto = await llm_client.generate_reply(
            message=prompt_context,
            system_prompt=effective_system_prompt,
        )
    except Exception as e:
        logger.warning(f"Falha ao gerar fala do Loomis via LLM ({repr(e)}), usando fala padrão de treino.")
        if state.is_victory:
            resposta_texto = "Vocês conseguiram, recrutas! Todas as 4 jaulas foram superadas! Vocês agora são os verdadeiros Heróis de Hesiod!"
        elif monster_fell:
            resposta_texto = "A fera caiu! Excelente golpe, recrutas! Mas mantenham o foco que a próxima jaula está à frente!"
        elif "declare sua ação e o valor" in (state.last_context or ""):
            resposta_texto = "De nada adianta empunhar a arma sem atacar de verdade! Mantenham a postura e preparem o golpe!"
        else:
            resposta_texto = "Fiquem atentos e mantenham a formação! Hesiod conta com a coragem de vocês!"

    speech = re.sub(r"<[^>]+>", "", resposta_texto).strip()
    speech = re.sub(r'^["\'«»\s]*(?:Loomis\s*:\s*["\'«»\s]*)+', "", speech, flags=re.IGNORECASE).strip()
    speech = speech.strip("\"'«»").strip()

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
    """Roteia o fluxo entre combate, conselho tático e exploração com trava anti-dispersão."""
    last_user_message = state.get_last_user_message()
    intent = await classify_intent(last_user_message)

    active_monster = _get_active_monster(state)
    beast_in_arena = bool(active_monster and not active_monster.is_defeated and active_monster.hp > 0) and _is_combat_active(state)
    if intent == "exploration" and beast_in_arena:
        return "tactical_advice"

    return intent


def build_turn_graph():
    """Compila e retorna o fluxo do LangGraph para o ciclo de turno."""
    workflow = StateGraph(GameState)

    workflow.add_node("combat", combat_node)
    workflow.add_node("tactical_advice", tactical_advice_node)
    workflow.add_node("exploration", exploration_node)
    workflow.add_node("npc", npc_node)

    workflow.add_conditional_edges(
        START,
        route_intent,
        {
            "combat": "combat",
            "tactical_advice": "tactical_advice",
            "exploration": "exploration",
        },
    )
    workflow.add_edge("combat", "npc")
    workflow.add_edge("tactical_advice", "npc")
    workflow.add_edge("exploration", "npc")
    workflow.add_edge("npc", END)

    return workflow.compile()


turn_graph = build_turn_graph()
