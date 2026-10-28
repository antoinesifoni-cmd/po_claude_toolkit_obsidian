"""Images between the vault and Confluence page attachments.

attachments.json records, per "<page_id>/<Confluence filename>", the local file name,
the attachment version and the content hash. That is what lets push skip an image that
did not change and pull skip one it already has, and it is the only link between the two
names when a pulled image had to be renamed to avoid clobbering another page's file.
"""

import hashlib
import json
from pathlib import Path

from .config import ATTACHMENTS_FILE, VAULT, load_json, save_json
from .rest import download_attachment, upload_attachment


SKIP_DIRS = {".confsync", ".obsidian", ".trash", ".git"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attachment_dir(note: Path) -> Path:
    """Where Obsidian puts new attachments for this note (Settings > Files and links)."""
    try:
        app = json.loads((VAULT / ".obsidian" / "app.json").read_text(encoding="utf-8"))
        folder = app.get("attachmentFolderPath", "/")
    except (OSError, ValueError):
        folder = "/"
    if folder in ("", "/"):
        return VAULT
    if folder.startswith("./"):
        return note.parent / folder[2:]
    return VAULT / folder


def find_local(name: str, note: Path):
    """Resolve an embed name the way Obsidian does: a path, or the first file so named."""
    if "/" in name:
        p = VAULT / name
        return p if p.exists() else None
    for candidate in (note.parent / name, attachment_dir(note) / name):
        if candidate.exists():
            return candidate
    for p in VAULT.rglob(name):
        if not SKIP_DIRS.intersection(p.relative_to(VAULT).parts):
            return p
    return None


def push_image(cfg, s, page_id, name: str, note: Path):
    """Upload a local image if it changed. Returns the Confluence filename, or None."""
    path = find_local(name, note)
    if path is None:
        print(f"  ! Image not found in the vault, left as text: {name}")
        return None
    registry = load_json(ATTACHMENTS_FILE, {})
    remote = next((k.split("/", 1)[1] for k, e in registry.items()
                   if k.startswith(f"{page_id}/") and e.get("local") == path.name), path.name)
    key = f"{page_id}/{remote}"
    sha = _sha(path)
    if registry.get(key, {}).get("sha") != sha:
        _, version = upload_attachment(cfg, s, page_id, path, remote)
        registry[key] = {"local": path.name, "version": version, "sha": sha}
        save_json(ATTACHMENTS_FILE, registry)
        print(f"  uploaded image {remote}")
    return remote


def pull_image(cfg, s, page_id, filename: str, version, note: Path) -> str:
    """Download an attachment unless the vault already has that version. Returns the
    local file name to embed."""
    registry = load_json(ATTACHMENTS_FILE, {})
    key = f"{page_id}/{filename}"
    entry = registry.get(key)
    if entry and str(entry.get("version")) == str(version) and find_local(entry["local"], note):
        return entry["local"]

    folder = attachment_dir(note)
    dest = folder / (entry["local"] if entry else filename)
    if not entry and dest.exists():
        # Someone else's file already has this name - keep both.
        dest = folder / f"{Path(filename).stem} ({page_id}){Path(filename).suffix}"
    got = download_attachment(cfg, s, page_id, filename, dest)
    if got is None:
        print(f"  ! Image {filename} is not attached to the page, embed left as is")
        return dest.name
    registry[key] = {"local": dest.name, "version": got, "sha": _sha(dest)}
    save_json(ATTACHMENTS_FILE, registry)
    return dest.name
