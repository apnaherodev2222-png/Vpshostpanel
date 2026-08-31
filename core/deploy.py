"""
core/deploy.py
Orchestrates: detect runtime -> security scan -> build/run (Docker or
plain process fallback) -> persist bot record in bots.db.
"""

import os
import uuid
import config
from core import runtime_detector, security, docker_manager, process_manager, dependency_manager
from database.db import bots_db


class DeployError(Exception):
    pass


def _docker_ready() -> bool:
    return config.USE_DOCKER and docker_manager.is_docker_available()


def deploy_bot(owner_id: int, bot_name: str, project_path: str, source: str = "upload", repo_url: str | None = None) -> dict:
    """
    Deploys (builds + starts) a bot project that already lives on disk
    at `project_path`. Returns the bots.db row as a dict.
    """
    ok, reason = security.scan_project_tree(project_path)
    if not ok:
        raise DeployError(reason)

    info = runtime_detector.detect_runtime(project_path)
    runtime = info["runtime"]
    entrypoint = info["entrypoint"]

    if runtime is None or entrypoint is None:
        raise DeployError(
            "Couldn't detect a runnable entrypoint. Make sure your project has a "
            "main.py/bot.py (Python) or package.json + index.js (Node)."
        )

    # Persist a placeholder bot row first so we have a bot_id
    with bots_db() as conn:
        cur = conn.execute(
            """INSERT INTO bots (owner_id, name, source, repo_url, runtime, entrypoint, path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'deploying')""",
            (owner_id, bot_name, source, repo_url, runtime, entrypoint, project_path),
        )
        bot_id = cur.lastrowid

    try:
        if _docker_ready():
            _deploy_with_docker(bot_id, project_path, runtime, entrypoint, owner_id, bot_name)
        else:
            _deploy_with_process(bot_id, project_path, runtime, entrypoint)
    except Exception as e:
        with bots_db() as conn:
            conn.execute("UPDATE bots SET status='crashed' WHERE bot_id=?", (bot_id,))
        raise DeployError(str(e))

    with bots_db() as conn:
        row = conn.execute("SELECT * FROM bots WHERE bot_id=?", (bot_id,)).fetchone()
        return dict(row)


def _deploy_with_docker(bot_id, project_path, runtime, entrypoint, owner_id, bot_name):
    docker_manager.write_dockerfile(project_path, runtime, entrypoint)
    image_tag = f"hostedbot-{bot_id}-{uuid.uuid4().hex[:6]}".lower()
    container_name = f"hostedbot-{owner_id}-{bot_name}".lower().replace(" ", "-")

    docker_manager.build_image(project_path, image_tag)
    env_vars = _load_env_vars(bot_id)
    container_id = docker_manager.run_container(image_tag, container_name, env_vars)

    with bots_db() as conn:
        conn.execute(
            "UPDATE bots SET container_id=?, status='running' WHERE bot_id=?",
            (container_id, bot_id),
        )


def _deploy_with_process(bot_id, project_path, runtime, entrypoint):
    if runtime == "python":
        ok, out = dependency_manager.install_python_deps(project_path)
    else:
        ok, out = dependency_manager.install_node_deps(project_path)
    if not ok:
        raise DeployError(f"Dependency install failed:\n{out}")

    env_vars = _load_env_vars(bot_id)
    pid = process_manager.start_process(project_path, runtime, entrypoint, bot_id, env_vars)

    with bots_db() as conn:
        conn.execute("UPDATE bots SET pid=?, status='running' WHERE bot_id=?", (pid, bot_id))


def _load_env_vars(bot_id: int) -> dict:
    from database.db import settings_db
    with settings_db() as conn:
        rows = conn.execute("SELECT key, value FROM bot_env WHERE bot_id=?", (bot_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def stop_bot(bot_row: dict):
    if bot_row.get("container_id"):
        docker_manager.stop_container(bot_row["container_id"])
    elif bot_row.get("pid"):
        process_manager.stop_process(bot_row["pid"])
    with bots_db() as conn:
        conn.execute("UPDATE bots SET status='stopped' WHERE bot_id=?", (bot_row["bot_id"],))


def restart_bot(bot_row: dict):
    if bot_row.get("container_id"):
        docker_manager.restart_container(bot_row["container_id"])
        with bots_db() as conn:
            conn.execute("UPDATE bots SET status='running' WHERE bot_id=?", (bot_row["bot_id"],))
    else:
        # process fallback: stop then redeploy
        if bot_row.get("pid"):
            process_manager.stop_process(bot_row["pid"])
        _deploy_with_process(bot_row["bot_id"], bot_row["path"], bot_row["runtime"], bot_row["entrypoint"])


def delete_bot(bot_row: dict):
    import shutil
    stop_bot(bot_row)
    if bot_row.get("container_id"):
        docker_manager.remove_container(bot_row["container_id"])
    shutil.rmtree(bot_row["path"], ignore_errors=True)
    with bots_db() as conn:
        conn.execute("DELETE FROM bots WHERE bot_id=?", (bot_row["bot_id"],))


def get_logs(bot_row: dict, tail: int = None) -> str:
    tail = tail or config.LOG_TAIL_LINES
    if bot_row.get("container_id"):
        try:
            return docker_manager.get_logs(bot_row["container_id"], tail)
        except Exception as e:
            return f"(couldn't fetch container logs: {e})"
    return process_manager.tail_log(bot_row["bot_id"], tail)
