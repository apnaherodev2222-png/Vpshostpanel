"""
handlers/github.py
"Deploy from GitHub" flow: user sends a repo URL, we clone + deploy it.
"""

import os
import asyncio
import config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from core import github_manager, security, deploy, premium
from database.db import bots_db
from handlers.common import safe_edit, esc

AWAITING_REPO_URL = "awaiting_repo_url"


async def start_github(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data[AWAITING_REPO_URL] = True
    text = (
        "🐙 *Deploy from GitHub*\n\n"
        "Send me a public repo URL, e.g.\n`https://github.com/user/my-bot`"
        + config.CREDIT_FOOTER
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="home:go")]])
    await safe_edit(query, text, parse_mode="Markdown", reply_markup=kb)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(AWAITING_REPO_URL):
        return
    context.user_data[AWAITING_REPO_URL] = False

    user = update.effective_user
    repo_url = update.message.text.strip()

    if not github_manager.is_valid_github_url(repo_url):
        await update.message.reply_text(
            "❌ That doesn't look like a valid GitHub repo URL. Try again with /start."
        )
        return

    is_admin = user.id in config.ADMIN_IDS
    with bots_db() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM bots WHERE owner_id=?", (user.id,)).fetchone()["c"]
    ok, reason = security.enforce_user_bot_limit(count, is_admin, premium.is_premium(user.id))
    if not ok:
        await update.message.reply_text(f"❌ {reason}")
        return

    status_msg = await update.message.reply_text("⏳ Cloning repository...")

    bot_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")[:40]
    ok, result = await asyncio.to_thread(github_manager.clone_repo, repo_url, user.id, bot_name)
    if not ok:
        await status_msg.edit_text(f"❌ {result}")
        return

    project_path = result
    ok, reason = security.scan_project_tree(project_path)
    if not ok:
        await status_msg.edit_text(f"❌ {reason}")
        return

    await status_msg.edit_text("⏳ Deploying...")
    try:
        bot_row = await asyncio.to_thread(deploy.deploy_bot, user.id, bot_name, project_path, "github", repo_url)
        text = (
            f"✅ *{esc(bot_row['name'])}* deployed and running!\n"
            f"Runtime: `{bot_row['runtime']}`\n"
            f"Entrypoint: `{bot_row['entrypoint']}`"
            + config.CREDIT_FOOTER
        )
        await status_msg.edit_text(text, parse_mode="Markdown")
    except deploy.DeployError as e:
        await status_msg.edit_text(f"❌ Deploy failed: {e}")


def register(app):
    app.add_handler(CallbackQueryHandler(start_github, pattern="^github:start$"))
    # NOTE: handle_text is dispatched centrally from bot.py's text_router,
    # not registered directly here, since several flows share plain-text input.
