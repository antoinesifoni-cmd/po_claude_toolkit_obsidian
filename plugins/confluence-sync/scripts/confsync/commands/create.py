"""create-page and create-folder - making new Confluence nodes from local notes.

create_page_here and create_folder_here are the primitives scaffold reuses for every node
in a tree, which is why they take an explicit space/parent instead of parsing args.
"""

import sys
from pathlib import Path

from datetime import datetime

from .. import drafts
from ..base import save_base, save_draft_base
from ..config import (FOLDERS_FILE, MAPPING_FILE, api, get_config, load_json, rel,
                      save_json)
from ..frontmatter import (apply_frontmatter, build_confluence_frontmatter,
                           read_local_frontmatter, split_frontmatter)
from ..hashing import HASH_ALGO, body_hash
from ..rest import post_folder, post_page, put_page, resolve_target
from ..transforms import md_to_storage, needs_page_id


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
    save_base(mapping[f]["page_id"], final_text)
    save_json(MAPPING_FILE, mapping)
    return mapping[f]


def create_page_here(cfg, s, space_id, title, parent_id, local: Path, mapping,
                     message=None, up_note=None, draft=False):
    """Create a Confluence page from a local note (or an empty one) and link the two.

    Pages carrying diagram fences or image embeds are created empty and then pushed,
    because those upload attachments and that needs a page id that does not exist yet.
    Everything else is created with its body inline, so the page starts life at v1 with
    real content instead of an empty v1 nobody wants in the history.
    """
    body_md = ""
    if local.exists():
        body_md = split_frontmatter(local.read_text(encoding="utf-8"))[1]

    if draft:
        return create_draft_page(cfg, s, space_id, title, parent_id, local, mapping, body_md)

    needs_id = needs_page_id(body_md)
    storage = "" if needs_id else md_to_storage(body_md, cfg, s, None, local)
    page = post_page(cfg, s, space_id, title, parent_id, storage)
    entry = register_page(cfg, s, mapping, local, page, body_md, up_note)

    if needs_id:
        storage = md_to_storage(body_md, cfg, s, page["id"], local)
        result = put_page(cfg, s, page["id"], title, storage, entry["version"] + 1,
                          message or "Initial content (confluence-sync)")
        entry = register_page(cfg, s, mapping, local, result, body_md, up_note)
    return entry


def create_draft_page(cfg, s, space_id, title, parent_id, local: Path, mapping, body_md):
    """create-page --draft: a new page that stays unpublished until published in Confluence.

    Linked like any created page, but at version 0 (nothing published), marked never
    pushed, and with the same "draft" record push --draft writes (see drafts.py). Once
    it is published, it is v1 and the next pull takes it like any published draft.
    """
    needs_id = needs_page_id(body_md)
    storage = "" if needs_id else md_to_storage(body_md, cfg, s, None, local)
    page = post_page(cfg, s, space_id, title, parent_id, storage, status="draft")
    if needs_id:
        storage = md_to_storage(body_md, cfg, s, page["id"], local)
        page = put_page(cfg, s, page["id"], title, storage, page["version"]["number"], "",
                        status="draft")
    # No published version to show; the edit URL is the useful link while it is a draft.
    meta = {**page, "version": {}, "_links": {"webui": (page.get("_links") or {}).get("edituiv2", "")}}
    entry = register_page(cfg, s, mapping, local, {**meta, "version": {"number": 0}}, body_md)
    fm = build_confluence_frontmatter(cfg, mapping, meta)
    local.write_text(apply_frontmatter(body_md, read_local_frontmatter(local), fm), encoding="utf-8")
    entry.update(never_pushed=True, draft={
        "on_version": 0, "hash": body_hash(body_md),
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fingerprints": [drafts.fingerprint(storage)],
    })
    save_draft_base(entry["page_id"], body_md)
    save_json(MAPPING_FILE, mapping)
    print(f"Review and publish it in Confluence: {drafts.edit_url(cfg, page)}")
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
    entry = create_page_here(cfg, s, space_id, title, parent_id, local, mapping, args.message,
                             draft=args.draft)
    if args.draft:
        print(f"created page \"{title}\" as a draft (id {entry['page_id']}), not published -> {f}")
        return
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
