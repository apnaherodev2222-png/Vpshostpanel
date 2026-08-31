"""
core/auto_fix.py
Looks at a bot's recent logs for a handful of well-known, low-risk
failure patterns (missing pip/npm package, wrong entrypoint) and
attempts a single automated fix before giving up and notifying the user.
"""

import re
from core import dependency_manager

PY_MODULE_NOT_FOUND = re.compile(r"ModuleNotFoundError: No module named '([\w\-.]+)'")
NODE_MODULE_NOT_FOUND = re.compile(r"Cannot find module '([\w\-./@]+)'")


def diagnose(log_text: str) -> dict:
    """Returns {"issue": str|None, "detail": str|None}"""
    if not log_text:
        return {"issue": None, "detail": None}

    m = PY_MODULE_NOT_FOUND.search(log_text)
    if m:
        return {"issue": "missing_python_package", "detail": m.group(1)}

    m = NODE_MODULE_NOT_FOUND.search(log_text)
    if m:
        return {"issue": "missing_node_package", "detail": m.group(1)}

    if "SyntaxError" in log_text:
        return {"issue": "syntax_error", "detail": None}

    if "Permission denied" in log_text:
        return {"issue": "permission_denied", "detail": None}

    return {"issue": None, "detail": None}


def attempt_fix(project_path: str, runtime: str, log_text: str) -> tuple[bool, str]:
    """
    Attempts exactly one automated fix. Returns (fixed, message).
    Only handles the safe, well-understood case of a missing dependency —
    anything else is surfaced to the user instead of guessed at.
    """
    diagnosis = diagnose(log_text)
    issue = diagnosis["issue"]

    if issue == "missing_python_package":
        pkg = diagnosis["detail"]
        ok, out = dependency_manager.install_missing_python_package(pkg, project_path)
        if ok:
            return True, f"Installed missing package '{pkg}'. Restarting bot."
        return False, f"Tried to install '{pkg}' but it failed:\n{out}"

    if issue == "missing_node_package":
        pkg = diagnosis["detail"]
        ok, out = dependency_manager.install_node_deps(project_path)
        if ok:
            return True, f"Reinstalled node_modules to resolve missing '{pkg}'."
        return False, f"npm install failed:\n{out}"

    if issue == "syntax_error":
        return False, "A syntax error was detected in your code. Auto-fix can't safely rewrite code — please check the logs and fix it manually."

    if issue == "permission_denied":
        return False, "A permission error was detected. Check file paths and permissions in your code."

    return False, "No known auto-fixable issue was found in the recent logs."
