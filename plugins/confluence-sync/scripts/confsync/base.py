"""The last-synced body of each page - the common ancestor a merge works from.

mapping.json only keeps a hash of the last sync, which says *that* a side changed but not
*what* changed. Keeping the text itself lets a merge tell an edit made on one side from
a deletion made on the other, and lets pull report how big each side's changes are.

One file per page id under .confsync/base/, body only (frontmatter is confsync's own
metadata and never part of a merge). Written on every pull, push and create; a page
linked before 0.11.0 gets its first one on its next pull or push.
"""

import difflib

from .config import BASE_DIR
from .frontmatter import split_frontmatter


def normalize(text: str) -> str:
    body = split_frontmatter(text)[1]
    return body.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def base_path(page_id):
    return BASE_DIR / f"{page_id}.md"


def save_base(page_id, text: str):
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    base_path(page_id).write_text(normalize(text), encoding="utf-8")


def load_base(page_id):
    p = base_path(page_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


# The body last sent by `push --draft`. Until that draft is published it is a better
# ancestor than the base: the published version grows out of it, not out of the base.
def draft_base_path(page_id):
    return BASE_DIR / f"{page_id}.draft.md"


def save_draft_base(page_id, text: str):
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    draft_base_path(page_id).write_text(normalize(text), encoding="utf-8")


def load_draft_base(page_id):
    p = draft_base_path(page_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


def line_changes(old: str, new: str) -> str:
    """'+added -removed' lines from old to new, bodies only."""
    a, b = normalize(old).splitlines(), normalize(new).splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return f"+{added} -{removed}"
