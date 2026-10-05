import asyncio
import logging
from datetime import datetime, timezone
from api.ai_core.turn_graph import turn_graph
from api.motor_rpg.session_service import (
    get_or_create_session_state,
    persist_session_state_to_db,
    set_memory_session,
)
from api.schemas.rpg import GameState, Message

logger = logging.getLogger(__name__)


async def process_npc_turn(user_message: str, user_info: dict | None = None) -> str:
    """Orquestra o turno do NPC recebendo a mensagem do jogador e devolvendo a resposta da IA.

    Fluxo:
    1. Recupera ou inicializa a sessão (PostgreSQL com fallback em memória).
    2. Registra a mensagem do usuário no buffer recente.
    3. Executa o ciclo cognitivo e mecânico no LangGraph.
    4. Persiste o estado atualizado no banco via threadpool assíncrono.
    5. Retorna a fala de Loomis para o usuário.
    """
    chat_id = user_info.get("chat_id") if user_info else None
    session_id = str(user_info.get("session_id") or chat_id or "default_session") if user_info else "default_session"

    logger.info(f"Processando turno do NPC para session_id={session_id}: '{user_message}'")

    # 1. Recupera ou cria estado básico (Jaula 1 ativa com herói) sem travar o loop de eventos
    state = await asyncio.to_thread(get_or_create_session_state, session_id, user_info=user_info)

    # 2. Registra a mensagem do usuário no buffer recente
    state.recent_messages.append(
        Message(
            sender="Jogador",
            content=user_message,
            role="user",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )

    # 3. Executa o grafo do LangGraph
    raw_final = await turn_graph.ainvoke(state)
    final_state = GameState(**raw_final) if isinstance(raw_final, dict) else raw_final

    # 4. Salva o estado atualizado na memória e no banco relacional de forma assíncrona
    set_memory_session(session_id, final_state)
    await asyncio.to_thread(persist_session_state_to_db, final_state, chat_id=chat_id)

    # 5. Retorna a última mensagem do Loomis
    if final_state.recent_messages:
        return final_state.recent_messages[-1].content
    return "Loomis observa com firmeza, aguardando seu próximo movimento."
