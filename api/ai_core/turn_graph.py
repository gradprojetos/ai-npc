import re
import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from api.schemas.rpg import GameState, Message
from llm_gateway.client import LLMClient
from api.motor_rpg.motor_rpg import resolve_hero_attack, resolve_monster_attack, get_cage_monster, create_hero
from db.models import NPC
from db.session import SessionLocal

logger = logging.getLogger(__name__)
llm_client = LLMClient()

# Buffers temporários de execução em memória por sessão
_round_buffers: dict[str, list[str]] = {}
_last_monster_targets: dict[str, str] = {}
_exploration_counters: dict[str, int] = {}


async def extract_d20(text: str) -> int | None:
    """Extrai a rolagem física de um d20 (1 a 20) informada pelo jogador."""
    if not text.strip():
        return None

    # 1. Tenta padrão com palavras indicadoras: "com 15", "c 20", "rolei 18", "dado 12", "d20 20", etc.
    match = re.search(
        r"\b(?:d20|tirei|rolei|deu|com|c|dado|número|numero)\s*[:=]?\s*([1-9]|1[0-9]|20)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return int(match.group(1))

    # 2. Busca qualquer número isolado de 1 a 20 dentro da mensagem (ex: "ataco 20", "20")
    numbers = re.findall(r"\b([1-9]|1[0-9]|20)\b", text)
    if numbers:
        return int(numbers[-1])

    return None


async def classify_intent(text: str) -> str:
    """Classifica a intenção da mensagem via LLM ('combat', 'tactical_advice' ou 'exploration')."""
    if not text.strip():
        return "exploration"

    prompt = (
        "Você é o classificador de intenções de um RPG de mesa textual.\n"
        "Classifique a mensagem do jogador em estritamente UMA das 3 categorias:\n"
        "1. 'combat': Ações de ataque, golpes, tiros, magias ofensivas, dados (d20), ou confirmação de prontidão para iniciar a luta / abrir jaula (ex: 'estamos prontos', 'pode abrir', 'vamos lutar', 'puxa a alavanca', 'bora').\n"
        "2. 'tactical_advice': Perguntas sobre regras de combate, fraquezas do monstro atual ou conselho sobre como usar poderes da carta de herói.\n"
        "3. 'exploration': Conversa livre, perguntas sobre a vila de Hesiod, investigar a cabana, caldeirão de poção, ferramentas, lore ou passado de Loomis.\n\n"
        "Responda APENAS: 'combat', 'tactical_advice' ou 'exploration'."
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
        if "tactical" in decision or "advice" in decision:
            return "tactical_advice"
        return "exploration"
    except Exception as e:
        logger.warning(f"Falha ao classificar intenção via LLM ({repr(e)}), aplicando fallback por regex.")
        d20 = await extract_d20(text)
        if d20 is not None:
            return "combat"
        ready_pattern = r"\b(?:pront[oa]s?|vamos lutar|abrir|abre a jaula|puxa a alavanca|bora|começar)\b"
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
    hero = state.players[0] if state.players else None
    monster = next((m for m in state.monsters if not m.is_defeated), None)

    last_msg = state.get_last_user_message().lower()
    is_dispersion = any(w in last_msg for w in ["cabana", "passear", "riacho", "olhar", "investigar", "procurar", "sair"])

    context_parts: list[str] = []
    if monster and is_dispersion:
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


def exploration_node(state: GameState) -> dict:
    """Nó para roleplay livre, investigação do cenário e diálogo com Loomis na clareira."""
    logger.info("Executando nó de exploração...")
    count = _exploration_counters.get(state.session_id, 0) + 1
    _exploration_counters[state.session_id] = count

    context_parts = ["Ação Livre (Roleplay e Exploração na Clareira de Treino):"]

    if count >= 7:
        beast = state.monsters[0] if state.monsters else get_cage_monster(1)
        state.location = f"Arena de Hesiod — Jaula {beast.cage_number} Aberta"
        _exploration_counters[state.session_id] = 0
        context_parts.append(
            f"Gatilho Forçado de Combate: Loomis perdeu a paciência com o grupo após {count} mensagens de conversa!\n"
            f"Ele puxa a alavanca da Jaula 1 por conta própria, solta o {beast.name} na arena e grita para os recrutas assumirem formação de batalha imediatamente!"
        )
    elif count >= 4:
        context_parts.append(
            "Loomis impaciente: Responda brevemente ao que foi perguntado, mas corte a conversa mole e pressione com firmeza: "
            "'Chega de conversa mole e de passar a mão na madeira da cabana, recrutas! As feras estão farejando o almoço. Vamos abrir a Jaula 1 ou vocês vão amarelar?'"
        )
    else:
        context_parts.append(
            "Loomis acolhedor: Responda com simpatia e experiência de veterano às perguntas sobre a vila de Hesiod, "
            "as ferramentas, a cabana rústica e o caldeirão de poção revigorante de menta e limão. Lembre-os amigavelmente de avisar quando estiverem prontos."
        )

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

    # Identifica o herói que está agindo com base no remetente da mensagem
    hero = state.players[0]
    last_user_msg = next((m for m in reversed(state.recent_messages) if m.role == "user"), None)
    if last_user_msg and state.players:
        sender = last_user_msg.sender
        for p in state.players:
            if p.player_id == sender or (sender and sender in p.name):
                hero = p
                break

    # Identifica o monstro alvo (se houver mais de um e o jogador tiver citado o nome)
    monster = state.monsters[0]
    last_msg_lower = last_user_message.lower()
    for m in state.monsters:
        if not m.is_defeated and any(part in last_msg_lower for part in m.name.lower().split()):
            monster = m
            break

    # Abre a jaula para combate se ainda estiver na fase de exploração
    if "Aberta" not in (state.location or ""):
        cage_num = monster.cage_number if monster else 1
        state.location = f"Arena de Hesiod — Jaula {cage_num} Aberta"
        _exploration_counters[state.session_id] = 0

    # Se o d20 não foi informado: sinaliza abertura da jaula e pede rolagem física
    if d20 is None:
        lines = [
            "<b>Dungeon Master:</b>",
            f"• A Jaula {monster.cage_number} foi aberta e <b>{monster.name}</b> entrou na arena [HP: {monster.hp}/{monster.max_hp} | CA: {monster.ac}]!",
            f"• <b>{hero.name}</b>, declare sua ação e o valor do seu d20 físico (ex: <i>\"ataco com 17\"</i>)!",
        ]
        state.last_context = "\n".join(lines)
        return {
            "last_context": state.last_context,
            "players": state.players,
            "monsters": state.monsters,
            "recent_messages": state.recent_messages,
        }

    initial_monster_name = monster.name
    round_actions = _round_buffers.setdefault(state.session_id, [])

    # 1. Ataque do Herói atual (acumulado para o resumo da rodada)
    hero_res = resolve_hero_attack(hero=hero, monster=monster, d20=d20)
    if hero_res["is_critical"]:
        h_dmg = hero_res["damage_dealt"]
        hero_action_text = f"acertou criticamente {h_dmg} de dano! [Monstro HP: {monster.hp}/{monster.max_hp}]"
    elif hero_res["is_hit"]:
        hero_action_text = f"acertou 1 de dano! [Monstro HP: {monster.hp}/{monster.max_hp}]"
    else:
        hero_action_text = f"errou o golpe! [Monstro HP: {monster.hp}/{monster.max_hp}]"

    round_actions.append(
        f"• <b>{hero.name}</b> atacou <b>{initial_monster_name}</b> com {hero.attack_name} e {hero_action_text}"
    )

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
        round_actions.append(f"• <b>{new_beast.name}</b> entrou na arena! [Monstro HP: {new_beast.hp}/{new_beast.max_hp}]")

    # 3. Derrota do Monstro
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
                round_actions.append(f"• Loomis curou {', '.join(healed)} com a poção!")

            if monster.cage_number >= 4:
                state.is_victory = True
                round_actions.append("• Todas as 4 jaulas foram superadas!")
            else:
                next_cage = monster.cage_number + 1
                next_beast = get_cage_monster(next_cage)
                state.monsters = [next_beast]

    # 4. Rotaciona a fila de iniciativa dos heróis
    state.rotate_players()

    # 5. Verifica se a rodada terminou (todos os jogadores conscientes já declararam ação)
    total_active_heroes = len([h for h in state.players if not h.is_unconscious]) or 1
    round_finished = len(round_actions) >= total_active_heroes or state.is_victory

    if not round_finished:
        # Rodada ainda em andamento: não envia mensagem do DM nem do Loomis agora
        state.last_context = None
        return {
            "last_context": None,
            "players": state.players,
            "monsters": state.monsters,
            "is_victory": state.is_victory,
            "recent_messages": state.recent_messages,
        }

    # 6. Rodada Encerrada: Turno dos Monstros (cada fera viva ataca 1 vez)
    dm_lines = ["<b>Dungeon Master:</b>"] + round_actions
    _round_buffers.pop(state.session_id, None)

    if not state.is_victory:
        alive_beasts = [m for m in state.monsters if not m.is_defeated]
        conscious_heroes = [h for h in state.players if not h.is_unconscious]
        last_target_id = _last_monster_targets.get(state.session_id)

        for beast in alive_beasts:
            if not conscious_heroes:
                break
            # Regra canônica: priorizar maior HP, mas excluir o alvo atingido no turno anterior se houver outro herói consciente
            candidates = [h for h in conscious_heroes if h.player_id != last_target_id] if len(conscious_heroes) > 1 else conscious_heroes
            target_hero = max(candidates, key=lambda h: h.hp)
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
                conscious_heroes.remove(target_hero)

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

    # Se a rodada ainda estiver aberta aguardando outros heróis, não dispara mensagem
    if state.last_context is None and not state.is_victory:
        return {
            "recent_messages": state.recent_messages,
        }

    effective_system_prompt = state.npcs[0].system_prompt if state.npcs and state.npcs[0].system_prompt else ""
    if not effective_system_prompt:
        try:
            with SessionLocal() as db:
                db_npc = db.query(NPC).filter_by(name="Loomis").first()
                if db_npc:
                    effective_system_prompt = db_npc.system_prompt
        except Exception as e:
            logger.debug(f"Não foi possível carregar prompt do NPC do banco: {e}")

    monster_fell = "HP: 0/" in (state.last_context or "") or any(m.is_defeated for m in state.monsters)
    defeated_tag = "\n[MONSTRO DERROTADO]" if monster_fell else ""

    # Memória de curto prazo seletiva: exploração recebe histórico recente; combate apenas resumo mecânico
    is_exploration = "Roleplay e Exploração" in (state.last_context or "")
    if is_exploration and len(state.recent_messages) > 1:
        dialogue_history = "\n".join(
            f"{m.sender}: {m.content}" for m in state.recent_messages[-6:-1]
        )
        prompt_context = (
            f"Contexto do Treino e Ambiente:\n{state.last_context}\n\n"
            f"Diálogo recente:\n{dialogue_history}\n\n"
            f"Mensagem atual do jogador: {last_user_message}"
        )
    elif state.last_context:
        prompt_context = f"Contexto do Treino e Regras:\n{state.last_context}{defeated_tag}\n\nMensagem do jogador: {last_user_message}"
    else:
        prompt_context = last_user_message

    logger.info(f"Gerando resposta do Loomis via LLM para: '{prompt_context}'")
    try:
        resposta_texto = await llm_client.generate_reply(
            message=prompt_context,
            system_prompt=effective_system_prompt,
            model="ministral-3:8b",
        )
    except Exception as e:
        logger.warning(f"Falha ao gerar fala do Loomis via LLM ({repr(e)}), usando fala padrão de treino.")
        if state.is_victory:
            resposta_texto = "Vocês conseguiram, recrutas! Todas as 4 jaulas foram superadas! Vocês agora são os verdadeiros Heróis de Hesiod!"
        elif monster_fell:
            resposta_texto = "A fera caiu! Excelente golpe, recrutas! Mas mantenham o foco que a próxima jaula está à frente!"
        elif "nenhuma rolagem de dado válida" in (state.last_context or "") or "declare sua ação e o valor" in (state.last_context or ""):
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
    """Roteia o fluxo entre combate, conselho tático e exploração com trava anti-dispersão."""
    last_user_message = state.get_last_user_message()
    intent = await classify_intent(last_user_message)

    # Trava de Combate Ativo (Anti-Dispersão):
    # Se houver fera viva na arena com Jaula aberta, intercepta tentativa de exploração livre
    beast_in_arena = any(not m.is_defeated for m in state.monsters) and "Aberta" in (state.location or "")
    if intent == "exploration" and beast_in_arena:
        return "tactical_advice"

    return intent


def build_turn_graph():
    """Compila e retorna o fluxo do LangGraph para o ciclo de turno."""
    workflow = StateGraph(GameState)

    # Registro dos nós
    workflow.add_node("combat", combat_node)
    workflow.add_node("tactical_advice", tactical_advice_node)
    workflow.add_node("exploration", exploration_node)
    workflow.add_node("npc", npc_node)

    # Bifurcação a partir do START
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