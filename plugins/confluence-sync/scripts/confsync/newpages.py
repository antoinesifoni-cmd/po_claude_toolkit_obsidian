"""New pages and folders on Confluence, under what the vault already links.

Someone adds a page inside a linked folder, or under a linked page, and nothing tells the
vault. One CQL search finds what was created there lately, at any depth:

    type in (page, folder) and ancestor in (<every linked folder and page>)
                           and created >= now("-14d")

Anything it returns that is not linked and not ignored is new. A page inside a new folder
is counted on the folder's line instead of getting its own. The window rolls, so the
first run lists the last 14 days, not every page ever left out, and a page nobody adds
stops showing after 14 days.

status reports them (read-only). `add` links one into the matching vault folder and pulls
it, `ignore` remembers it in .confsync/ignored.json so it never shows again.
"""

import re
from datetime import date

from . import config

# Same rule as scaffold.safe_name, kept here so status never needs scaffold's YAML import.
ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(title: str) -> str:
    cleaned = ILLEGAL_NAME_CHARS.sub("-", title).rstrip(". ")
    return cleaned or "untitled"


NEW_DAYS = 14
CHUNK = 150          # ids per CQL query, which keeps the query well under URL limits
PAGE = 100           # results per call
MAX_CALLS = 10


def ignored_file():
    return config.STATE_DIR / "ignored.json"


def ignored_ids() -> set:
    data = config.load_json(ignored_file(), {})
    return {str(i.get("id")) for i in data.get("ignored", []) if isinstance(i, dict)}


def remember_ignored(node: dict):
    data = config.load_json(ignored_file(), {})
    items = [i for i in data.get("ignored", []) if isinstance(i, dict)]
    if str(node["id"]) not in {str(i.get("id")) for i in items}:
        items.append({"id": str(node["id"]), "title": node.get("title"),
                      "type": node.get("type"), "on": date.today().isoformat()})
    config.save_json(ignored_file(), {"ignored": items})


def search_cql(cfg, s, cql: str, start: int = 0) -> dict:
    r = s.get(f"{cfg['base_url']}/wiki/rest/api/content/search",
              params={"cql": cql, "limit": PAGE, "start": start,
                      "expand": "ancestors,history"})
    if not r.ok:
        raise RuntimeError(f"search failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def search_all(cfg, s, cql: str) -> list:
    out, start = [], 0
    for _ in range(MAX_CALLS):
        data = search_cql(cfg, s, cql, start)
        found = data.get("results", [])
        out += found
        if len(found) < PAGE:
            break
        start += len(found)
    return out


def linked_places(mapping: dict, folders: dict) -> dict:
    """{confluence id: the local folder that holds its children}."""
    places = {}
    for key, entry in folders.items():
        if entry.get("folder_id"):
            places[str(entry["folder_id"])] = key
    for key, entry in mapping.items():
        if entry.get("page_id"):
            places[str(entry["page_id"])] = key.rsplit("/", 1)[0] if "/" in key else ""
    return places


def local_dir(node: dict, places: dict):
    """Where a node goes in the vault: the nearest linked ancestor's folder, then one
    folder per Confluence folder between it and the node. None when nothing above it is
    linked."""
    chain = node.get("ancestors") or []
    for i in range(len(chain) - 1, -1, -1):
        anc_id = str(chain[i].get("id"))
        if anc_id in places:
            parts = [places[anc_id]] if places[anc_id] else []
            parts += [safe_name(a.get("title") or "") for a in chain[i + 1:] if a.get("type") == "folder"]
            return "/".join(parts)
    return None


def describe(node: dict) -> dict:
    history = node.get("history") or {}
    return {"id": str(node["id"]), "type": node.get("type") or "page",
            "title": node.get("title") or "", "by": (history.get("createdBy") or {}).get("displayName"),
            "date": (history.get("createdDate") or "")[:10]}


def find_new(cfg, s, mapping: dict, folders: dict, days: int = NEW_DAYS) -> list:
    """The new pages and folders, newest first, each with its local `dir` and, for a
    folder, how many new pages are `inside` it."""
    places = linked_places(mapping, folders)
    ids = sorted(places)
    if not ids:
        return []
    found = {}
    for k in range(0, len(ids), CHUNK):
        cql = (f"type in (page, folder) and ancestor in ({', '.join(ids[k:k + CHUNK])}) "
               f"and created >= now(\"-{days}d\")")
        for node in search_all(cfg, s, cql):
            found[str(node["id"])] = node
    skip = ignored_ids()
    new = {i: n for i, n in found.items() if i not in places and i not in skip
           and not any(str(a.get("id")) in skip for a in n.get("ancestors") or [])}
    out, inside = [], {}
    for i, node in new.items():
        holder = next((str(a["id"]) for a in node.get("ancestors") or [] if str(a.get("id")) in new
                       and new[str(a["id"])].get("type") == "folder"), None)
        if holder:
            inside[holder] = inside.get(holder, 0) + (node.get("type") != "folder")
            continue
        item = describe(node)
        item["dir"] = local_dir(node, places)
        out.append(item)
    for item in out:
        if item["type"] == "folder":
            item["inside"] = inside.get(item["id"], 0)
    return sorted(out, key=lambda x: (x["date"], x["title"]), reverse=True)


def report_new(items: list) -> list:
    lines = []
    for it in items:
        where = it["dir"] or "a place the vault does not link"
        by = f", by {it['by']}" if it.get("by") else ""
        if it["type"] == "folder":
            n = it.get("inside", 0)
            lines.append(f'NEW FOLDER: "{it["title"]}" (folder {it["id"]}) in {where}, {n} page'
                         f'{"" if n == 1 else "s"} inside{by}, {it["date"]}. '
                         f'Add it: conf.py add {it["id"]} | ignore it: conf.py ignore {it["id"]}')
        else:
            lines.append(f'NEW: "{it["title"]}" (page {it["id"]}) in {where}{by}, {it["date"]}. '
                         f'Add it: conf.py add {it["id"]} | ignore it: conf.py ignore {it["id"]}')
    return lines


def fetch_node(cfg, s, node_id: str) -> dict:
    found = search_cql(cfg, s, f"id = {node_id}").get("results", [])
    if not found:
        raise RuntimeError(f"No page or folder {node_id} on Confluence.")
    return found[0]


def descendants(cfg, s, folder_id: str) -> list:
    """Every page and folder under a folder, parents before children."""
    nodes = search_all(cfg, s, f"type in (page, folder) and ancestor = {folder_id}")
    return sorted(nodes, key=lambda n: len(n.get("ancestors") or []))
