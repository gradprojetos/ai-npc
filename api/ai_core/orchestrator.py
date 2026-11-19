import asyncio
import logging
import re
from datetime import datetime, timezone
from api.ai_core.turn_graph import turn_graph
from api.motor_rpg.session_service import (
    get_or_create_session_state,
    persist_session_state_to_db,
)
from api.schemas.rpg import GameState, Message

logger = logging.getLogger(__name__)


def is_noise_input(text: str | None) -> bool:
    """Identifica entradas vazias ou pontuação isolada, preservando rolagens numéricas de 1–2 dígitos."""
    if not text or not text.strip():
        return True
    if re.fullmatch(r"\s*-?\d+\s*", text):
        return False
    alnum_chars = re.findall(r"[a-zA-Z0-9À-ÿ]", text)
    return len(alnum_chars) < 2


async def process_npc_turn(user_message: str, user_info: dict | None = None) -> str:
    """Orquestra o turno do NPC recebendo a mensagem do jogador e devolvendo a resposta da IA."""
    chat_id = user_info.get("chat_id") if user_info else None
    session_id = str(user_info.get("session_id") or chat_id or "default_session") if user_info else "default_session"

    logger.info(f"Processando turno do NPC para session_id={session_id}: '{user_message}'")

    state = await asyncio.to_thread(get_or_create_session_state, session_id, user_info=user_info)

    if state.is_recruiting:
        if not state.players:
            return "A arena ainda está fechada! Escolham seus heróis com <code>/select &lt;1-5&gt;</code> e depois usem <code>/done</code> para começar."
        return (
            f"Recrutas alistados até agora: <b>{', '.join(p.name for p in state.players)}</b>.\n"
            f"Quando todos tiverem escolhido, digitem <code>/done</code> para Loomis abrir a Jaula 1 e iniciar a luta!"
        )

    if is_noise_input(user_message):
        return '<b>Loomis:</b>\n"Fale com clareza, recruta! Diga o que pretende fazer na arena!"'

    sender = str(user_info.get("telegram_id") or user_info.get("player_id") or "Jogador") if user_info else "Jogador"
    state.recent_messages.append(
        Message(
            sender=sender,
            content=user_message,
            role="user",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    raw_final = await turn_graph.ainvoke(state)
    final_state = GameState(**raw_final) if isinstance(raw_final, dict) else raw_final

    await asyncio.to_thread(persist_session_state_to_db, final_state, chat_id=chat_id)

    if final_state.recent_messages and final_state.recent_messages[-1].role == "assistant":
        return final_state.recent_messages[-1].content
    return ""
