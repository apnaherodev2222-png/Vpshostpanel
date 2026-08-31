"""
handlers/common.py
Shared helper for editing the bot's menu message.

/start sends a VIDEO with a caption, so every subsequent inline button
press is editing that same message. Telegram's API treats caption
edits and text edits as different calls — calling edit_message_text()
on a media message raises:
    telegram.error.BadRequest: There is no text in the message to edit

safe_edit() detects which kind of message we're dealing with and calls
the right method, falling back to deleting + resending if neither edit
is possible (e.g. the message is too old, or was a document).
"""

from telegram.error import BadRequest
import re


def esc(value) -> str:
    """
    Escape characters that have special meaning in Telegram's legacy
    Markdown parser (*, _, `, [) so that user-supplied text (usernames,
    bot names, filenames, repo URLs) can't break message parsing or
    accidentally inject formatting.
    """
    return re.sub(r"([_*`\[])", r"\\\1", str(value))


async def safe_edit(query, text, reply_markup=None, parse_mode="Markdown"):
    msg = query.message
    is_media = bool(msg.caption is not None or msg.photo or msg.video or msg.document or msg.animation)

    try:
        if is_media:
            await query.edit_message_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return
    except BadRequest as e:
        # "Message is not modified" just means nothing changed — safe to ignore.
        if "not modified" in str(e).lower():
            return
        # Otherwise fall through to the fallbacks below.

    # First fallback: retry the same edit without Markdown parsing, in case
    # the text contained an unescaped special character that broke parsing.
    try:
        if is_media:
            await query.edit_message_caption(caption=text, parse_mode=None, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        return
    except BadRequest:
        pass

    # Last resort: delete and send a fresh plain-text message.
    try:
        await msg.delete()
    except Exception:
        pass
    try:
        await msg.chat.send_message(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest:
        await msg.chat.send_message(text, parse_mode=None, reply_markup=reply_markup)
