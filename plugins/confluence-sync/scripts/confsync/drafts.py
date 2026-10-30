"""push --draft: a note sent as unpublished changes, for the user to publish in Confluence.

Confluence keeps one shared editor draft per page beside the published version. What the
v2 API does with it (checked 2026-10-30 on a scratch page):

- PUT status=draft replaces the draft's body and title. The published page, its version
  and its history do not move. The version message is dropped.
- The draft has its own version counter, which stays 1 while the page goes v2, v3...
  The PUT must send that number (see rest.get_draft), anything else is a 400.
- The PUT replaces whatever was in the draft, including someone's unpublished edits.
- Images upload as ordinary attachments straight away: listed on the page, shown in the
  draft, shown on the page only once the draft is published.
- Publishing through the API (a normal push) leaves the old draft in place.
- The editor rewrites the draft's XML as soon as it opens it (local-id attributes, image
  layout), so drafts are compared by their text and image names, never byte for byte.

Nothing is published, so the sync point (version, hash, base) stays where it was. The
mapping entry gets a "draft" record instead:

  {"on_version": N, "hash": <note body hash when sent>, "sent_at": "2026-10-30 16:49",
   "fingerprints": [<draft text this tool knows about: what it sent, what got published>]}

The draft is pending while on_version still equals the entry's version: nothing was
pulled or pushed since. When the page then moves, it is most likely the draft being
published, and if the note is still exactly what was sent, pull takes the published
version without calling it a conflict - the note's "local edits" are already in it.
"""

import hashlib

from bs4 import BeautifulSoup

from .hashing import local_body_hash


def fingerprint(storage: str) -> str:
    """Hash of a storage body's words and image names - what survives the editor."""
    soup = BeautifulSoup(storage or "", "html.parser")
    words = " ".join(soup.get_text(" ").split())
    images = sorted(t.get("ri:filename", "") for t in soup.find_all("ri:attachment"))
    return hashlib.sha256((words + "\n" + "\n".join(images)).encode("utf-8")).hexdigest()


def pending(entry) -> bool:
    """A draft was sent and nothing was pulled or pushed since."""
    d = entry.get("draft")
    return bool(d) and d.get("on_version") == entry["version"]


def sent_unchanged(entry, local) -> bool:
    """A draft is pending and the note is still exactly what it sent."""
    return (pending(entry) and local.exists()
            and local_body_hash(local) == entry["draft"]["hash"])


def foreign(entry, draft, published_storage) -> bool:
    """True when the page's draft holds edits that are neither published nor ours."""
    if draft is None:
        return False
    fp = fingerprint(draft["body"]["storage"]["value"])
    return fp != fingerprint(published_storage) and not known(entry, fp)


def known(entry, fp) -> bool:
    """The draft text is one this tool sent, or one it saw published."""
    return fp in (entry.get("draft") or {}).get("fingerprints", [])


def edit_url(cfg, page) -> str:
    links = page.get("_links") or {}
    path = links.get("edituiv2") or f"/pages/resumedraft.action?draftId={page['id']}"
    return cfg["base_url"] + "/wiki" + path
