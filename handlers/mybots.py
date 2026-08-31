"""
handlers/mybots.py
Lists a user's hosted bots and lets them start/stop/restart/delete each.
"""

import asyncio
import config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from core import deploy
from database.db import bots_db
from handlers.common import safe_edit, esc

STATUS_EMOJI = {"running": "🟢", "stopped": "🔴", "crashed": "💥", "deploying": "🟡"}


def _get_bot_row(bot_id: int) -> dict | None:
    with bots_db() as conn:
        row = conn.execute("SELECT * FROM bots WHERE bot_id=?", (bot_id,)).fetchone()
        return dict(row) if row else None


async def list_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    with bots_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bots WHERE owner_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()]

    if not rows:
        text = "You haven't deployed any bots yet." + config.CREDIT_FOOTER
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="home:go")]])
        await safe_edit(query, text, reply_markup=kb, parse_mode="Markdown")
        return

    buttons = []
    for r in rows:
        emoji = STATUS_EMOJI.get(r["status"], "⚪")
        buttons.append([InlineKeyboardButton(f"{emoji} {r['name']}", callback_data=f"mybots:view:{r['bot_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="home:go")])

    text = "🤖 *Your hosted bots*\nTap one to manage it." + config.CREDIT_FOOTER
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def view_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[2])
    row = _get_bot_row(bot_id)
    if not row or row["owner_id"] != update.effective_user.id:
        await safe_edit(query, "Bot not found.")
        return

    emoji = STATUS_EMOJI.get(row["status"], "⚪")
    text = (
        f"{emoji} *{esc(row['name'])}*\n"
        f"Runtime: `{row['runtime']}`\n"
        f"Status: `{row['status']}`\n"
        f"Source: `{row['source']}`"
        + config.CREDIT_FOOTER
    )
    buttons = [
        [InlineKeyboardButton("▶️ Start/Restart", callback_data=f"mybots:restart:{bot_id}", style="success"),
         InlineKeyboardButton("⏹ Stop", callback_data=f"mybots:stop:{bot_id}", style="danger")],
        [InlineKeyboardButton("📜 Logs", callback_data=f"logs:view:{bot_id}", style="primary"),
         InlineKeyboardButton("📊 Stats", callback_data=f"dashboard:bot:{bot_id}", style="primary")],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"mybots:delete_confirm:{bot_id}", style="danger")],
        [InlineKeyboardButton("⬅️ Back", callback_data="mybots:list")],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Stopping...")
    bot_id = int(query.data.split(":")[2])
    row = _get_bot_row(bot_id)
    if row and row["owner_id"] == update.effective_user.id:
        await asyncio.to_thread(deploy.stop_bot, row)
    await view_bot(update, context)


async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Restarting...")
    bot_id = int(query.data.split(":")[2])
    row = _get_bot_row(bot_id)
    if row and row["owner_id"] == update.effective_user.id:
        try:
            await asyncio.to_thread(deploy.restart_bot, row)
        except Exception as e:
            await query.message.reply_text(f"❌ Restart failed: {e}")
    await view_bot(update, context)


async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[2])
    text = "⚠️ This will permanently delete this bot and its files. Are you sure?"
    buttons = [
        [InlineKeyboardButton("✅ Yes, delete", callback_data=f"mybots:delete:{bot_id}", style="danger"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"mybots:view:{bot_id}", style="success")],
    ]
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(buttons))


async def delete_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Deleting...")
    bot_id = int(query.data.split(":")[2])
    row = _get_bot_row(bot_id)
    if row and row["owner_id"] == update.effective_user.id:
        await asyncio.to_thread(deploy.delete_bot, row)
    await list_bots(update, context)


def register(app):
    app.add_handler(CallbackQueryHandler(list_bots, pattern="^mybots:list$"))
    app.add_handler(CallbackQueryHandler(view_bot, pattern=r"^mybots:view:\d+$"))
    app.add_handler(CallbackQueryHandler(stop_bot, pattern=r"^mybots:stop:\d+$"))
    app.add_handler(CallbackQueryHandler(restart_bot, pattern=r"^mybots:restart:\d+$"))
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern=r"^mybots:delete_confirm:\d+$"))
    app.add_handler(CallbackQueryHandler(delete_bot, pattern=r"^mybots:delete:\d+$"))
