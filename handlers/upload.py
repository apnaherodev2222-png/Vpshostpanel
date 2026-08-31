"""
handlers/upload.py
"Upload Bot" flow: user sends a .zip/.py/.js file, we extract it,
detect the runtime, and deploy it.
"""

import os
import shutil
import zipfile
import asyncio
import config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from core import security, deploy, premium
from database.db import bots_db
from handlers.common import safe_edit, esc

AWAITING_UPLOAD = "awaiting_upload"


async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data[AWAITING_UPLOAD] = True
    text = (
        "⬆️ *Upload your bot*\n\n"
        "Send me a `.zip` of your project, or a single `.py`/`.js` file.\n"
        "Make sure it includes `requirements.txt` (Python) or `package.json` (Node) "
        "if it needs extra packages."
        + config.CREDIT_FOOTER
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="home:go")]])
    await safe_edit(query, text, parse_mode="Markdown", reply_markup=kb)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(AWAITING_UPLOAD):
        return  # not in upload flow, ignore

    context.user_data[AWAITING_UPLOAD] = False
    user = update.effective_user
    doc = update.message.document

    ok, reason = security.check_extension(doc.file_name)
    if not ok:
        await update.message.reply_text(f"❌ {reason}" + config.CREDIT_FOOTER, parse_mode="Markdown")
        return

    if doc.file_size and doc.file_size > config.MAX_UPLOAD_MB * 1024 * 1024:
        await update.message.reply_text(
            f"❌ File too large (limit {config.MAX_UPLOAD_MB}MB)." + config.CREDIT_FOOTER
        )
        return

    status_msg = await update.message.reply_text("⏳ Downloading and deploying...")

    user_dir = os.path.join(config.UPLOADS_DIR, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    bot_name = os.path.splitext(doc.file_name)[0].replace(" ", "_")[:40]
    project_path = os.path.join(user_dir, bot_name)
    if os.path.exists(project_path):
        shutil.rmtree(project_path)
    os.makedirs(project_path, exist_ok=True)

    tg_file = await doc.get_file()
    local_path = os.path.join(config.TEMP_DIR, doc.file_name)
    await tg_file.download_to_drive(local_path)

    ok, reason = security.check_upload_size(local_path)
    if not ok:
        os.remove(local_path)
        shutil.rmtree(project_path, ignore_errors=True)
        await status_msg.edit_text(f"❌ {reason}")
        return

    try:
        if doc.file_name.lower().endswith(".zip"):
            with zipfile.ZipFile(local_path) as zf:
                zf.extractall(project_path)
            # If the zip contained a single top-level folder, flatten it
            entries = os.listdir(project_path)
            if len(entries) == 1 and os.path.isdir(os.path.join(project_path, entries[0])):
                nested = os.path.join(project_path, entries[0])
                for item in os.listdir(nested):
                    shutil.move(os.path.join(nested, item), project_path)
                os.rmdir(nested)
        else:
            shutil.copy(local_path, os.path.join(project_path, doc.file_name))
    finally:
        os.remove(local_path)

    is_admin = user.id in config.ADMIN_IDS
    with bots_db() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM bots WHERE owner_id=?", (user.id,)).fetchone()["c"]
    ok, reason = security.enforce_user_bot_limit(count, is_admin, premium.is_premium(user.id))
    if not ok:
        shutil.rmtree(project_path, ignore_errors=True)
        await status_msg.edit_text(f"❌ {reason}")
        return

    ok, reason = security.scan_project_tree(project_path)
    if not ok:
        shutil.rmtree(project_path, ignore_errors=True)
        await status_msg.edit_text(f"❌ {reason}")
        return

    try:
        bot_row = await asyncio.to_thread(deploy.deploy_bot, user.id, bot_name, project_path, "upload")
        text = (
            f"✅ *{esc(bot_row['name'])}* deployed and running!\n"
            f"Runtime: `{bot_row['runtime']}`\n"
            f"Entrypoint: `{bot_row['entrypoint']}`"
            + config.CREDIT_FOOTER
        )
        await status_msg.edit_text(text, parse_mode="Markdown")
    except deploy.DeployError as e:
        shutil.rmtree(project_path, ignore_errors=True)
        await status_msg.edit_text(f"❌ Deploy failed: {e}")


def register(app):
    app.add_handler(CallbackQueryHandler(start_upload, pattern="^upload:start$"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
