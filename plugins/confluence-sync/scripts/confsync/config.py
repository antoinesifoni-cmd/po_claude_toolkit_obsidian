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


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


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
    return str(path.resolve().relative_to(VAULT))
