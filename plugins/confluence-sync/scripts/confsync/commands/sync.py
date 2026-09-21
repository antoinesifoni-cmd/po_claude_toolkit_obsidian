"""pull and push - the two directions content actually moves.

pull_one is factored out of cmd_pull so `link` can take the remote copy immediately after
linking, without fabricating an args namespace.
"""

import sys
from pathlib import Path

from ..config import (FOLDERS_FILE, MAPPING_FILE, VAULT, api, get_config, load_json,
                      rel, save_json)
from ..frontmatter import (apply_frontmatter, build_confluence_frontmatter,
                           read_local_frontmatter, split_frontmatter)
from ..hashing import HASH_ALGO, body_hash, local_body_hash
from ..rest import get_folder_meta, get_page_body, get_page_meta, put_page
from ..transforms import md_to_storage, storage_to_md


def sync_folders(cfg, s):
    """One-way: rename local folders to match their current Confluence folder title.

    Confluence wins (no folder body to conflict on). A rename cascades into every
    mapping.json/folders.json path nested under the renamed folder. Re-reads folders.json
    each iteration since an earlier rename in this same pass may have already moved a
    later entry's path.
    """
    initial = load_json(FOLDERS_FILE, {})
    if not initial:
        return
    ordered_ids = [e["folder_id"] for _, e in sorted(initial.items(), key=lambda kv: kv[0].count("/"))]
    for folder_id in ordered_ids:
        folders = load_json(FOLDERS_FILE, {})
        f = next((k for k, e in folders.items() if e["folder_id"] == folder_id), None)
        if f is None:
            continue  # already renamed away as part of an ancestor's cascade below
        local = VAULT / f
        if not local.is_dir():
            print(f"folder {f}: local path missing, skipping")
            continue

        remote_title = get_folder_meta(cfg, s, folder_id)["title"]
        if local.name == remote_title:
            continue

        new_local = local.parent / remote_title
        if new_local.exists():
            print(f"folder {f}: Confluence renamed it to \"{remote_title}\" but "
                  f"{new_local} already exists locally - skipping, resolve by hand")
            continue

        local.rename(new_local)
        new_f = rel(new_local)
        old_prefix, new_prefix = f + "/", new_f + "/"

        mapping = load_json(MAPPING_FILE, {})
        for path_key in list(mapping.keys()):
            if path_key.startswith(old_prefix):
                mapping[new_prefix + path_key[len(old_prefix):]] = mapping.pop(path_key)
        save_json(MAPPING_FILE, mapping)

        for other_key in list(folders.keys()):
            if other_key != f and other_key.startswith(old_prefix):
                folders[new_prefix + other_key[len(old_prefix):]] = folders.pop(other_key)
        folders[new_f] = folders.pop(f)
        folders[new_f]["title"] = remote_title
        save_json(FOLDERS_FILE, folders)
        print(f"folder: renamed \"{f}\" -> \"{new_f}\" (Confluence title changed)")


def pull_one(cfg, s, mapping, f, force=False) -> bool:
    """Pull one mapped file. False if it was skipped or left as a conflict.

    Split out of cmd_pull so `link` can take the remote copy straight after linking,
    without faking an args namespace.
    """
    entry = mapping.get(f)
    if not entry:
        print(f"{f}: not linked, skipping")
        return False
    local = VAULT / f
    page = get_page_body(cfg, s, entry["page_id"])
    remote_v = page["version"]["number"]
    remote_md = storage_to_md(page["body"]["storage"]["value"])

    local_dirty = local.exists() and local_body_hash(local) != entry["hash"]
    fm_fields = build_confluence_frontmatter(cfg, mapping, page)
    existing_fm = read_local_frontmatter(local)

    if local_dirty and remote_v != entry["version"] and not force:
        side = local.with_suffix(".remote.md")
        side.write_text(apply_frontmatter(remote_md, existing_fm, fm_fields), encoding="utf-8")
        print(f"{f}: CONFLICT - local edits + remote v{remote_v}."
              f"\n  Remote saved to {side.name}. Merge manually, then push."
              f"\n  (or re-run pull --force to overwrite local)")
        return False

    final_text = apply_frontmatter(remote_md, existing_fm, fm_fields)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(final_text, encoding="utf-8")
    entry.update(version=remote_v, hash=body_hash(final_text),
                 hash_algo=HASH_ALGO, title=page["title"])
    save_json(MAPPING_FILE, mapping)
    print(f"{f}: pulled v{remote_v} (\"{page['title']}\")")
    return True


def cmd_pull(args):
    cfg = get_config()
    s = api(cfg)
    if args.all:
        sync_folders(cfg, s)
    mapping = load_json(MAPPING_FILE, {})
    targets = sorted(mapping.keys()) if args.all else [rel(Path(args.file))]
    for f in targets:
        pull_one(cfg, s, mapping, f, force=args.force)


def cmd_push(args):
    cfg = get_config()
    s = api(cfg)
    mapping = load_json(MAPPING_FILE, {})
    f = rel(Path(args.file))
    entry = mapping.get(f)
    if not entry:
        sys.exit(f"{f} is not linked. Use: conf.py link {f} <pageId>")
    local = VAULT / f
    if not local.exists():
        sys.exit(f"{local} does not exist")

    meta = get_page_meta(cfg, s, entry["page_id"])
    remote_v = meta["version"]["number"]
    if remote_v != entry["version"] and not args.force:
        sys.exit(
            f"ABORT: remote is v{remote_v} but you last synced v{entry['version']}."
            f"\nSomeone edited the page. Run 'conf.py pull {f}' first, merge, then push."
            f"\n(--force overrides, clobbering their changes - use with care)"
        )

    existing_fm, md_text = split_frontmatter(local.read_text(encoding="utf-8"))
    storage = md_to_storage(md_text, cfg, s, entry["page_id"])
    message = args.message or "Updated via confluence-sync"
    result = put_page(cfg, s, entry["page_id"], entry.get("title") or meta["title"],
                      storage, remote_v + 1, message)

    fm_fields = build_confluence_frontmatter(cfg, mapping, result)
    final_text = apply_frontmatter(md_text, existing_fm, fm_fields)
    local.write_text(final_text, encoding="utf-8")

    entry.update(version=result["version"]["number"], hash=body_hash(final_text),
                 hash_algo=HASH_ALGO)
    save_json(MAPPING_FILE, mapping)
    print(f"{f}: pushed as v{result['version']['number']} - \"{message}\"")
