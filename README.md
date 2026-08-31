# Telegram VPS Bot-Hosting Panel — Arranged Project

## Structure
```
core/       -> deploy.py, docker_manager.py, process_manager.py, runtime_detector.py,
               dependency_manager.py, github_manager.py, security.py, auto_fix.py,
               monitor.py, premium.py, host_stats.py
handlers/   -> home.py, upload.py, github.py, mybots.py, files.py, logs.py, env.py,
               dashboard.py, backup.py, settings.py, admin.py, common.py
database/   -> db.py, settings.db, users.db, bots.db
extra/      -> main.py (VPS Terminal / remote-shell bot), hostingmanager.py
               (a separate "Marco File Host" bot), bot_data.db (empty
               user_files/active_users tables, looks tied to hostingmanager.py)
               — these look like standalone scripts, not part of the
               core/+handlers/ panel, so I kept them out of the main package
               but included them in case you need them.
```

## config.py
The real `config.py` for this panel is now included at the project root. Its
`BOT_TOKEN` was hardcoded and had already been exposed in chat, so I replaced it
with a placeholder — get a fresh token from @BotFather and paste it in before
running (and revoke the old one, since it was posted in plaintext).

## Still missing
- **`requirements.txt`** — not provided yet. Based on the imports across the
  project you'll need at least: `python-telegram-bot`, `psutil`, `docker`,
  `GitPython`. Say the word and I'll generate a proper `requirements.txt`.

## `bot.py` (entry point)
This is your own, more thorough version of the entry point — config
validation, file+console logging, a `/cancel` command, a global error
handler, and clean monitor-task startup/shutdown. One bug fixed: the
`CommandHandler` for `/cancel` was being pulled in via a runtime
`__import__("telegram.ext", fromlist=[...])` hack instead of a normal
top-of-file import; that's now a plain `from telegram.ext import ...
CommandHandler ...` and `application.add_handler(CommandHandler("cancel",
cancel_command))`. Compiles clean (`python3 -m py_compile bot.py`).

Run it with `python bot.py` once `config.py` has a real token in it.

I also added empty `__init__.py` files to `core/`, `handlers/`, and
`database/` so the `from handlers.common import ...` / `from core import ...`
/ `from database.db import ...` imports resolve cleanly as packages.

## Excluded on purpose
- **Bomber tool**: `adit.py`, `config.py` (bomber version), `database.py` (bomber
  version), `zenox_bomber.db`, and `db_export.json` (a JSON export of that same
  bomber database — same users/bomb_logs/transactions/redeem_codes data) — as
  requested.
- **Third-party library source files** (not your project code — internals of
  packages you'd normally just `pip install`): `_updater.py`, `all.py`, `auth.py`,
  `bad_request_400.py`, `constants.py`, `http.py`, `lexer.py`, `logging.py`,
  `rpcerrorlist.py`, `secrets.py`, `util.py`, `webhookhandler.py`. Say the word if
  you actually want any of these bundled in too.
