"""link, link-folder, find, relink and unlink - attaching notes to pages that exist.

One `link` command covers pages and folders because every caller starts from the same
place: a pasted reference and a local path. See parse_ref for how the two are told apart.

relink and unlink repair what reconcile.py reports after a rename or delete in the vault:
they only rewrite mapping.json / folders.json, after a backup, and never contact the site.
"""

import sys
from pathlib import Path

from .. import config
from ..config import (FOLDERS_FILE, MAPPING_FILE, VAULT, api, backup_state, get_config,
                      load_json, rel, save_json)
from ..frontmatter import (apply_frontmatter, build_confluence_frontmatter,
                           split_frontmatter)
from ..hashing import HASH_ALGO, body_hash, local_body_hash
from ..reconcile import note_page_id
from ..rest import get_folder_meta, get_page_meta, parse_ref, resolve_node
from .sync import pull_one


def link_page(cfg, s, page_id, path: Path, mapping) -> str:
    """Map a local note to an existing page. Returns the vault-relative path."""
    meta = get_page_meta(cfg, s, page_id)
    f = rel(path)
    local = VAULT / f
    mapping[f] = {
        "page_id": page_id,
        "title": meta["title"],
        "version": 0,  # force first pull/push to be deliberate
        "hash": local_body_hash(local) if local.exists() else "",
        "hash_algo": HASH_ALGO,
        # Cleared by the first publish from this vault. Until then push wants --draft
        # or --first-publish: the first push is where formatting gets flattened.
        "never_pushed": True,
    }

    if local.exists():
        existing_fm, body = split_frontmatter(local.read_text(encoding="utf-8"))
        fields = build_confluence_frontmatter(cfg, mapping, meta)
        final_text = apply_frontmatter(body, existing_fm, fields)
        local.write_text(final_text, encoding="utf-8")
        mapping[f]["hash"] = body_hash(final_text)

    save_json(MAPPING_FILE, mapping)
    print(f"Linked {f} -> \"{meta['title']}\" (page {page_id}, remote v{meta['version']['number']}).")
    return f


def link_folder(cfg, s, folder_id, path: Path) -> str:
    """Map a local directory to an existing Confluence folder."""
    meta = get_folder_meta(cfg, s, folder_id)
    if not path.is_dir():
        sys.exit(f"{path} is not an existing local folder (create it first, then link it)")
    folders = load_json(FOLDERS_FILE, {})
    f = rel(path)
    folders[f] = {
        "folder_id": folder_id,
        "title": meta["title"],
        "parent_id": meta.get("parentId"),
    }
    save_json(FOLDERS_FILE, folders)
    print(f"Linked folder {f} -> \"{meta['title']}\" (folder {folder_id})."
          f"\nRun 'conf.py pull --all' to keep its name in sync with Confluence.")
    return f


def cmd_link(args):
    """link <path> <url-or-id> - page or folder, told apart by the URL or probed.

    One command for both kinds because every caller (a pasted URL, a title search, a
    folder someone just made) starts from the same place: a reference and a local path.
    Making the user pick the right subcommand only exposes an id-namespace detail they
    have no way to resolve themselves.
    """
    cfg = get_config()
    s = api(cfg)
    node_id, hint = parse_ref(args.ref)
    kind = args.kind or hint or resolve_node(cfg, s, node_id)[0]

    path = Path(args.path)
    if kind == "folder":
        link_folder(cfg, s, node_id, path)
        return

    mapping = load_json(MAPPING_FILE, {})
    f = link_page(cfg, s, node_id, path, mapping)
    # A freshly linked note is empty or stale far more often than it is authoritative,
    # so taking the remote copy is the safe default: skipping it leaves a note whose
    # next push would publish over the real page.
    if args.no_pull:
        print(f"Run 'conf.py pull {f}' to fetch the page content.")
        return
    pull_one(cfg, s, mapping, f, create_dirs=True)


def cmd_find(args):
    """Search Confluence by title, so linking never requires fetching a URL by hand."""
    cfg = get_config()
    s = api(cfg)
    safe = args.query.replace('"', '\\"')
    cql = f'title ~ "{safe}"'
    if args.space:
        cql += f' and space = "{args.space}"'

    # Folders are a newer content type and not every site indexes them under that name,
    # so narrow first and retry untyped rather than returning an empty list on a 400.
    def search(query):
        return s.get(f"{cfg['base_url']}/wiki/rest/api/content/search",
                     params={"cql": query, "limit": args.limit, "expand": "space"})

    r = search(f"type in (page,folder) and {cql}")
    if not r.ok:
        r = search(cql)
    if not r.ok:
        sys.exit(f"Search failed ({r.status_code}): {r.text[:300]}")

    results = r.json().get("results", [])
    if not results:
        print(f"Nothing titled like \"{args.query}\".")
        return
    for c in results:
        space = (c.get("space") or {}).get("key", "?")
        print(f"  {c.get('type', '?'):<7} {c['id']:<14} [{space}] {c['title']}")
        webui = (c.get("_links") or {}).get("webui", "")
        if webui:
            print(f"          {cfg['base_url']}/wiki{webui}")
    print("\nLink one with: conf.py link <path> <id>")


def cmd_relink(args):
    """relink <old> <new> - a linked note or folder was renamed or moved in the vault.

    Moves its entry to the new path, keeping version, hash and draft state, so the note
    stays linked to the same page. Nothing is sent to Confluence: a local rename never
    renames the page. For a folder, the notes and folders inside it move with it.
    """
    mapping = load_json(config.MAPPING_FILE, {})
    folders = load_json(config.FOLDERS_FILE, {})
    old, new = rel(Path(args.old)), rel(Path(args.new))
    target = config.VAULT / new

    if old in mapping:
        pid = str(mapping[old]["page_id"])
        if not target.is_file():
            sys.exit(f"{new} is not a note in the vault.")
        if new in mapping:
            sys.exit(f"{new} is already linked to page {mapping[new]['page_id']}.")
        if note_page_id(target) != pid:
            sys.exit(f"{new} does not carry page_id {pid} in its properties, so it is not "
                     f"the renamed note. Use `link` to attach it on purpose.")
        backup_state()
        mapping[new] = mapping.pop(old)
        save_json(config.MAPPING_FILE, mapping)
        print(f"Relinked {old} -> {new} (page {pid}, still v{mapping[new]['version']}).")
        return

    if old in folders:
        if not target.is_dir():
            sys.exit(f"{new} is not a folder in the vault.")
        if new in folders:
            sys.exit(f"{new} is already linked to folder {folders[new]['folder_id']}.")
        backup_state()
        moved, left = 0, []
        for key in sorted(k for k in mapping if config.is_under(k, old)):
            dest = new + key[len(old):]
            same = note_page_id(config.VAULT / dest) == str(mapping[key]["page_id"])
            if dest not in mapping and same:
                mapping[dest] = mapping.pop(key)
                moved += 1
            else:
                left.append(key)
        for key in sorted(k for k in folders if config.is_under(k, old)):
            dest = new + key[len(old):]
            if dest not in folders and (config.VAULT / dest).is_dir():
                folders[dest] = folders.pop(key)
        folders[new] = folders.pop(old)
        save_json(config.MAPPING_FILE, mapping)
        save_json(config.FOLDERS_FILE, folders)
        print(f"Relinked folder {old} -> {new} (folder {folders[new]['folder_id']}), "
              f"{moved} note{'s' if moved != 1 else ''} inside moved with it.")
        for key in left:
            print(f"  not moved: {key} - not found at the same place in {new}. Run status.")
        return

    sys.exit(f"{old} is not linked, so there is nothing to relink.")


def cmd_unlink(args):
    """unlink <path> - forget a note's or folder's link. Confluence is not touched.

    The page's saved copy in .confsync/base/ is kept, so linking the note again later
    still has its merge ancestor. A folder takes with it the entries inside it whose
    files are gone too.
    """
    mapping = load_json(config.MAPPING_FILE, {})
    folders = load_json(config.FOLDERS_FILE, {})
    f = rel(Path(args.path))

    if f in mapping:
        backup_state()
        entry = mapping.pop(f)
        save_json(config.MAPPING_FILE, mapping)
        print(f"Unlinked {f} (page {entry['page_id']}). The Confluence page is untouched.")
        if (config.VAULT / f).exists():
            print("The note is still in the vault, with its Confluence properties. "
                  "They no longer do anything.")
        return

    if f in folders:
        backup_state()
        gone = [k for k in mapping if config.is_under(k, f) and not (config.VAULT / k).exists()]
        for k in gone:
            mapping.pop(k)
        for k in [k for k in folders
                  if config.is_under(k, f) and not (config.VAULT / k).is_dir()]:
            folders.pop(k)
        entry = folders.pop(f)
        save_json(config.MAPPING_FILE, mapping)
        save_json(config.FOLDERS_FILE, folders)
        print(f"Unlinked folder {f} (folder {entry['folder_id']}) and {len(gone)} "
              f"note{'s' if len(gone) != 1 else ''} that were in it. Confluence is untouched.")
        return

    sys.exit(f"{f} is not linked.")
