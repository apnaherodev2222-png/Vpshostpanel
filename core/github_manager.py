"""
core/github_manager.py
Clones a public (or token-authenticated) GitHub repo into the uploads
directory so it can go through the same deploy pipeline as an upload.
"""

import os
import re
import shutil
import config

try:
    import git
    from git.exc import GitCommandError
except ImportError:
    git = None
    GitCommandError = Exception

GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(\.git)?/?$")


def is_valid_github_url(url: str) -> bool:
    return bool(GITHUB_URL_RE.match(url.strip()))


def clone_repo(repo_url: str, user_id: int, bot_name: str) -> tuple[bool, str]:
    """
    Clones repo_url into uploads/<user_id>/<bot_name>.
    Returns (success, path_or_error_message).
    """
    if git is None:
        return False, "GitPython isn't installed on the server."

    if not is_valid_github_url(repo_url):
        return False, "That doesn't look like a valid GitHub repo URL."

    dest = os.path.join(config.UPLOADS_DIR, str(user_id), bot_name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    try:
        git.Repo.clone_from(repo_url, dest, depth=1)
    except GitCommandError as e:
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"Clone failed: {e}"

    # Don't ship the .git history into the deploy/container image
    git_dir = os.path.join(dest, ".git")
    if os.path.exists(git_dir):
        shutil.rmtree(git_dir, ignore_errors=True)

    return True, dest


def pull_latest(project_path: str) -> tuple[bool, str]:
    """Not used after .git is stripped on clone; kept for repos re-cloned with history."""
    if git is None:
        return False, "GitPython isn't installed on the server."
    try:
        repo = git.Repo(project_path)
        repo.remotes.origin.pull()
        return True, "Updated to latest commit."
    except Exception as e:
        return False, str(e)
