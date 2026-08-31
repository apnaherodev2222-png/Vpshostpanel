"""
database/db.py
SQLite helpers for users.db, bots.db and settings.db.
The .db files themselves are created automatically on first run —
they are not checked into the repo.
"""

import sqlite3
import contextlib
import config


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def users_db():
    conn = _connect(config.USERS_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def bots_db():
    conn = _connect(config.BOTS_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def settings_db():
    conn = _connect(config.SETTINGS_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn, table: str, column: str, coltype: str):
    """Adds a column to an existing table if it isn't there yet.
    Safe to call every startup — needed so bots.db/users.db created by an
    older version of the bot pick up new columns without wiping data."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_databases():
    """Create all tables if they don't already exist. Call once on startup."""
    import os
    os.makedirs(config.DATABASE_DIR, exist_ok=True)
    os.makedirs(config.UPLOADS_DIR, exist_ok=True)
    os.makedirs(config.CONTAINERS_DIR, exist_ok=True)
    os.makedirs(config.BACKUPS_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    os.makedirs(config.TEMP_DIR, exist_ok=True)

    with users_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id      INTEGER PRIMARY KEY,
                username     TEXT,
                first_seen   TEXT DEFAULT CURRENT_TIMESTAMP,
                is_admin     INTEGER DEFAULT 0,
                is_banned    INTEGER DEFAULT 0,
                is_premium   INTEGER DEFAULT 0,
                premium_until TEXT
            )
        """)
        _add_column_if_missing(conn, "users", "is_premium", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "users", "premium_until", "TEXT")

    with bots_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                bot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id     INTEGER NOT NULL,
                name         TEXT NOT NULL,
                source       TEXT DEFAULT 'upload',   -- upload | github
                repo_url     TEXT,
                runtime      TEXT,                    -- python | node
                entrypoint   TEXT,
                path         TEXT NOT NULL,
                container_id TEXT,
                pid          INTEGER,
                status       TEXT DEFAULT 'stopped',   -- running | stopped | crashed
                restarts     INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, name)
            )
        """)

    with settings_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_env (
                bot_id  INTEGER NOT NULL,
                key     TEXT NOT NULL,
                value   TEXT,
                PRIMARY KEY (bot_id, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id  INTEGER PRIMARY KEY,
                notify_on_crash INTEGER DEFAULT 1,
                auto_fix_enabled INTEGER DEFAULT 1
            )
        """)
