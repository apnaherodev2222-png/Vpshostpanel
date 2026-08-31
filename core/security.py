"""
core/security.py
Basic safety checks applied to uploaded/cloned projects before hosting.
This is intentionally conservative: it blocks a small set of obviously
dangerous patterns and enforces size/resource limits. It is NOT a
substitute for real sandboxing — Docker (or another isolation layer)
is what actually protects the host in this project.
"""

import os
import config

MAX_UPLOAD_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024

# File extensions that should never be accepted from an upload
BLOCKED_EXTENSIONS = {".exe", ".dll", ".so", ".bat", ".msi", ".sh.exe"}


def check_upload_size(file_path: str) -> tuple[bool, str]:
    size = os.path.getsize(file_path)
    if size > MAX_UPLOAD_BYTES:
        return False, f"File is {size / 1024 / 1024:.1f}MB, limit is {config.MAX_UPLOAD_MB}MB."
    return True, ""


def check_extension(filename: str) -> tuple[bool, str]:
    ext = os.path.splitext(filename)[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        return False, f"File type '{ext}' is not allowed."
    return True, ""


def scan_project_tree(project_path: str) -> tuple[bool, str]:
    """Reject archives that contain blocked file types or that are absurdly large in total."""
    total_size = 0
    for root, _, files in os.walk(project_path):
        for name in files:
            fp = os.path.join(root, name)
            ok, reason = check_extension(name)
            if not ok:
                return False, reason
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                continue
    if total_size > MAX_UPLOAD_BYTES * 3:
        return False, "Extracted project is too large."
    return True, ""


def enforce_user_bot_limit(current_count: int, is_admin: bool, is_premium: bool = False) -> tuple[bool, str]:
    if is_admin:
        return True, ""
    limit = config.MAX_BOTS_PER_PREMIUM_USER if is_premium else config.MAX_BOTS_PER_USER
    if current_count >= limit:
        tier = "premium" if is_premium else "free"
        return False, f"You've reached your {tier} limit of {limit} hosted bots."
    return True, ""
