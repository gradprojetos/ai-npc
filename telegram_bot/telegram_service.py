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


def format_to_telegram_html(text: str) -> str:
    """Converte Markdown para tags HTML e escapa caracteres fora de tags válidas do Telegram."""
    if not text:
        return ""
    # Converte **negrito** para <b>negrito</b>
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Converte *itálico* para <i>itálico</i>
    formatted = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", formatted)
    # Converte `código` para <code>código</code>
    formatted = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", formatted)

    # Escapa caracteres &, <, > fora de tags HTML válidas do Telegram
    valid_tag_pattern = r"(</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote|tg-spoiler)\b[^>]*>|<a\s+href=\"[^\"]+\"[^>]*>|</a>)"
    tokens = re.split(valid_tag_pattern, formatted, flags=re.IGNORECASE)
    parts: list[str] = []
    for i, token in enumerate(tokens):
        if i % 2 == 1:
            parts.append(token)
        else:
            escaped = re.sub(r"&(?!amp;|lt;|gt;|quot;)", "&amp;", token)
            escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
            parts.append(escaped)
    return "".join(parts)


async def _invoke_callback(callback: Callable, *args, **kwargs) -> Any:
    """Invoca callback seja ele assíncrono ou síncrono sem travar o event loop."""
    if inspect.iscoroutinefunction(callback):
        return await callback(*args, **kwargs)
    return await asyncio.to_thread(callback, *args, **kwargs)


class TelegramService:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
        self.bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "pfg_npc_bot").lower()
        self.app: Application | None = None
        self.on_message_callback: Callable[[str, dict], Awaitable[str]] | None = None
        self.on_reset_callback: Callable[[int], Any] | None = None
        self.on_select_callback: Callable[..., Any] | None = None

    async def setup(
        self, 
        on_message: Callable[[str, dict], Awaitable[str]],
        on_reset: Callable[[int], Any] | None = None,
        on_select: Callable[..., Any] | None = None,
    ) -> None:
        """Inicializa a aplicação do Telegram recebendo callbacks para mensagem, reset e seleção de herói."""
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado.")

        self.on_message_callback = on_message
        self.on_reset_callback = on_reset
        self.on_select_callback = on_select
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler(["start"], self._start_handler))
        self.app.add_handler(CommandHandler(["select", "escolher"], self._select_handler))
        self.app.add_handler(CommandHandler(["ajuda", "help"], self._ajuda_handler))
        self.app.add_handler(CommandHandler(["reset"], self._reset_handler))
        self.app.add_handler(MessageHandler(filters.TEXT, self._message_handler))

        await self.app.initialize()
        await self.app.start()
        try:
            bot_me = await self.app.bot.get_me()
            if bot_me and bot_me.username:
                self.bot_username = bot_me.username.lower()
        except Exception as e:
            logger.debug(f"Não foi possível obter username do bot via get_me: {e}")
        logger.info(f"Telegram Application inicializada com sucesso (bot_username=@{self.bot_username}).")

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
        """Apresenta a Arena de Hesiod e recruta os jogadores com as 5 cartas canônicas."""
        if not update.message:
            return
        cards_text = (
            "<b>Arena de Treinamento de Hesiod</b>\n\n"
            "Eu sou <b>Loomis</b>, o treinador da vila de Hesiod! "
            "Antes de abrirmos as jaulas, cada recruta deve escolher sua carta:\n\n"
            "• <code>/select 1</code> - <b>Evindol</b> (Ladino Humano | CA 11 | HP 3 | Ataque +6)\n"
            "• <code>/select 2</code> - <b>Raen</b> (Bárbara Anã | CA 9 | HP 7 | Ataque +5)\n"
            "• <code>/select 3</code> - <b>Jorick</b> (Guerreiro Humano | CA 13 | HP 5 | Ataque +4)\n"
            "• <code>/select 4</code> - <b>Yarrow</b> (Xamã Meio-Orc | CA 10 | HP 6 | Ataque +3)\n"
            "• <code>/select 5</code> - <b>Bet</b> (Maga Elfa | CA 7 | HP 4 | Ataque +7)\n\n"
            "Digite <code>/select &lt;1-5&gt;</code> para alistar seu herói na arena!"
        )
        try:
            await update.message.reply_text(cards_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(cards_text)

    async def _select_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /select <1-5> para o jogador escolher sua ficha no grupo."""
        if not update.message or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user
        session_id = str(chat.id if chat else user.id)
        player_name = user.first_name or user.username or f"Recruta_{user.id}"

        args = context.args or []
        if not args:
            await update.message.reply_text(
                "Informe o número da carta! Exemplo: <code>/select 2</code>.",
                parse_mode="HTML",
            )
            return

        choice = args[0]
        if self.on_select_callback:
            try:
                success, reply_msg, _ = await self._invoke_callback(
                    self.on_select_callback, session_id, str(user.id), player_name, choice
                )
            except Exception as e:
                logger.error(f"Erro ao selecionar herói: {e}", exc_info=True)
                reply_msg = "Ocorreu um erro ao selecionar o herói."
        else:
            reply_msg = "Seleção de herói não configurada."

        try:
            await update.message.reply_text(reply_msg, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(reply_msg)

    async def _ajuda_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /ajuda para explicar comandos e regras de jogo em formato HTML."""
        if not update.message:
            return
        help_text = (
            "<b>Arena de Treinamento de Hesiod — Regras & Comandos</b>\n\n"
            "Eu sou <b>Loomis</b>, o treinador da vila de Hesiod! Aqui você aprende a enfrentar feras reais antes de sair para o mundo.\n\n"
            "<b>Comandos:</b>\n"
            "• <code>/start</code> - Apresenta a arena e as 5 cartas de heróis.\n"
            "• <code>/select &lt;1-5&gt;</code> - Escolhe sua carta para o combate.\n"
            "• <code>/reset</code> - Reinicia a sessão e permite novo recrutamento.\n"
            "• <code>/ajuda</code> - Exibe estas instruções.\n\n"
            "<b>Como Jogar:</b>\n"
            "• <b>Combate:</b> Declare sua ação e o resultado do seu d20 físico real (ex: <i>\"ataco com 19\"</i>).\n"
            "• <b>Conselho Tático:</b> Peça dicas ou pergunte sobre as fraquezas da fera na jaula (Ação Livre, não gasta turno).\n"
            "• <b>No Grupo:</b> Comandos funcionam sempre. Falas abertas de RPG são respondidas pela arena, mas conversas entre jogadores com reply ou menção @ são ignoradas pela IA."
        )
        try:
            await update.message.reply_text(help_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(help_text)

    async def _reset_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /reset para apagar a sessão inteira da arena/grupo e recomeçar a partida."""
        if not update.message or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user
        target_id = chat.id if chat else user.id
        logger.info(f"Comando /reset recebido de user_id={user.id} para session target_id={target_id}")

        if self.on_reset_callback:
            try:
                await self._invoke_callback(self.on_reset_callback, target_id)

                await update.message.reply_text(
                    "<b>Sessão de jogo reiniciada! A Jaula 1 foi trancada e a arena restaurada.</b>\n\n"
                    "<i>Escolham novamente seus recrutas para o treino:</i>",
                    parse_mode="HTML",
                )
                await self._start_handler(update, context)
            except Exception as e:
                logger.error(f"Erro ao processar /reset: {e}", exc_info=True)
                await update.message.reply_text("Ocorreu um erro ao tentar reiniciar a sessão do jogo.")
        else:
            await update.message.reply_text("Comando de reset não configurado.")

    async def _message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Recebe texto, passa para a main.py processar e devolve a resposta formatada em HTML."""
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
            bot_username = (context.bot.username or self.bot_username or "").lower()
            other_mentions = [m for m in mentions if m.lower() != bot_username]
            if other_mentions:
                return

        user_text = raw_text
        bot_username = (context.bot.username or self.bot_username or "").lower()
        if bot_username:
            user_text = re.sub(rf"@{re.escape(bot_username)}", "", user_text, flags=re.IGNORECASE).strip()

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

        formatted_reply = format_to_telegram_html(reply_text)
        try:
            await update.message.reply_text(formatted_reply, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Erro ao enviar resposta com parse_mode=HTML: {e}. Enviando como texto puro.")
            clean_text = re.sub(r"<[^>]+>", "", reply_text)
            await update.message.reply_text(clean_text)
