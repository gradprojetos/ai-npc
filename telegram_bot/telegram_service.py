import os
import httpx
import asyncio
import logging
from typing import Callable, Awaitable
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
        self.app: Application | None = None
        self.on_message_callback: Callable[[str, dict], Awaitable[str]] | None = None
        self.on_reset_callback: Callable[[int], Awaitable[None]] | None = None

    async def setup(
        self, 
        on_message: Callable[[str, dict], Awaitable[str]],
        on_reset: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        """Inicializa a aplicação do Telegram recebendo o orquestrador e handler de reset como callbacks."""
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado.")

        self.on_message_callback = on_message
        self.on_reset_callback = on_reset
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler("start", self._start_handler))
        self.app.add_handler(CommandHandler("reset", self._reset_handler))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._message_handler))

        await self.app.initialize()
        await self.app.start()
        logger.info("Telegram Application inicializada com sucesso.")

    async def _get_cloudflared_url(self) -> str | None:
        """Tenta descobrir a URL pública gerada pelo container do cloudflared na rede Docker."""
        logger.info("Tentando descobrir URL pública via container cloudflared (aguardando até 30s)...")
        for _ in range(30):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get("http://cloudflared:4567/quicktunnel", timeout=2.0)
                    if resp.status_code == 200:
                        hostname = resp.json().get("hostname")
                        if hostname and len(hostname) > 5:
                            logger.info(f"URL encontrada ({hostname}). Aguardando 6s para o DNS publicar mundialmente...")
                            await asyncio.sleep(6)
                            return f"https://{hostname}/webhook"
            except Exception:
                pass
            await asyncio.sleep(1)
        return None

    async def set_webhook(self) -> None:
        if not self.app:
            raise RuntimeError("Serviço precisa ser inicializado via setup() antes do webhook.")

        url_to_set = self.webhook_url
        if not url_to_set:
            url_to_set = await self._get_cloudflared_url()

        if not url_to_set:
            raise ValueError("TELEGRAM_WEBHOOK_URL não configurada e auto-descoberta do cloudflared falhou.")

        # Tenta registrar no Telegram com retries para dar tempo do DNS do Cloudflare propagar mundialmente
        for attempt in range(5):
            try:
                await self.app.bot.set_webhook(url=url_to_set)
                logger.info(f"Webhook configurado com sucesso para: {url_to_set}")
                return
            except Exception as e:
                logger.warning(f"Tentativa {attempt + 1}/5 de registrar Webhook falhou ({e}). Aguardando 3s para propagação de DNS...")
                await asyncio.sleep(3)

        raise RuntimeError(f"Falha ao registrar Webhook no Telegram após retries: {url_to_set}")

    async def process_update(self, request_json: dict) -> None:
        if not self.app:
            raise RuntimeError("Serviço não inicializado.")
        update = Update.de_json(data=request_json, bot=self.app.bot)
        await self.app.process_update(update)

    async def shutdown(self) -> None:
        if self.app:
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram Application finalizada.")

    async def _start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text("Olá! Eu sou seu NPC. Fale comigo!")

    async def _reset_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /reset para apagar o histórico e recomeçar a conversa."""
        if not update.message or not update.effective_user:
            return

        telegram_id = update.effective_user.id
        if self.on_reset_callback:
            try:
                await self.on_reset_callback(telegram_id)
                await update.message.reply_text("🧹 Histórico e memória apagados! Pode começar de novo.")
            except Exception as e:
                logger.error(f"Erro ao processar /reset: {e}", exc_info=True)
                await update.message.reply_text("Ocorreu um erro ao tentar reiniciar seu histórico.")
        else:
            await update.message.reply_text("Comando de reset não configurado.")

    async def _message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Recebe texto, passa para a main.py processar e devolve a resposta."""
        if not update.message or not update.message.text or not self.on_message_callback:
            return

        user_text = update.message.text
        user = update.effective_user
        chat = update.effective_chat
        user_info = {
            "telegram_id": user.id if user else None,
            "username": user.username if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "chat_id": chat.id if chat else None,
        }

        await update.message.chat.send_action(action="typing")

        try:
            # Chama o orquestrador passando a mensagem e os metadados do jogador
            reply_text = await self.on_message_callback(user_text, user_info)
        except Exception as e:
            logger.error(f"Erro no orquestrador: {e}", exc_info=True)
            reply_text = "Desculpe, ocorreu um erro interno ao pensar."

        await update.message.reply_text(reply_text)
