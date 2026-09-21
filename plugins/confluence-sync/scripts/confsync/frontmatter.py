"""The YAML properties block at the top of a note (Obsidian's Properties panel).

confsync owns the keys in CONFSYNC_FM_KEYS and rewrites them on every link/pull/push;
any other key on the note is a manual property and is carried through untouched.
"""

import re
from pathlib import Path

import yaml

from .config import USERS_FILE, load_json


# Keys confsync owns end-to-end: rewritten from Confluence metadata on every link/pull/push.
# Any other frontmatter key already on the note (manual properties) is left untouched.
CONFSYNC_FM_KEYS = (
    "title", "page_id", "confluence_version", "parent_page_id", "confluence_space",
    "confluence_url", "up", "last_modified", "author",
)


FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def split_frontmatter(text: str):
    """(frontmatter_dict, body) - frontmatter_dict is {} if the file has none."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end():]


def render_frontmatter(fm: dict) -> str:
    if not fm:
        return ""
    dumped = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{dumped}---\n\n"


def read_local_frontmatter(path: Path) -> dict:
    if not path.exists():
        return {}
    fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return fm


def apply_frontmatter(body_md: str, existing_fm: dict, updates: dict) -> str:
    """Rewrite the confsync-owned keys, keep manual keys, then re-attach the body.

    A key present in CONFSYNC_FM_KEYS but absent from `updates` (e.g. no parent page,
    so no `up`) is dropped rather than left stale.
    """
    manual = {k: v for k, v in existing_fm.items() if k not in CONFSYNC_FM_KEYS}
    merged = {k: updates[k] for k in CONFSYNC_FM_KEYS if k in updates}
    merged.update(manual)
    return render_frontmatter(merged) + body_md.lstrip("\n")


def build_confluence_frontmatter(cfg, mapping: dict, meta: dict) -> dict:
    """Human-readable fields derived from a v2 API page payload (meta/body/put response)."""
    fields = {"title": meta["title"], "page_id": str(meta["id"])}

    version = meta.get("version") or {}
    if version.get("number") is not None:
        fields["confluence_version"] = version["number"]

    parent_id = meta.get("parentId")
    if parent_id:
        fields["parent_page_id"] = str(parent_id)
        for rel_path, entry in mapping.items():
            if str(entry.get("page_id")) == str(parent_id):
                fields["up"] = f"[[{Path(rel_path).stem}]]"
                break

    # A page parented by a *folder* has no parent note to link, and Obsidian wikilinks
    # can only target notes - so scaffold records an anchor note per entry and `up` falls
    # back to it. Persisted in mapping.json rather than recomputed from Confluence
    # ancestry because the anchor (a project's Read Me) is typically a *sibling* of the
    # folders, never an ancestor, so ancestry can never find it.
    if "up" not in fields:
        own = next((e for e in mapping.values() if str(e.get("page_id")) == str(meta["id"])), None)
        if own and own.get("up_note"):
            fields["up"] = f"[[{own['up_note']}]]"

    webui = (meta.get("_links") or {}).get("webui", "")
    space_match = re.match(r"/spaces/([^/]+)/pages", webui)
    if space_match:
        fields["confluence_space"] = space_match.group(1)
    if webui:
        fields["confluence_url"] = cfg["base_url"] + "/wiki" + webui

    created = version.get("createdAt")
    if created:
        fields["last_modified"] = created[:10]  # YYYY-MM-DD, renders as a date property

    author_id = version.get("authorId")
    if author_id:
        users = load_json(USERS_FILE, {})
        by_id = {v["account_id"]: k for k, v in users.items()}
        fields["author"] = by_id.get(author_id, author_id)

    return fields
