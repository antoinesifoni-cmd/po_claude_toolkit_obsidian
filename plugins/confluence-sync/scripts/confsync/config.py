"""Vault discovery, on-disk state files, credentials and the HTTP session.

Every other confsync module imports this one; it deliberately imports none of them,
so it stays the one piece that can be loaded and reasoned about in isolation.

VAULT is resolved once, at import time, by walking up from the working directory until
a .confsync/ directory turns up - so every path constant below is fixed for the life of
the process.
"""

import json
import os
import sys
from pathlib import Path

import requests


def find_vault_root(start: Path) -> Path:
    """Walk up from start until a .confsync dir is found; else use start."""
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".confsync").is_dir():
            return parent
    return p


VAULT = find_vault_root(Path.cwd())


STATE_DIR = VAULT / ".confsync"


MAPPING_FILE = STATE_DIR / "mapping.json"


FOLDERS_FILE = STATE_DIR / "folders.json"


CONFIG_FILE = STATE_DIR / "config.json"


USERS_FILE = STATE_DIR / "users.json"


PLANTUML_JAR = STATE_DIR / "plantuml.jar"


# The body of every linked page as it stood at the last pull or push, one file per page
# id. It is the common ancestor a merge needs: without it, a paragraph present on one
# side only could have been added there or deleted on the other, and nothing says which.
BASE_DIR = STATE_DIR / "base"


def vault_key(path_key: str) -> str:
    """The one spelling of a vault-relative path used as a mapping/folders key: "/".

    Up to 0.10.0 keys were OS-native, so a vault synced on Windows held "a\\b.md" and
    every prefix test written with "/" silently missed - folder renames stopped
    cascading and pull recreated the old tree beside the renamed one. One separator,
    the one Obsidian itself uses, makes the files portable between machines too.
    """
    return path_key.replace("\\", "/")


def is_under(path_key: str, folder_key: str) -> bool:
    """True if path_key is strictly inside folder_key (both vault keys)."""
    return path_key.startswith(folder_key.rstrip("/") + "/")


def load_json(path: Path, default):
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    # Old backslash keys are rewritten on read, and the next save stores them fixed.
    if path in (MAPPING_FILE, FOLDERS_FILE):
        data = {vault_key(k): v for k, v in data.items()}
    return data


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_config():
    cfg = load_json(CONFIG_FILE, {})
    base = os.environ.get("CONFLUENCE_BASE_URL") or cfg.get("base_url")
    email = os.environ.get("CONFLUENCE_EMAIL") or cfg.get("email")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not (base and email and token):
        sys.exit(
            "Missing credentials. Set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL and "
            "CONFLUENCE_API_TOKEN env vars (token: id.atlassian.com > Security > API tokens)."
        )
    cfg["base_url"] = base.rstrip("/")
    cfg["email"] = email
    cfg["token"] = token
    cfg.setdefault("jira_project_keys", [])
    return cfg


def api(cfg):
    s = requests.Session()
    s.auth = (cfg["email"], cfg["token"])
    s.headers.update({"Accept": "application/json"})
    return s


def rel(path: Path) -> str:
    """Vault-relative key for a path, always with "/" (see vault_key)."""
    return path.resolve().relative_to(VAULT).as_posix()
