"""Body-only content hashing - the optimistic lock behind status, pull and push.

Split from config.py because the hash has to skip frontmatter, which makes it depend on
the frontmatter parser. Keeping it separate is what stops config.py needing an import it
would otherwise want for a single function.
"""

import hashlib
from pathlib import Path

from .frontmatter import split_frontmatter


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# Marks a mapping entry whose `hash` covers the body only. Entries without it were
# written by <=0.3.0 (whole-file hash) and need `conf.py rebaseline` once.
HASH_ALGO = "body1"


def body_hash(text: str) -> str:
    """Hash the markdown body, ignoring YAML frontmatter.

    Push strips frontmatter before upload (see cmd_push), so frontmatter is by
    definition not push-relevant. Hashing it made every note read "local changes"
    the moment Obsidian's Properties panel reformatted the YAML (it writes block
    sequences at 2-space indent and double quotes, PyYAML writes them at zero
    indent with single quotes, so the two never agree). That stuck-dirty flag also
    poisoned the pull conflict check, turning clean pulls into spurious CONFLICTs.

    Callers reaching this via read_text() already get universal-newline translation
    (CRLF -> LF), but the normalization is repeated here so the function is correct
    for any caller, including one passing raw bytes decoded elsewhere.
    """
    body = split_frontmatter(text)[1]
    return sha256(body.replace("\r\n", "\n").replace("\r", "\n").strip())


def local_body_hash(path: Path) -> str:
    return body_hash(path.read_text(encoding="utf-8"))


def is_legacy(entry: dict) -> bool:
    """True for entries still carrying a whole-file hash from <=0.3.0."""
    return entry.get("hash_algo") != HASH_ALGO
