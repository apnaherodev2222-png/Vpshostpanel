"""
core/dependency_manager.py
Installs dependencies for the non-Docker (process_manager) fallback path.
When running under Docker, dependency installation happens inside the
image build instead (see docker_manager.py Dockerfile templates).
"""

import os
import shutil
import subprocess


def _missing_binary_message(binary: str) -> str:
    install_hint = {
        "npm": "Install Node.js + npm: `sudo apt install -y nodejs npm` (Ubuntu), "
               "or switch USE_DOCKER = True in config.py so Node runs inside a container instead.",
        "pip": "Install pip: `sudo apt install -y python3-pip` (Ubuntu), "
               "or switch USE_DOCKER = True in config.py so Python runs inside a container instead.",
    }.get(binary, f"Install `{binary}` on this server.")
    return f"'{binary}' isn't installed on this server. {install_hint}"


def install_python_deps(project_path: str, timeout: int = 300) -> tuple[bool, str]:
    req = os.path.join(project_path, "requirements.txt")
    if not os.path.exists(req):
        return True, "No requirements.txt found — skipping."

    if shutil.which("pip") is None and shutil.which("pip3") is None:
        return False, _missing_binary_message("pip")
    pip_cmd = "pip" if shutil.which("pip") else "pip3"

    try:
        result = subprocess.run(
            [pip_cmd, "install", "--no-cache-dir", "-r", "requirements.txt"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return False, "pip install timed out."
    except FileNotFoundError:
        return False, _missing_binary_message("pip")


def install_node_deps(project_path: str, timeout: int = 300) -> tuple[bool, str]:
    pkg = os.path.join(project_path, "package.json")
    if not os.path.exists(pkg):
        return True, "No package.json found — skipping."

    if shutil.which("npm") is None:
        return False, _missing_binary_message("npm")

    try:
        result = subprocess.run(
            ["npm", "install", "--omit=dev"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return False, "npm install timed out."
    except FileNotFoundError:
        return False, _missing_binary_message("npm")


def install_missing_python_package(package_name: str, project_path: str) -> tuple[bool, str]:
    """Used by auto_fix when a ModuleNotFoundError is detected in logs."""
    pip_cmd = "pip" if shutil.which("pip") else ("pip3" if shutil.which("pip3") else None)
    if pip_cmd is None:
        return False, _missing_binary_message("pip")

    try:
        result = subprocess.run(
            [pip_cmd, "install", "--no-cache-dir", package_name],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, (result.stdout + result.stderr)[-1000:]
    except subprocess.TimeoutExpired:
        return False, f"Timed out installing {package_name}."
    except FileNotFoundError:
        return False, _missing_binary_message("pip")
