import os
import re
import inspect
import httpx
import asyncio
import logging
from typing import Callable, Awaitable, Any
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
        self.app: Application | None = None
        self.on_message_callback: Callable[[str, dict], Awaitable[str]] | None = None
        self.on_reset_callback: Callable[[int], Any] | None = None

    async def setup(
        self, 
        on_message: Callable[[str, dict], Awaitable[str]],
        on_reset: Callable[[int], Any] | None = None,
    ) -> None:
        """Inicializa a aplicação do Telegram recebendo o orquestrador e handler de reset como callbacks."""
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado.")

        self.on_message_callback = on_message
        self.on_reset_callback = on_reset
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler("start", self._start_handler))
        self.app.add_handler(CommandHandler("reset", self._reset_handler))
        self.app.add_handler(MessageHandler(filters.TEXT, self._message_handler))

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
            await update.message.reply_text(
                "Olá recruta! Eu sou <b>Loomis</b>, o treinador de Hesiod!\n"
                "Diga-me o que quer fazer ou ataque a fera na jaula!\n\n"
                "• Use <code>/reset</code> para reiniciar o treino.",
                parse_mode="HTML",
            )

    async def _reset_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /reset para apagar a sessão inteira da arena/grupo e recomeçar a partida."""
        if not update.message or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user
        # Em grupo, o reset zera a sessão compartilhada do grupo inteiro (chat.id)
        target_id = chat.id if chat else user.id
        logger.info(f"Comando /reset recebido de user_id={user.id} para session target_id={target_id}")

        if self.on_reset_callback:
            try:
                if inspect.iscoroutinefunction(self.on_reset_callback):
                    await self.on_reset_callback(target_id)
                else:
                    await asyncio.to_thread(self.on_reset_callback, target_id)

                reply_msg = (
                    "<b>Sessão de jogo reiniciada com sucesso!</b>\n\n"
                    "• <b>Arena de Hesiod:</b> Restaurada para a <b>Jaula 1</b> com o <b>Bullette Faminto</b> (HP: 8/8 | CA: 15).\n"
                    "• <b>Grupo e Heróis:</b> Status de combate e histórico de todos os recrutas zerados.\n\n"
                    "<b>Loomis:</b> <i>\"A jaula está trancada de novo! Parem de conversa fiada, peguem seus dados e me mostrem do que são capazes!\"</i>"
                )
                try:
                    await update.message.reply_text(reply_msg, parse_mode="HTML")
                except Exception:
                    await update.message.reply_text(
                        "Sessão de jogo reiniciada com sucesso! A arena de Hesiod foi restaurada: Jaula 1 trancada com o Bullette Faminto (HP 8/8) e histórico zerado."
                    )
            except Exception as e:
                logger.error(f"Erro ao processar /reset: {e}", exc_info=True)
                await update.message.reply_text("Ocorreu um erro ao tentar reiniciar a sessão do jogo.")
        else:
            await update.message.reply_text("Comando de reset não configurado.")

    async def _message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Recebe texto, passa para a main.py processar e devolve a resposta."""
        if not update.message or not update.message.text or not self.on_message_callback:
            return

        chat = update.effective_chat
        user = update.effective_user
        raw_text = update.message.text.strip()
        is_command = raw_text.startswith("/")

        # Em grupos, se for mensagem de texto comum (não-comando) dirigida a outro humano, a IA não responde:
        if not is_command and chat and chat.type in ("group", "supergroup"):
            # 1. Se for reply direcionado a outro usuário humano:
            if update.message.reply_to_message and update.message.reply_to_message.from_user:
                if update.message.reply_to_message.from_user.id != context.bot.id:
                    return

            # 2. Se contiver menção @ a outro usuário que não seja o bot:
            mentions = re.findall(r"@([a-zA-Z0-9_]+)", raw_text)
            bot_username = (context.bot.username or "").lower()
            other_mentions = [m for m in mentions if m.lower() != bot_username]
            if other_mentions:
                return

        user_text = raw_text
        if context.bot.username:
            user_text = re.sub(rf"@{re.escape(context.bot.username)}", "", user_text, flags=re.IGNORECASE).strip()

        logger.info(f"Mensagem recebida [chat_id={chat.id if chat else None}, user={user.username if user else None}]: '{user_text}'")

        user_info = {
            "telegram_id": user.id if user else None,
            "username": user.username if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "chat_id": chat.id if chat else None,
        }

        try:
            await update.message.chat.send_action(action="typing")
        except Exception as e:
            logger.debug(f"Não foi possível enviar typing action: {e}")

        try:
            # Chama o orquestrador passando a mensagem e os metadados do jogador
            reply_text = await self.on_message_callback(user_text, user_info)
            logger.info(f"Resposta enviada para chat_id={chat.id if chat else None}: '{reply_text[:60]}...'")
        except Exception as e:
            logger.error(f"Erro no orquestrador: {e}", exc_info=True)
            reply_text = "Desculpe, ocorreu um erro interno ao pensar."

        try:
            await update.message.reply_text(reply_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Erro ao enviar resposta com parse_mode=HTML: {e}. Enviando como texto puro.")
            await update.message.reply_text(reply_text)
