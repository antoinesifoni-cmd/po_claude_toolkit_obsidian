"""pull, push and resolve - the commands that move content.

pull_one is factored out of cmd_pull so `link` can take the remote copy immediately after
linking, without fabricating an args namespace.
"""

import sys
from datetime import datetime
from pathlib import Path

from ..base import line_changes, load_base, save_base
from ..config import (FOLDERS_FILE, MAPPING_FILE, VAULT, api, get_config, is_under,
                      load_json, rel, save_json)
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
    later entry's path. Keys always use "/" (see config.vault_key), so depth and nesting
    are plain string tests.

    The rename goes straight to disk, not through Obsidian, so wikilinks that spell out
    a folder path are not rewritten.
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

        mapping = load_json(MAPPING_FILE, {})
        for path_key in list(mapping.keys()):
            if is_under(path_key, f):
                mapping[new_f + path_key[len(f):]] = mapping.pop(path_key)
        save_json(MAPPING_FILE, mapping)

        for other_key in list(folders.keys()):
            if is_under(other_key, f):
                folders[new_f + other_key[len(f):]] = folders.pop(other_key)
        folders[new_f] = folders.pop(f)
        folders[new_f]["title"] = remote_title
        save_json(FOLDERS_FILE, folders)
        print(f"folder: renamed \"{f}\" -> \"{new_f}\" (Confluence title changed)")


def describe(f, local, entry, page, remote_md, fm_fields, conflict):
    """One row of the decision table the pull skill shows for a note it left alone."""
    base = load_base(entry["page_id"])
    local_text = local.read_text(encoding="utf-8")
    if base is not None:
        yours = line_changes(base, local_text)
    elif not conflict:
        yours = line_changes(remote_md, local_text)  # remote unchanged, so it is the base
    else:
        yours = "size unknown (no copy of the last sync)"
    if not conflict:
        theirs = "no change since your last sync"
    elif base is not None:
        theirs = line_changes(base, remote_md) + " since your last sync"
    else:
        theirs = "changed since your last sync (size unknown)"
    edited = datetime.fromtimestamp(local.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    row = (f"{f} | {'CONFLICT' if conflict else 'push needed'}"
           f" | yours: edited {edited}, {yours}"
           f" | Confluence: v{page['version']['number']} by {fm_fields.get('author', '?')}"
           f" on {fm_fields.get('last_modified', '?')}, {theirs}")
    if conflict:
        row += f" | remote copy: {local.with_suffix('.remote.md').name}"
    return row


def pull_one(cfg, s, mapping, f, force=False, decisions=None, create_dirs=False) -> bool:
    """Pull one mapped file. False if it was skipped or left as a conflict.

    Only writes the note when Confluence has something new and the note has nothing
    unpushed - or when forced. A note with local edits is never touched: if the page
    did not move it is just "push needed", if it did it is a CONFLICT and the remote copy
    goes beside it. Either way a row goes into `decisions` for the skill to show.

    Split out of cmd_pull so `link` can take the remote copy straight after linking,
    without faking an args namespace.
    """
    entry = mapping.get(f)
    if not entry:
        print(f"{f}: not linked, skipping")
        return False
    local = VAULT / f
    if not local.exists() and not local.parent.is_dir() and not (force or create_dirs):
        # Almost always a stale link left by a folder moved outside this tool, not a new
        # page - writing it would rebuild the old folder next to the real one.
        print(f"{f}: its folder no longer exists locally - skipped. If the folder was "
              f"moved or renamed, re-link the note at its new path.")
        return False

    page = get_page_body(cfg, s, entry["page_id"])
    remote_v = page["version"]["number"]
    remote_md = storage_to_md(page["body"]["storage"]["value"])

    local_changed = local.exists() and local_body_hash(local) != entry["hash"]
    remote_changed = remote_v != entry["version"]
    fm_fields = build_confluence_frontmatter(cfg, mapping, page)
    existing_fm = read_local_frontmatter(local)

    if local_changed and not force:
        if remote_changed:
            side = local.with_suffix(".remote.md")
            side.write_text(apply_frontmatter(remote_md, existing_fm, fm_fields), encoding="utf-8")
            entry["conflict_version"] = remote_v
            save_json(MAPPING_FILE, mapping)
            print(f"{f}: CONFLICT - local edits + remote v{remote_v}."
                  f"\n  Remote saved to {side.name}. Your note was not changed.")
        else:
            print(f"{f}: local changes, push needed - skipped")
        if decisions is not None:
            decisions.append(describe(f, local, entry, page, remote_md, fm_fields, remote_changed))
        return False

    if not remote_changed and local.exists() and not force:
        print(f"{f}: already in sync (v{remote_v})")
        return False

    final_text = apply_frontmatter(remote_md, existing_fm, fm_fields)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(final_text, encoding="utf-8")
    entry.update(version=remote_v, hash=body_hash(final_text),
                 hash_algo=HASH_ALGO, title=page["title"])
    entry.pop("conflict_version", None)
    save_base(entry["page_id"], final_text)
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
    decisions = []
    for f in targets:
        pull_one(cfg, s, mapping, f, force=args.force, decisions=decisions)
    if decisions:
        n = len(decisions)
        print(f"\nDECISIONS NEEDED - {n} note{'s' if n > 1 else ''} left untouched:")
        for row in decisions:
            print(f"  {row}")


def cmd_resolve(args):
    """resolve <file> - record that a CONFLICT has been merged into the note.

    Moves the note's sync point to the remote version that was merged in, so the next
    push is an ordinary one: it still aborts if the page moved again since, instead of
    needing --force and trusting that nobody else edited in the meantime.
    """
    mapping = load_json(MAPPING_FILE, {})
    f = rel(Path(args.file))
    entry = mapping.get(f)
    if not entry:
        sys.exit(f"{f} is not linked.")
    side = (VAULT / f).with_suffix(".remote.md")
    remote_v = entry.get("conflict_version")
    if remote_v is None or not side.exists():
        sys.exit(f"{f}: no pending conflict. Run 'conf.py pull {f}' to check for one.")

    remote_text = side.read_text(encoding="utf-8")
    entry.update(version=remote_v, hash=body_hash(remote_text), hash_algo=HASH_ALGO)
    entry.pop("conflict_version")
    save_base(entry["page_id"], remote_text)
    save_json(MAPPING_FILE, mapping)
    side.unlink()
    print(f"{f}: merge recorded against Confluence v{remote_v}, {side.name} removed."
          f"\nThe note now reads 'push needed' - push it to publish the merge.")


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
    entry.pop("conflict_version", None)
    save_base(entry["page_id"], final_text)
    save_json(MAPPING_FILE, mapping)
    print(f"{f}: pushed as v{result['version']['number']} - \"{message}\"")
