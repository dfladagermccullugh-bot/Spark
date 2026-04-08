"""Telegram delivery adapter using python-telegram-bot."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from spark.delivery.base import DeliveryAdapter

logger = logging.getLogger(__name__)


class TelegramAdapter(DeliveryAdapter):
    """Send and receive messages via Telegram bot."""

    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._app: Application | None = None
        self._on_message: Callable[[str], str | None] | None = None

    async def send(self, message: str) -> bool:
        """Send a message to the configured chat."""
        try:
            bot = Bot(token=self._bot_token)
            await bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode=None,  # Plain text, like a real person
            )
            logger.info(f"Sent Telegram message: {message[:60]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def start_listening(self, on_message: Callable[[str], str | None]) -> None:
        """Start the Telegram bot to listen for user replies."""
        self._on_message = on_message

        self._app = (
            Application.builder()
            .token(self._bot_token)
            .build()
        )

        # Command handlers
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(CommandHandler("pause", self._handle_pause))
        self._app.add_handler(CommandHandler("resume", self._handle_resume))
        self._app.add_handler(CommandHandler("projects", self._handle_projects))

        # Catch-all message handler
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        logger.info("Starting Telegram bot listener...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        if not update.message or str(update.message.chat_id) != self._chat_id:
            return  # Ignore messages from other chats

        text = update.message.text
        logger.info(f"Received Telegram message: {text[:60]}...")

        if self._on_message:
            reply = self._on_message(text)
            if reply:
                await update.message.reply_text(reply)

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if str(update.message.chat_id) != self._chat_id:
            return
        # Delegate to the on_message handler with a special command
        if self._on_message:
            reply = self._on_message("/status")
            if reply:
                await update.message.reply_text(reply)

    async def _handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pause command."""
        if str(update.message.chat_id) != self._chat_id:
            return
        if self._on_message:
            reply = self._on_message("/pause")
            if reply:
                await update.message.reply_text(reply)

    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resume command."""
        if str(update.message.chat_id) != self._chat_id:
            return
        if self._on_message:
            reply = self._on_message("/resume")
            if reply:
                await update.message.reply_text(reply)

    async def _handle_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /projects command."""
        if str(update.message.chat_id) != self._chat_id:
            return
        if self._on_message:
            reply = self._on_message("/projects")
            if reply:
                await update.message.reply_text(reply)
