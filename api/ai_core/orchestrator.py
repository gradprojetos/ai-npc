import logging
from llm_gateway.client import LLMClient

logger = logging.getLogger(__name__)

llm_client = LLMClient()


async def process_npc_turn(user_message: str, user_info: dict | None = None) -> str:
    """Orquestra o turno do NPC recebendo a mensagem do jogador e devolvendo a resposta da IA.
    
    No futuro, aqui entrará o grafo do LangGraph e integração com Guardrails/RAG.
    """
    user_id = user_info.get("telegram_id") if user_info else None
    logger.info(f"Processando turno do NPC para jogador telegram_id={user_id}: {user_message}")

    # Por enquanto, chamada direta ao LLMClient
    resposta = await llm_client.generate_reply(message=user_message)
    return resposta
