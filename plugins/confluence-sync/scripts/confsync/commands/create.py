"""create-page and create-folder - making new Confluence nodes from local notes.

create_page_here and create_folder_here are the primitives scaffold reuses for every node
in a tree, which is why they take an explicit space/parent instead of parsing args.
"""

import sys
from pathlib import Path

from ..config import (FOLDERS_FILE, MAPPING_FILE, api, get_config, load_json, rel,
                      save_json)
from ..frontmatter import (apply_frontmatter, build_confluence_frontmatter,
                           read_local_frontmatter, split_frontmatter)
from ..hashing import HASH_ALGO, body_hash
from ..rest import post_folder, post_page, put_page, resolve_target
from ..transforms import DIAGRAM_FENCE_RE, md_to_storage


def register_page(cfg, s, mapping, local: Path, page_meta, body_md: str, up_note=None):
    """Record a freshly created/linked page in mapping.json and stamp its frontmatter."""
    f = rel(local)
    mapping[f] = {
        "page_id": str(page_meta["id"]),
        "title": page_meta["title"],
        "version": page_meta["version"]["number"],
        "hash": "",
        "hash_algo": HASH_ALGO,
    }
    if up_note:
        mapping[f]["up_note"] = up_note
    fields = build_confluence_frontmatter(cfg, mapping, page_meta)
    final_text = apply_frontmatter(body_md, read_local_frontmatter(local), fields)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(final_text, encoding="utf-8")
    mapping[f]["hash"] = body_hash(final_text)
    save_json(MAPPING_FILE, mapping)
    return mapping[f]


def create_page_here(cfg, s, space_id, title, parent_id, local: Path, mapping,
                     message=None, up_note=None):
    """Create a Confluence page from a local note (or an empty one) and link the two.

    Pages carrying ```plantuml/```mermaid fences are created empty and then pushed,
    because rendering a diagram uploads an attachment and that needs a page id that does
    not exist yet. Everything else is created with its body inline, so the page starts
    life at v1 with real content instead of an empty v1 nobody wants in the history.
    """
    body_md = ""
    if local.exists():
        body_md = split_frontmatter(local.read_text(encoding="utf-8"))[1]

    has_diagrams = bool(DIAGRAM_FENCE_RE.search(body_md))
    storage = "" if has_diagrams else md_to_storage(body_md, cfg, s, None)
    page = post_page(cfg, s, space_id, title, parent_id, storage)
    entry = register_page(cfg, s, mapping, local, page, body_md, up_note)

    if has_diagrams:
        storage = md_to_storage(body_md, cfg, s, page["id"])
        result = put_page(cfg, s, page["id"], title, storage, entry["version"] + 1,
                          message or "Initial content (confluence-sync)")
        entry = register_page(cfg, s, mapping, local, result, body_md, up_note)
    return entry


def create_folder_here(cfg, s, space_id, title, parent_id, local: Path, folders):
    """Create a Confluence folder, mirror it as a local directory, and link the two."""
    folder = post_folder(cfg, s, space_id, title, parent_id)
    local.mkdir(parents=True, exist_ok=True)
    folders[rel(local)] = {
        "folder_id": str(folder["id"]),
        "title": folder["title"],
        "parent_id": str(folder.get("parentId")) if folder.get("parentId") else None,
    }
    save_json(FOLDERS_FILE, folders)
    return folders[rel(local)]


def cmd_create_page(args):
    cfg = get_config()
    s = api(cfg)
    local = Path(args.file)
    if local.suffix != ".md":
        local = local.with_suffix(".md")
    f = rel(local)
    mapping = load_json(MAPPING_FILE, {})
    if f in mapping:
        sys.exit(f"{f} is already linked to page {mapping[f]['page_id']}. "
                 f"Use 'push' to update it.")

    space_id, parent_id = resolve_target(cfg, s, args.parent, args.space)
    title = args.title or local.stem
    entry = create_page_here(cfg, s, space_id, title, parent_id, local, mapping, args.message)
    print(f"created page \"{title}\" (id {entry['page_id']}, v{entry['version']}) -> {f}")


def cmd_create_folder(args):
    cfg = get_config()
    s = api(cfg)
    local = Path(args.folder)
    folders = load_json(FOLDERS_FILE, {})
    if local.exists() and rel(local) in folders:
        sys.exit(f"{rel(local)} is already linked to folder {folders[rel(local)]['folder_id']}.")

    space_id, parent_id = resolve_target(cfg, s, args.parent, args.space)
    title = args.title or local.name
    entry = create_folder_here(cfg, s, space_id, title, parent_id, local, folders)
    print(f"created folder \"{title}\" (id {entry['folder_id']}) -> {rel(local)}")
