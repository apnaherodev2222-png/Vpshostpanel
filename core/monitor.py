"""
core/monitor.py
Background loop: periodically checks every "running" bot, and if it has
crashed, tries auto_fix once (if the owner allows it) before marking it
crashed and (optionally) notifying the owner.

v2 fixes:
  - No longer performs a restart/write while another bots.db write
    transaction is still open (that caused "database is locked" and
    silently broke auto-restart). Each write is now its own short
    transaction, and the restart happens outside any open transaction.
  - Honors the per-user `notify_on_crash` and `auto_fix_enabled`
    settings that the Settings menu was already writing but nothing read.
"""

import asyncio
import logging
import config
from core import docker_manager, process_manager, deploy, auto_fix
from database.db import bots_db, settings_db

logger = logging.getLogger("monitor")

CHECK_INTERVAL_SECONDS = 30


def _md_escape(text: str) -> str:
    """Escape the legacy-Markdown specials so a bot name can't break parsing."""
    out = str(text)
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


def _user_prefs(user_id: int) -> dict:
    """Per-user crash-notify / auto-fix toggles (defaults ON if unset)."""
    with settings_db() as conn:
        r = conn.execute(
            "SELECT notify_on_crash, auto_fix_enabled FROM user_settings WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if r is None:
        return {"notify_on_crash": 1, "auto_fix_enabled": 1}
    return {"notify_on_crash": r["notify_on_crash"], "auto_fix_enabled": r["auto_fix_enabled"]}


async def monitor_loop(bot_app):
    """Run forever as a background task on the PTB application."""
    while True:
        try:
            await _check_all_bots(bot_app)
        except Exception:
            logger.exception("monitor loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _check_all_bots(bot_app):
    with bots_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bots WHERE status='running'"
        ).fetchall()]

    for row in rows:
        alive = await asyncio.to_thread(_is_alive, row)
        if alive:
            continue

        prefs = _user_prefs(row["owner_id"])
        logger.info("bot_id=%s appears crashed", row["bot_id"])
        logs = await asyncio.to_thread(deploy.get_logs, row, 200)

        # Only attempt auto-fix if the owner has it enabled.
        fixed, message = False, "Bot stopped unexpectedly."
        if prefs["auto_fix_enabled"]:
            fixed, message = await asyncio.to_thread(
                auto_fix.attempt_fix, row["path"], row["runtime"], logs
            )

        restarts = row["restarts"] + 1
        restarted = False

        if fixed and restarts <= config.MAX_AUTO_RESTARTS:
            # Short write first (own transaction), THEN restart outside it —
            # restart_bot opens its own bots.db connection, so it must not run
            # while a write lock from this function is still held.
            with bots_db() as conn:
                conn.execute("UPDATE bots SET restarts=? WHERE bot_id=?", (restarts, row["bot_id"]))
            try:
                await asyncio.to_thread(deploy.restart_bot, row)
                restarted = True
            except Exception as e:
                logger.warning("auto-restart failed for bot_id=%s: %s", row["bot_id"], e)
                with bots_db() as conn:
                    conn.execute("UPDATE bots SET status='crashed' WHERE bot_id=?", (row["bot_id"],))
        else:
            with bots_db() as conn:
                conn.execute("UPDATE bots SET status='crashed' WHERE bot_id=?", (row["bot_id"],))

        if prefs["notify_on_crash"]:
            await _notify_owner(bot_app, row, restarted, message)


def _is_alive(row: dict) -> bool:
    if row.get("container_id"):
        try:
            stats = docker_manager.get_stats(row["container_id"])
            return stats["status"] == "running"
        except Exception:
            return False
    if row.get("pid"):
        return process_manager.is_running(row["pid"])
    return False


async def _notify_owner(bot_app, row: dict, restarted: bool, message: str):
    name = _md_escape(row["name"])
    text = f"⚠️ *{name}* stopped unexpectedly.\n\n"
    text += f"✅ Auto-fix applied & restarted: {message}" if restarted else f"❌ {message}"
    text += config.CREDIT_FOOTER
    try:
        await bot_app.bot.send_message(chat_id=row["owner_id"], text=text, parse_mode="Markdown")
    except Exception:
        logger.warning("could not notify owner %s", row["owner_id"])
