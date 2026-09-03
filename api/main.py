from contextlib import asynccontextmanager
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request

from api.ai_core.orchestrator import process_npc_turn
from api.motor_rpg.session_service import reset_player_session
from telegram_bot.telegram_service import TelegramService

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

telegram_service = TelegramService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando serviço do Telegram Bot...")

    await telegram_service.setup(
        on_message=process_npc_turn,
        on_reset=reset_player_session,
    )

    try:
        await telegram_service.set_webhook()
    except Exception as e:
        logger.warning(f"Não foi possível configurar o Webhook automaticamente: {e}")

    yield

    logger.info("Encerrando serviço do Telegram Bot...")
    await telegram_service.shutdown()


app = FastAPI(title="AI NPC Main API", lifespan=lifespan)


@app.get("/")
async def health_check():
    return {"status": "online", "service": "AI NPC Main API"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Endpoint público consumido pelo Telegram via HTTP POST."""
    try:
        data = await request.json()
        await telegram_service.process_update(data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}", exc_info=True)
        # Retorna 200 para evitar que o Telegram reenvie a mesma atualização em loop infinito
        return {"status": "error_handled", "detail": str(e)}
