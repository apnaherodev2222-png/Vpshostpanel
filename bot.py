"""
bot.py
Main entrypoint for the Telegram VPS Bot-Hosting Panel.

Responsibilities:
- Validate configuration
- Initialize databases/runtime directories
- Register every handler module
- Route shared plain-text input to GitHub / Env flows
- Provide /cancel for pending input states
- Run the background bot monitor
- Install a global error handler
- Start Telegram polling cleanly

Run:
    python3 bot.py

Requirements:
    python-telegram-bot >= 20
    psutil
    docker
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

import config
from database.db import init_databases

from telegram import Update
from telegram.error import Conflict, InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from handlers import (
    account,
    admin,
    backup,
    dashboard,
    env,
    files,
    github,
    home,
    logs,
    mybots,
    settings,
    upload,
)
from core import monitor


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging() -> None:
    """Configure console + file logging without exposing secrets."""
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers when this module is imported/reloaded.
    if root.handlers:
        return

    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        file_handler = logging.FileHandler(
            os.path.join(config.LOGS_DIR, "panel.log"),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # Console logging is still sufficient if the log file cannot be opened.
        logging.getLogger(__name__).warning(
            "Could not open panel.log; continuing with console logging."
        )


logger = logging.getLogger("hosting-panel")


# ---------------------------------------------------------------------------
# Configuration / startup checks
# ---------------------------------------------------------------------------

def validate_config() -> None:
    """Fail early on configuration mistakes."""
    token = str(getattr(config, "BOT_TOKEN", "") or "").strip()

    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN is not configured. Put the current BotFather token "
            "in config.py before starting the panel."
        )

    owner_id = getattr(config, "OWNER_ID", None)
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise RuntimeError("OWNER_ID must be a valid Telegram numeric user ID.")

    admin_ids = getattr(config, "ADMIN_IDS", None)
    if not isinstance(admin_ids, (list, tuple, set)):
        raise RuntimeError("ADMIN_IDS must be a list/tuple/set of Telegram user IDs.")

    if owner_id not in admin_ids:
        logger.warning("OWNER_ID is not present in ADMIN_IDS.")

    # This panel is intended to isolate hosted applications.
    # Never silently downgrade to host-process execution when Docker is enabled.
    if getattr(config, "USE_DOCKER", True) is not True:
        logger.warning(
            "USE_DOCKER is disabled. Hosted projects may execute directly "
            "on the VPS host; this is not recommended for multi-user hosting."
        )


def prepare_runtime() -> None:
    """Create required directories and SQLite tables."""
    init_databases()

    required_dirs = (
        config.UPLOADS_DIR,
        config.CONTAINERS_DIR,
        config.BACKUPS_DIR,
        config.LOGS_DIR,
        config.TEMP_DIR,
        config.DATABASE_DIR,
    )

    for directory in required_dirs:
        os.makedirs(directory, exist_ok=True)


# ---------------------------------------------------------------------------
# Shared text router
# ---------------------------------------------------------------------------

# These keys are defined by the existing handlers. They are deliberately
# centralized here because both flows need plain text and should not register
# competing catch-all MessageHandlers.
PENDING_KEYS = (
    github.AWAITING_REPO_URL,
    env.AWAITING_ENV_INPUT,
    upload.AWAITING_UPLOAD,
)


async def text_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Route non-command text to the currently active flow.

    Priority:
        1. Environment variable input
        2. GitHub repository URL

    Uploads are documents, so handlers/upload.py handles them separately.
    """
    if not update.message or not update.message.text:
        return

    # A user can normally have only one active text flow. If stale state ever
    # exists, ENV is handled first because it is the more specific operation.
    if context.user_data.get(env.AWAITING_ENV_INPUT):
        await env.handle_text(update, context)
        return

    if context.user_data.get(github.AWAITING_REPO_URL):
        await github.handle_text(update, context)
        return


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Cancel any pending upload/text flow for the current user."""
    for key in PENDING_KEYS:
        context.user_data.pop(key, None)

    context.user_data.pop(env.AWAITING_ENV_BOT_ID, None)

    if update.message:
        await update.message.reply_text(
            "❌ Current operation cancelled.\n\nUse /start to open the panel."
        )


# ---------------------------------------------------------------------------
# Monitor lifecycle
# ---------------------------------------------------------------------------

_MONITOR_TASK: Optional[asyncio.Task] = None


async def post_init(application: Application) -> None:
    """
    PTB lifecycle hook.

    Called after the Application is initialized and before polling starts.
    The monitor is started here so it shares PTB's running event loop.
    """
    global _MONITOR_TASK

    # Verify Telegram credentials/connectivity early and log the bot identity.
    me = await application.bot.get_me()
    logger.info("Telegram bot connected: @%s (id=%s)", me.username, me.id)

    if _MONITOR_TASK is None or _MONITOR_TASK.done():
        _MONITOR_TASK = application.create_task(
            monitor.monitor_loop(application),
            name="hosting-panel-monitor",
        )
        logger.info("Background bot monitor started.")


async def post_shutdown(application: Application) -> None:
    """Cancel the background monitor before the application fully shuts down."""
    global _MONITOR_TASK

    task = _MONITOR_TASK
    _MONITOR_TASK = None

    if task is None:
        return

    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Background bot monitor stopped.")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Global PTB error handler.

    Full exception details go to server logs; Telegram users receive only a
    short safe message when an update-specific message is available.
    """
    error = context.error

    if isinstance(error, Conflict):
        logger.error(
            "Telegram polling conflict: another process is already using "
            "this bot token. Stop the other instance."
        )
    elif isinstance(error, InvalidToken):
        logger.error("Telegram rejected BOT_TOKEN. Check config.py.")
    elif isinstance(error, NetworkError):
        logger.warning("Telegram network error: %s", error)
    else:
        logger.exception("Unhandled Telegram update error", exc_info=error)

    # Best-effort user-facing response. Never leak exception text because it
    # can contain filesystem paths, tokens, command output, or other details.
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong while processing that request. "
                "Please try again."
            )
        except TelegramError:
            pass


# ---------------------------------------------------------------------------
# Application construction
# ---------------------------------------------------------------------------

def register_handlers(application: Application) -> None:
    """Register every panel handler exactly once."""
    # Home owns /start and /help + home callback.
    home.register(application)

    # Feature modules.
    upload.register(application)
    github.register(application)
    mybots.register(application)
    files.register(application)
    logs.register(application)
    env.register(application)
    dashboard.register(application)
    backup.register(application)
    settings.register(application)
    account.register(application)

    # Admin commands.
    admin.register(application)

    # Shared plain-text router. It must be after feature callback/document
    # registrations, but it only consumes TEXT messages when a flow is active.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    application.add_handler(CommandHandler("cancel", cancel_command))


def build_application() -> Application:
    """Build and configure the PTB Application."""
    validate_config()
    prepare_runtime()

    application = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    register_handlers(application)
    application.add_error_handler(error_handler)

    return application


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    configure_logging()

    try:
        application = build_application()

        logger.info(
            "Starting Hosting Panel v%s | Docker=%s",
            getattr(config, "VERSION", "?"),
            getattr(config, "USE_DOCKER", True),
        )

        # drop_pending_updates avoids processing an old backlog after a VPS
        # restart. This is appropriate for a hosting control panel where stale
        # button/text actions should not be replayed.
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
        )

    except InvalidToken:
        logger.error("Invalid BOT_TOKEN. Get a fresh token from @BotFather.")
        raise SystemExit(2)
    except Conflict:
        logger.error(
            "Bot is already running somewhere else. "
            "Only one polling process may use this token."
        )
        raise SystemExit(3)
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    except Exception:
        logger.exception("Fatal startup/runtime error.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
