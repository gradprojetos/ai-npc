import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from api.ai_core.orchestrator import process_npc_turn
from api.motor_rpg.session_service import (
    finish_recruiting_for_session,
    reset_player_session,
    select_hero_for_player,
)
from api.routers.game import router as game_router
from telegram_bot.telegram_service import TelegramService

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

telegram_service = TelegramService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if telegram_service.token:
        logger.info("Inicializando serviço do Telegram Bot...")
        try:
            await telegram_service.setup(
                on_message=process_npc_turn,
                on_reset=reset_player_session,
                on_select=select_hero_for_player,
                on_done=finish_recruiting_for_session,
            )
            await telegram_service.set_webhook()
        except Exception as e:
            logger.warning(f"Telegram Bot não inicializado: {e}")
    else:
        logger.info("TELEGRAM_BOT_TOKEN não configurado. Operando em modo API REST pura.")

    yield

    if telegram_service.app:
        logger.info("Encerrando serviço do Telegram Bot...")
        await telegram_service.shutdown()


app = FastAPI(title="AI NPC Main API", lifespan=lifespan)
app.include_router(game_router, prefix="/game", tags=["Game"])


@app.get("/")
async def health_check():
    return {"status": "online", "service": "AI NPC Main API"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Endpoint público consumido pelo Telegram via HTTP POST."""
    try:
        data = await request.json()
        asyncio.create_task(telegram_service.process_update(data))
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}", exc_info=True)
        # Retorna 200 para evitar que o Telegram reenvie a mesma atualização em loop infinito
        return {"status": "error_handled", "detail": str(e)}
