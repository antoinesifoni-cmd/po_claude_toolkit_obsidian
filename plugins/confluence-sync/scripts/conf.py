#!/usr/bin/env python3
"""
conf.py - Git-like sync between local Markdown files and Confluence Cloud.

Commands:
  status       [file]              Compare local files vs remote versions
  pull         <file|--all>        Download remote page(s) -> markdown (conflict-safe)
  push         <file> -m "msg"     Upload local markdown -> Confluence (optimistic lock)
  find         <title>             Search Confluence by title (to get an id to link)
  link         <path> <url|id>     Map a note/folder to an existing page/folder
  link-folder  <path> <url|id>     Alias for `link`, forced to folder
  create-page   <file>   --parent <id>  Create a NEW Confluence page from a local note
  create-folder <folder> --parent <id>  Create a NEW Confluence folder + local directory
  scaffold     <spec.yaml>         Create a whole folder/page tree in one pass
  rebaseline   [--check]           Migrate pre-0.4.0 whole-file hashes to body-only
  users        <query>             Search Confluence users (to populate users.json)

Auth (env vars):
  CONFLUENCE_BASE_URL   e.g. https://medfar.atlassian.net
  CONFLUENCE_EMAIL      your Atlassian account email
  CONFLUENCE_API_TOKEN  API token from https://id.atlassian.com/manage-profile/security/api-tokens

State lives in <vault>/.confsync/:
  config.json    { "base_url": "...", "jira_project_keys": ["RD","MYLE",...] }
  mapping.json   { "<relative/path.md>": {"page_id": "...", "version": N, "hash": "sha256..."} }
  folders.json   { "<relative/folder/path>": {"folder_id": "...", "title": "...", "parent_id": "..."} }
  users.json     { "alias": {"account_id": "...", "display_name": "..."} }

mapping.json remains the source of truth for the optimistic-lock version/hash. Every
link/pull/push also mirrors human-readable metadata (page_id, confluence_version,
confluence_url, author, last_modified, ...) into each note's YAML frontmatter for
visibility in Obsidian's Properties panel - see CONFSYNC_FM_KEYS. Those keys are
regenerated on every sync; don't hand-edit them.

Since 0.4.0 the stored hash covers the markdown body only, never the frontmatter
(entries carry "hash_algo": "body1"). Push strips frontmatter before upload anyway, so
frontmatter can't be push-relevant, and hashing it made Obsidian's YAML reformatting
look like a local edit on every note. See body_hash(). Entries written by <=0.3.0 are
flagged by `status` and migrated by `rebaseline`.

`link` takes a pasted Confluence URL or a bare id and works out for itself whether it
names a page or a folder (see parse_ref): the URL path says which, and a bare id is
probed against both endpoints. Linking a page then pulls it, because a just-linked note
is far more often empty or stale than authoritative - pass --no-pull to opt out. `find`
searches by title so getting an id never means leaving the editor to copy a URL.

The link/link-folder commands attach to pages that already exist; create-page,
create-folder and scaffold make new ones. scaffold reads a YAML/JSON tree spec and walks
it parents-first, creating each node in Confluence and mirroring it into the vault at the
matching path. It is idempotent - nodes already present in mapping.json/folders.json are
skipped and their ids reused - so an interrupted run is resumed by re-running it.

A spec carries `variables` (substituted into titles and bodies as {placeholders}), a
`frontmatter` block merged into every created note as manual properties, and per-node
`raw` / `target` / `repeat_per_team` / `when` flags. See expand_tree() for team expansion
and team-mode gating, and render_title() for the "{key} - {team} - {title}" convention;
templates/project.yaml is the shipped Medfar project tree.

Confluence "folders" (organizational containers, no page body) can be tracked with
link-folder. `pull --all` then renames the local folder to match the current Confluence
folder title, one-way (Confluence wins), cascading the rename into mapping.json/
folders.json paths nested under it.

```plantuml / ```mermaid fences always push their raw source into a Confluence
collapsible "expand" section (see DIAGRAM_TITLES). PlantUML also renders a PNG (shown
above the section) when java + plantuml.jar are present in .confsync/; Mermaid has no
local renderer, so it's always text-only. Pull converts either back into an inline fence.

Code layout - this file is only the argparse wiring; everything else is in confsync/:

  config.py       vault discovery, the .confsync/ state paths, credentials, HTTP session
  frontmatter.py  the YAML properties block: parse, render, merge, derive from a page
  hashing.py      body-only hashing (see the 0.4.0 note above) - the optimistic lock
  rest.py         every Confluence API call, plus URL/id parsing (parse_ref)
  transforms.py   markdown <-> storage format: jira links, diagrams, mentions

  commands/status.py    status, rebaseline          (read-only, never writes remotely)
  commands/sync.py      pull, push                  (the two directions content moves)
  commands/link.py      link, link-folder, find     (attach to pages that exist)
  commands/create.py    create-page, create-folder  (make new ones)
  commands/scaffold.py  scaffold                    (whole trees from a YAML spec)
  commands/users.py     users

Dependencies run one way and stay shallow. config.py and rest.py import no siblings at
all, so either can be read on its own; frontmatter -> config, hashing -> frontmatter,
transforms -> config + rest; and the command modules sit on top of all of them. Nothing
under confsync/ imports a command module. The only command-to-command imports are
link -> sync (link pulls straight after linking) and scaffold -> create (it creates each
node in the tree).

Dependencies: requests, markdown, markdownify, pyyaml   (pip install -r requirements.txt)
Optional: java + plantuml.jar in .confsync/ for PlantUML rendering.
"""

import argparse
import sys

try:
    import requests  # noqa: F401  - imported here so a missing dep fails with advice
    import yaml  # noqa: F401
    import markdown  # noqa: F401
    import markdownify  # noqa: F401
except ImportError as e:
    sys.exit(f"Missing dependency: {e.name}. Run: pip install requests markdown markdownify pyyaml")

from confsync.commands.create import cmd_create_folder, cmd_create_page
from confsync.commands.link import cmd_find, cmd_link
from confsync.commands.scaffold import cmd_scaffold
from confsync.commands.status import cmd_rebaseline, cmd_status
from confsync.commands.sync import cmd_pull, cmd_push
from confsync.commands.users import cmd_users


def main():
    p = argparse.ArgumentParser(description="Git-like Confluence sync for a markdown vault")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status"); sp.add_argument("file", nargs="?"); sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("link", help="map a note or folder to an existing page/folder")
    sp.add_argument("path"); sp.add_argument("ref", metavar="url-or-id")
    sp.add_argument("--no-pull", action="store_true",
                    help="don't fetch the page right after linking (pages only)")
    sp.set_defaults(fn=cmd_link, kind=None)

    # Retained so existing muscle memory and scripts keep working; `link` now detects
    # folders on its own, from the URL or by probing the id.
    sp = sub.add_parser("link-folder", help="alias for `link`, forced to folder")
    sp.add_argument("path"); sp.add_argument("ref", metavar="url-or-id")
    sp.set_defaults(fn=cmd_link, kind="folder", no_pull=True)

    sp = sub.add_parser("find", help="search Confluence by title")
    sp.add_argument("query"); sp.add_argument("--space", default=None)
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(fn=cmd_find)

    sp = sub.add_parser("pull"); sp.add_argument("file", nargs="?")
    sp.add_argument("--all", action="store_true"); sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_pull)

    sp = sub.add_parser("push"); sp.add_argument("file")
    sp.add_argument("-m", "--message", default=None); sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_push)

    sp = sub.add_parser("rebaseline"); sp.add_argument("--check", action="store_true")
    sp.set_defaults(fn=cmd_rebaseline)

    sp = sub.add_parser("create-page"); sp.add_argument("file")
    sp.add_argument("--parent", default=None); sp.add_argument("--space", default=None)
    sp.add_argument("--title", default=None); sp.add_argument("-m", "--message", default=None)
    sp.set_defaults(fn=cmd_create_page)

    sp = sub.add_parser("create-folder"); sp.add_argument("folder")
    sp.add_argument("--parent", default=None); sp.add_argument("--space", default=None)
    sp.add_argument("--title", default=None)
    sp.set_defaults(fn=cmd_create_folder)

    sp = sub.add_parser("scaffold"); sp.add_argument("spec")
    sp.add_argument("--parent", default=None); sp.add_argument("--space", default=None)
    sp.add_argument("-m", "--message", default=None)
    sp.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="override a spec variable, e.g. --set key=PT-1947 "
                         "--set teams=Charting,L&D Rx (repeatable)")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_scaffold)

    sp = sub.add_parser("users"); sp.add_argument("query")
    sp.add_argument("--add", action="store_true"); sp.set_defaults(fn=cmd_users)

    args = p.parse_args()
    if args.cmd == "pull" and not args.all and not args.file:
        p.error("pull needs a file or --all")
    args.fn(args)


if __name__ == "__main__":
    main()
