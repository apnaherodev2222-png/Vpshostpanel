"""
core/runtime_detector.py
Inspects an uploaded/cloned project folder and figures out:
  - which runtime it needs (python / node)
  - what the entrypoint file is
"""

import os

PYTHON_ENTRY_CANDIDATES = ["main.py", "bot.py", "app.py", "run.py", "__main__.py"]
NODE_ENTRY_CANDIDATES = ["index.js", "main.js", "app.js", "bot.js", "server.js"]


def detect_runtime(project_path: str):
    """
    Returns a dict: {"runtime": "python"|"node"|None, "entrypoint": str|None,
                      "dependency_file": str|None}
    """
    files = set(os.listdir(project_path))

    # Node.js project
    if "package.json" in files:
        entry = _find_package_json_entry(project_path) or _first_match(files, NODE_ENTRY_CANDIDATES)
        return {
            "runtime": "node",
            "entrypoint": entry,
            "dependency_file": "package.json",
        }

    # Python project
    if "requirements.txt" in files or any(f.endswith(".py") for f in files):
        entry = _first_match(files, PYTHON_ENTRY_CANDIDATES)
        if not entry:
            py_files = [f for f in files if f.endswith(".py")]
            entry = py_files[0] if py_files else None
        return {
            "runtime": "python",
            "entrypoint": entry,
            "dependency_file": "requirements.txt" if "requirements.txt" in files else None,
        }

    return {"runtime": None, "entrypoint": None, "dependency_file": None}


def _first_match(files, candidates):
    for c in candidates:
        if c in files:
            return c
    return None


def _find_package_json_entry(project_path: str):
    import json
    pkg_path = os.path.join(project_path, "package.json")
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        main = data.get("main")
        if main and os.path.exists(os.path.join(project_path, main)):
            return main
    except Exception:
        pass
    return None
