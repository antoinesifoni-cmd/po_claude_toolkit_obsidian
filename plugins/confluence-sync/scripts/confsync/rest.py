"""Every Confluence Cloud API call the tool makes, plus the id/URL parsing feeding them.

Each function takes the config dict and an authenticated session rather than reaching for
module state, so this layer holds no state of its own.
"""

import re
import sys
from pathlib import Path


# Page and folder ids share one namespace, so a bare id says nothing about its kind and
# has to be probed against both endpoints. A pasted URL already carries the kind in its
# path, which saves the round trip and removes the ambiguity.
_REF_PATTERNS = (
    (re.compile(r"/pages/(\d+)"), "page"),
    (re.compile(r"/folder/(\d+)"), "folder"),
    (re.compile(r"[?&]pageId=(\d+)"), "page"),
)


def parse_ref(ref: str):
    """(node_id, kind_hint) from a Confluence URL or a bare id; hint is None for an id."""
    ref = ref.strip()
    if ref.isdigit():
        return ref, None
    for pattern, kind in _REF_PATTERNS:
        m = pattern.search(ref)
        if m:
            return m.group(1), kind
    sys.exit(f"Could not read a page or folder id out of \"{ref}\"."
             f"\nPaste the Confluence URL, or give the bare numeric id.")


def get_page_meta(cfg, s, page_id):
    """Metadata only - v2 API returns version without body unless body-format is asked."""
    r = s.get(f"{cfg['base_url']}/wiki/api/v2/pages/{page_id}")
    r.raise_for_status()
    return r.json()


def get_folder_meta(cfg, s, folder_id):
    """Folders are organizational containers - id/title/parentId only, no body."""
    r = s.get(f"{cfg['base_url']}/wiki/api/v2/folders/{folder_id}")
    r.raise_for_status()
    return r.json()


def get_page_body(cfg, s, page_id):
    r = s.get(
        f"{cfg['base_url']}/wiki/api/v2/pages/{page_id}",
        params={"body-format": "storage"},
    )
    r.raise_for_status()
    return r.json()


def put_page(cfg, s, page_id, title, storage_html, new_version, message):
    payload = {
        "id": page_id,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_html},
        "version": {"number": new_version, "message": message},
    }
    r = s.put(
        f"{cfg['base_url']}/wiki/api/v2/pages/{page_id}",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    if not r.ok:
        sys.exit(f"Push failed ({r.status_code}): {r.text[:500]}")
    return r.json()


def post_page(cfg, s, space_id, title, parent_id, storage_html=""):
    """Create a page. parent_id may be a page id OR a folder id - Confluence accepts both."""
    payload = {
        "spaceId": str(space_id),
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_html},
    }
    if parent_id:
        payload["parentId"] = str(parent_id)
    r = s.post(f"{cfg['base_url']}/wiki/api/v2/pages", json=payload,
               headers={"Content-Type": "application/json"})
    if not r.ok:
        sys.exit(f"Create page \"{title}\" failed ({r.status_code}): {r.text[:500]}")
    return r.json()


def post_folder(cfg, s, space_id, title, parent_id):
    """Create an organizational folder (no body). parent may be a page or another folder."""
    payload = {"spaceId": str(space_id), "title": title}
    if parent_id:
        payload["parentId"] = str(parent_id)
    r = s.post(f"{cfg['base_url']}/wiki/api/v2/folders", json=payload,
               headers={"Content-Type": "application/json"})
    if not r.ok:
        sys.exit(f"Create folder \"{title}\" failed ({r.status_code}): {r.text[:500]}")
    return r.json()


def resolve_node(cfg, s, node_id):
    """(kind, meta) for an id that may be a page or a folder - callers accept either.

    Confluence ids share one namespace but separate endpoints, so the only way to learn
    which kind an id is, is to ask both. Pages are tried first (far more common as a
    scaffold parent).
    """
    for kind in ("page", "folder"):
        r = s.get(f"{cfg['base_url']}/wiki/api/v2/{kind}s/{node_id}")
        if r.ok:
            return kind, r.json()
    sys.exit(f"{node_id} is neither a page nor a folder you can access "
             f"(check the id and your permissions).")


def personal_space_id(cfg, s):
    """The signed-in user's own personal space (key is ~<accountId>)."""
    r = s.get(f"{cfg['base_url']}/wiki/rest/api/user/current")
    r.raise_for_status()
    account_id = r.json()["accountId"]
    r = s.get(f"{cfg['base_url']}/wiki/api/v2/spaces", params={"keys": f"~{account_id}"})
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        sys.exit("Could not find your personal Confluence space.")
    return str(results[0]["id"])


def resolve_target(cfg, s, parent, space):
    """(space_id, parent_id) from the CLI/spec pair, with a personal-space fallback.

    Precedence: an explicit --space wins; otherwise the space is inherited from the
    parent, which is what you want when someone hands over a single page id. With no
    parent at all, everything lands at the root of the user's personal space - the
    "I did not say where" default.
    """
    parent_id = str(parent) if parent else None
    if space and str(space).lower() == "personal":
        return personal_space_id(cfg, s), parent_id
    if space:
        return str(space), parent_id
    if parent_id:
        _, meta = resolve_node(cfg, s, parent_id)
        return str(meta["spaceId"]), parent_id
    cfg_space = cfg.get("default_space_id")
    if cfg_space:
        return str(cfg_space), None
    return personal_space_id(cfg, s), None


def upload_attachment(cfg, s, page_id, filepath: Path):
    """Upload/replace an attachment on a page (v1 endpoint - v2 has no upload)."""
    url = f"{cfg['base_url']}/wiki/rest/api/content/{page_id}/child/attachment"
    headers = {"X-Atlassian-Token": "nocheck"}
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f)}
        r = s.put(url, headers=headers, files=files)  # PUT = create or update
        if not r.ok:
            r = s.post(url, headers=headers, files=files)
    r.raise_for_status()
    return filepath.name
