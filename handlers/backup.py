"""
handlers/backup.py
Zips a hosted bot's project folder and sends it back to the user.
"""

import os
import shutil
import asyncio
import config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from database.db import bots_db
from handlers.common import safe_edit, esc


async def backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    with bots_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT bot_id, name FROM bots WHERE owner_id=? ORDER BY name", (user_id,)
        ).fetchall()]

    if not rows:
        text = "You don't have any bots yet." + config.CREDIT_FOOTER
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="home:go")]])
        await safe_edit(query, text, reply_markup=kb, parse_mode="Markdown")
        return

    buttons = [[InlineKeyboardButton(r["name"], callback_data=f"backup:make:{r['bot_id']}")] for r in rows]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="home:go")])
    await safe_edit(query, "💾 *Backup* — choose a bot:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def make_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Creating backup...")
    bot_id = int(query.data.split(":")[2])
    with bots_db() as conn:
        row = conn.execute("SELECT * FROM bots WHERE bot_id=? AND owner_id=?", (bot_id, update.effective_user.id)).fetchone()
    if not row:
        await safe_edit(query, "Bot not found.")
        return
    row = dict(row)

    os.makedirs(config.BACKUPS_DIR, exist_ok=True)
    archive_base = os.path.join(config.BACKUPS_DIR, f"{row['name']}_{bot_id}")
    archive_path = await asyncio.to_thread(shutil.make_archive, archive_base, "zip", row["path"])

    with open(archive_path, "rb") as fh:
        await query.message.reply_document(
            document=fh,
            filename=os.path.basename(archive_path),
            caption=f"💾 Backup of *{esc(row['name'])}*" + config.CREDIT_FOOTER,
            parse_mode="Markdown",
        )


def register(app):
    app.add_handler(CallbackQueryHandler(backup_menu, pattern="^backup:menu$"))
    app.add_handler(CallbackQueryHandler(make_backup, pattern=r"^backup:make:\d+$"))
