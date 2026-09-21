"""link, link-folder and find - attaching notes to pages that already exist.

One `link` command covers pages and folders because every caller starts from the same
place: a pasted reference and a local path. See parse_ref for how the two are told apart.
"""

import sys
from pathlib import Path

from ..config import (FOLDERS_FILE, MAPPING_FILE, VAULT, api, get_config, load_json,
                      rel, save_json)
from ..frontmatter import (apply_frontmatter, build_confluence_frontmatter,
                           split_frontmatter)
from ..hashing import HASH_ALGO, body_hash, local_body_hash
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
    pull_one(cfg, s, mapping, f)


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
