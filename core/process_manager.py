"""
core/process_manager.py
Fallback host-process based runner, used automatically when Docker is
unavailable (config.USE_DOCKER = False, or the daemon can't be reached).
Each hosted bot runs as a plain subprocess with output redirected to a
log file under logs/<bot_id>.log.
"""

import os
import shutil
import subprocess
import signal
import psutil
import config

RUN_COMMANDS = {
    "python": lambda entry: ["python3", entry],
    "node": lambda entry: ["node", entry],
}

REQUIRED_BINARY = {"python": "python3", "node": "node"}


def start_process(project_path: str, runtime: str, entrypoint: str, bot_id: int, env_vars: dict | None = None) -> int:
    if runtime not in RUN_COMMANDS:
        raise ValueError(f"Unsupported runtime: {runtime}")

    binary = REQUIRED_BINARY[runtime]
    if shutil.which(binary) is None:
        raise RuntimeError(
            f"'{binary}' isn't installed on this server. Install it, or set USE_DOCKER = True "
            f"in config.py so this runtime runs inside a container instead."
        )

    log_path = os.path.join(config.LOGS_DIR, f"{bot_id}.log")
    env = os.environ.copy()
    env.update(env_vars or {})

    cmd = RUN_COMMANDS[runtime](entrypoint)

    with open(log_path, "ab") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=project_path,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # own process group -> clean kill later
        )
    return proc.pid


def stop_process(pid: int):
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            psutil.Process(pid).terminate()
        except psutil.NoSuchProcess:
            pass


def is_running(pid: int) -> bool:
    return psutil.pid_exists(pid)


def get_stats(pid: int) -> dict:
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            return {
                "status": p.status(),
                "cpu_percent": p.cpu_percent(interval=0.2),
                "mem_usage_mb": round(p.memory_info().rss / 1024 / 1024, 1),
            }
    except psutil.NoSuchProcess:
        return {"status": "stopped", "cpu_percent": 0, "mem_usage_mb": 0}


def tail_log(bot_id: int, lines: int = 100) -> str:
    log_path = os.path.join(config.LOGS_DIR, f"{bot_id}.log")
    if not os.path.exists(log_path):
        return "(no logs yet)"
    with open(log_path, "rb") as f:
        content = f.read().decode(errors="replace").splitlines()
    return "\n".join(content[-lines:]) or "(no logs yet)"
