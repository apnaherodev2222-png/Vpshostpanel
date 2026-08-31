"""
handlers/admin.py
Admin-only commands:
  /vpsstatus              — whole-VPS CPU/RAM/disk/uptime
  /addprem <user_id> [days] — grant premium (omit days = permanent)
  /removeprem <user_id>     — revoke premium
  /premlist                 — list current premium users
"""

import config
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from core import host_stats, premium
from handlers.common import esc

BOTS_DB_COUNT_TIP = "Tip: use /premlist to see who currently has premium."


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def vps_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    stats = host_stats.get_host_stats()
    load_line = ""
    if stats["load_avg"]:
        l1, l5, l15 = stats["load_avg"]
        load_line = f"Load avg: {l1:.2f}, {l5:.2f}, {l15:.2f}\n"

    text = (
        "🖥 *VPS Status*\n\n"
        f"CPU: {stats['cpu_percent']}% ({stats['cpu_cores']} cores)\n"
        f"{load_line}"
        f"RAM: {stats['mem_used_mb']}MB / {stats['mem_total_mb']}MB ({stats['mem_percent']}%)\n"
        f"Disk: {stats['disk_used_gb']}GB / {stats['disk_total_gb']}GB ({stats['disk_percent']}%)\n"
        f"Uptime: {host_stats.format_uptime(stats['uptime_seconds'])}"
        + config.CREDIT_FOOTER
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/addprem <user_id> [days]`\n"
            "Example: `/addprem 123456789 30` (30-day premium)\n"
            "Omit days for permanent premium: `/addprem 123456789`",
            parse_mode="Markdown",
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id must be a number.")
        return

    days = None
    if len(context.args) > 1:
        try:
            days = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ days must be a number.")
            return

    premium.ensure_user_row(target_id)
    until = premium.grant_premium(target_id, days)

    if until:
        await update.message.reply_text(
            f"✅ Granted premium to `{target_id}` until `{until}` (UTC)." + config.CREDIT_FOOTER,
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"✅ Granted permanent premium to `{target_id}`." + config.CREDIT_FOOTER,
            parse_mode="Markdown",
        )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 You've been upgraded to *Premium*!\n"
                f"You can now host up to {config.MAX_BOTS_PER_PREMIUM_USER} bots."
                + config.CREDIT_FOOTER
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass  # user may have never started the bot in DM


async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/removeprem <user_id>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id must be a number.")
        return

    premium.revoke_premium(target_id)
    await update.message.reply_text(f"✅ Revoked premium from `{target_id}`." + config.CREDIT_FOOTER, parse_mode="Markdown")


async def premium_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    users = premium.list_premium_users()
    if not users:
        await update.message.reply_text("No premium users yet." + config.CREDIT_FOOTER, parse_mode="Markdown")
        return

    lines = ["👑 *Premium users*\n"]
    for u in users:
        uname = f"@{esc(u['username'])}" if u["username"] else "(no username)"
        expiry = u["premium_until"] or "never"
        lines.append(f"`{u['user_id']}` {uname} — expires: `{expiry}`")

    await update.message.reply_text("\n".join(lines) + config.CREDIT_FOOTER, parse_mode="Markdown")


def register(app):
    app.add_handler(CommandHandler("vpsstatus", vps_status))
    app.add_handler(CommandHandler("addprem", add_premium))
    app.add_handler(CommandHandler("removeprem", remove_premium))
    app.add_handler(CommandHandler("premlist", premium_list))
