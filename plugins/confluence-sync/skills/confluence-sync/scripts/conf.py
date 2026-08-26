#!/usr/bin/env python3
"""
conf.py - Git-like sync between local Markdown files and Confluence Cloud.

Commands:
  status       [file]              Compare local files vs remote versions
  pull         <file|--all>        Download remote page(s) -> markdown (conflict-safe)
  push         <file> -m "msg"     Upload local markdown -> Confluence (optimistic lock)
  link         <file> <pageId>     Map a local file to an existing Confluence page
  link-folder  <folder> <folderId> Map a local folder to an existing Confluence folder
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

Dependencies: requests, markdown, markdownify, pyyaml   (pip install -r requirements.txt)
Optional: java + plantuml.jar in .confsync/ for PlantUML rendering.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import requests
    import yaml
    import markdown as md_lib
    from markdownify import markdownify as html_to_md
except ImportError as e:
    sys.exit(f"Missing dependency: {e.name}. Run: pip install requests markdown markdownify pyyaml")

# ---------------------------------------------------------------- config

def find_vault_root(start: Path) -> Path:
    """Walk up from start until a .confsync dir is found; else use start."""
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".confsync").is_dir():
            return parent
    return p


VAULT = find_vault_root(Path.cwd())
STATE_DIR = VAULT / ".confsync"
MAPPING_FILE = STATE_DIR / "mapping.json"
FOLDERS_FILE = STATE_DIR / "folders.json"
CONFIG_FILE = STATE_DIR / "config.json"
USERS_FILE = STATE_DIR / "users.json"
PLANTUML_JAR = STATE_DIR / "plantuml.jar"


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_config():
    cfg = load_json(CONFIG_FILE, {})
    base = os.environ.get("CONFLUENCE_BASE_URL") or cfg.get("base_url")
    email = os.environ.get("CONFLUENCE_EMAIL") or cfg.get("email")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not (base and email and token):
        sys.exit(
            "Missing credentials. Set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL and "
            "CONFLUENCE_API_TOKEN env vars (token: id.atlassian.com > Security > API tokens)."
        )
    cfg["base_url"] = base.rstrip("/")
    cfg["email"] = email
    cfg["token"] = token
    cfg.setdefault("jira_project_keys", [])
    return cfg


def api(cfg):
    s = requests.Session()
    s.auth = (cfg["email"], cfg["token"])
    s.headers.update({"Accept": "application/json"})
    return s


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# Marks a mapping entry whose `hash` covers the body only. Entries without it were
# written by <=0.3.0 (whole-file hash) and need `conf.py rebaseline` once.
HASH_ALGO = "body1"


def body_hash(text: str) -> str:
    """Hash the markdown body, ignoring YAML frontmatter.

    Push strips frontmatter before upload (see cmd_push), so frontmatter is by
    definition not push-relevant. Hashing it made every note read "local changes"
    the moment Obsidian's Properties panel reformatted the YAML (it writes block
    sequences at 2-space indent and double quotes, PyYAML writes them at zero
    indent with single quotes, so the two never agree). That stuck-dirty flag also
    poisoned the pull conflict check, turning clean pulls into spurious CONFLICTs.

    Callers reaching this via read_text() already get universal-newline translation
    (CRLF -> LF), but the normalization is repeated here so the function is correct
    for any caller, including one passing raw bytes decoded elsewhere.
    """
    body = split_frontmatter(text)[1]
    return sha256(body.replace("\r\n", "\n").replace("\r", "\n").strip())


def local_body_hash(path: Path) -> str:
    return body_hash(path.read_text(encoding="utf-8"))


def is_legacy(entry: dict) -> bool:
    """True for entries still carrying a whole-file hash from <=0.3.0."""
    return entry.get("hash_algo") != HASH_ALGO


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(VAULT))


# ---------------------------------------------------------------- REST helpers

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


# ---------------------------------------------------------------- frontmatter (Obsidian properties)

# Keys confsync owns end-to-end: rewritten from Confluence metadata on every link/pull/push.
# Any other frontmatter key already on the note (manual properties) is left untouched.
CONFSYNC_FM_KEYS = (
    "title", "page_id", "confluence_version", "parent_page_id", "confluence_space",
    "confluence_url", "up", "last_modified", "author",
)

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def split_frontmatter(text: str):
    """(frontmatter_dict, body) - frontmatter_dict is {} if the file has none."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end():]


def render_frontmatter(fm: dict) -> str:
    if not fm:
        return ""
    dumped = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{dumped}---\n\n"


def read_local_frontmatter(path: Path) -> dict:
    if not path.exists():
        return {}
    fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return fm


def apply_frontmatter(body_md: str, existing_fm: dict, updates: dict) -> str:
    """Rewrite the confsync-owned keys, keep manual keys, then re-attach the body.

    A key present in CONFSYNC_FM_KEYS but absent from `updates` (e.g. no parent page,
    so no `up`) is dropped rather than left stale.
    """
    manual = {k: v for k, v in existing_fm.items() if k not in CONFSYNC_FM_KEYS}
    merged = {k: updates[k] for k in CONFSYNC_FM_KEYS if k in updates}
    merged.update(manual)
    return render_frontmatter(merged) + body_md.lstrip("\n")


def build_confluence_frontmatter(cfg, mapping: dict, meta: dict) -> dict:
    """Human-readable fields derived from a v2 API page payload (meta/body/put response)."""
    fields = {"title": meta["title"], "page_id": str(meta["id"])}

    version = meta.get("version") or {}
    if version.get("number") is not None:
        fields["confluence_version"] = version["number"]

    parent_id = meta.get("parentId")
    if parent_id:
        fields["parent_page_id"] = str(parent_id)
        for rel_path, entry in mapping.items():
            if str(entry.get("page_id")) == str(parent_id):
                fields["up"] = f"[[{Path(rel_path).stem}]]"
                break

    # A page parented by a *folder* has no parent note to link, and Obsidian wikilinks
    # can only target notes - so scaffold records an anchor note per entry and `up` falls
    # back to it. Persisted in mapping.json rather than recomputed from Confluence
    # ancestry because the anchor (a project's Read Me) is typically a *sibling* of the
    # folders, never an ancestor, so ancestry can never find it.
    if "up" not in fields:
        own = next((e for e in mapping.values() if str(e.get("page_id")) == str(meta["id"])), None)
        if own and own.get("up_note"):
            fields["up"] = f"[[{own['up_note']}]]"

    webui = (meta.get("_links") or {}).get("webui", "")
    space_match = re.match(r"/spaces/([^/]+)/pages", webui)
    if space_match:
        fields["confluence_space"] = space_match.group(1)
    if webui:
        fields["confluence_url"] = cfg["base_url"] + "/wiki" + webui

    created = version.get("createdAt")
    if created:
        fields["last_modified"] = created[:10]  # YYYY-MM-DD, renders as a date property

    author_id = version.get("authorId")
    if author_id:
        users = load_json(USERS_FILE, {})
        by_id = {v["account_id"]: k for k, v in users.items()}
        fields["author"] = by_id.get(author_id, author_id)

    return fields


# ---------------------------------------------------------------- transforms md -> storage

JIRA_FENCE_RE = re.compile(r"```jira-issue\n(.*?)```", re.DOTALL)
DIAGRAM_FENCE_RE = re.compile(r"```(plantuml|mermaid)\n(.*?)```", re.DOTALL)
MENTION_RE = re.compile(r"@\[([^\]]+)\]|@([A-Za-z0-9_.-]+)")

# Collapsible "expand" section title per diagram language - source always goes here,
# regardless of whether an image could also be rendered (PlantUML titles matches the
# earlier confsync convention so pages already pushed still round-trip on pull).
DIAGRAM_TITLES = {
    "plantuml": "PlantUML source (confsync)",
    "mermaid": "Mermaid source (confsync)",
}
DIAGRAM_LANG_BY_TITLE = {title: lang for lang, title in DIAGRAM_TITLES.items()}


def transform_jira(md_text: str, cfg) -> str:
    """jira-issue fences and bare issue keys -> plain links (Confluence renders smart links)."""
    base = cfg["base_url"]

    def fence_repl(m):
        keys = [k.strip() for k in m.group(1).strip().splitlines() if k.strip()]
        return "\n".join(f"[{k}]({base}/browse/{k})" for k in keys)

    md_text = JIRA_FENCE_RE.sub(fence_repl, md_text)

    keys = cfg.get("jira_project_keys") or []
    if keys:
        bare = re.compile(
            r"(?<![\w/\[])((?:" + "|".join(map(re.escape, keys)) + r")-\d+)(?![\w\]])"
        )
        md_text = bare.sub(lambda m: f"[{m.group(1)}]({base}/browse/{m.group(1)})", md_text)
    return md_text


def render_diagram_blocks(md_text: str, cfg, s, page_id):
    """Extract ```plantuml/```mermaid fences, replace with placeholder tokens.

    PlantUML also renders a PNG (uploaded as an attachment) when java + plantuml.jar are
    available locally; Mermaid has no local renderer, so it's always text-only. Either
    way the raw source always goes into the returned block info - it always ends up in a
    collapsible section in storage HTML (see inject_diagram_storage), image or not.

    Returns (md_text, blocks) where blocks maps token -> {lang, source, image_filename}.
    """
    found = DIAGRAM_FENCE_RE.findall(md_text)
    if not found:
        return md_text, {}

    have_plantuml_renderer = PLANTUML_JAR.exists()
    blocks = {}
    for i, (lang, raw_src) in enumerate(found):
        token = f"CONFSYNCDIAGRAM{i}"
        src = raw_src.strip()
        image_filename = None
        if lang == "plantuml" and have_plantuml_renderer:
            with tempfile.TemporaryDirectory() as tmp:
                puml = Path(tmp) / f"diagram_{page_id}_{i}.puml"
                puml.write_text(src if "@startuml" in src else f"@startuml\n{src}\n@enduml\n",
                                encoding="utf-8")
                subprocess.run(
                    ["java", "-jar", str(PLANTUML_JAR), "-tpng", str(puml)],
                    check=True, capture_output=True,
                )
                image_filename = upload_attachment(cfg, s, page_id, puml.with_suffix(".png"))
        blocks[token] = {"lang": lang, "source": src, "image_filename": image_filename}
        md_text = md_text.replace(f"```{lang}\n{raw_src}```", f"\n{token}\n", 1)
    return md_text, blocks


def inject_diagram_storage(html: str, blocks) -> str:
    for token, info in blocks.items():
        expand = (
            f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">{DIAGRAM_TITLES[info["lang"]]}</ac:parameter>'
            f'<ac:rich-text-body><ac:structured-macro ac:name="code">'
            f'<ac:plain-text-body><![CDATA[{info["source"]}]]></ac:plain-text-body>'
            f"</ac:structured-macro></ac:rich-text-body></ac:structured-macro>"
        )
        if info["image_filename"]:
            block = (
                f'<ac:image><ri:attachment ri:filename="{info["image_filename"]}"/></ac:image>'
                + expand
            )
        else:
            block = expand
        html = re.sub(rf"<p>\s*{token}\s*</p>|{token}", block, html, count=1)
    return html


def transform_mentions(html: str) -> str:
    """@alias or @[Full Name] -> Confluence mention (needs users.json)."""
    users = load_json(USERS_FILE, {})
    unknown = []

    def repl(m):
        alias = (m.group(1) or m.group(2)).strip()
        entry = users.get(alias) or users.get(alias.lower())
        if not entry:
            unknown.append(alias)
            return m.group(0)
        return (
            f'<ac:link><ri:user ri:account-id="{entry["account_id"]}"/></ac:link>'
        )

    html = MENTION_RE.sub(repl, html)
    if unknown:
        print(f"  ! Unknown mention alias(es), left as text: {sorted(set(unknown))}"
              f"\n    Add them to {USERS_FILE} (use: conf.py users <name>)")
    return html


def md_to_storage(md_text: str, cfg, s, page_id) -> str:
    md_text = transform_jira(md_text, cfg)
    md_text, diagrams = render_diagram_blocks(md_text, cfg, s, page_id)
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    html = inject_diagram_storage(html, diagrams)
    html = transform_mentions(html)
    return html


# ---------------------------------------------------------------- transforms storage -> md

def storage_to_md(html: str) -> str:
    users = load_json(USERS_FILE, {})
    by_id = {v["account_id"]: k for k, v in users.items()}

    # mentions -> @alias (or @account_id if unknown)
    def mention_back(m):
        acc = m.group(1)
        return f"@{by_id.get(acc, acc)}"

    html = re.sub(
        r'<ac:link><ri:user ri:account-id="([^"]+)"\s*/></ac:link>', mention_back, html
    )

    # confsync diagram expand blocks -> fences (drop the rendered image, if any - keeping
    # the source is the point; a plain fence is simply "a section in the text" once it's
    # markdown, there's no "collapsed" state outside Confluence)
    def diagram_back(m):
        lang = DIAGRAM_LANG_BY_TITLE[m.group(1)]
        return f"\n```{lang}\n{m.group(2).strip()}\n```\n"

    title_alt = "|".join(re.escape(t) for t in DIAGRAM_TITLES.values())
    html = re.sub(
        r'(?:<ac:image>.*?</ac:image>\s*)?<ac:structured-macro ac:name="expand">.*?'
        rf'<ac:parameter ac:name="title">({title_alt})</ac:parameter>.*?'
        r"<!\[CDATA\[(.*?)\]\]>.*?</ac:structured-macro>",
        diagram_back, html, flags=re.DOTALL,
    )

    text = html_to_md(html, heading_style="ATX", bullets="-")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# ---------------------------------------------------------------- commands

def cmd_status(args):
    cfg = get_config()
    s = api(cfg)
    mapping = load_json(MAPPING_FILE, {})
    # Normalize like pull/push do - mapping keys are OS-native relative paths, so a
    # forward-slash argument on Windows would otherwise never match and report "not linked".
    targets = [rel(Path(args.file))] if args.file else sorted(mapping.keys())
    if not targets:
        print("No files linked yet. Use: conf.py link <file> <pageId>")
        return
    legacy_seen = False
    for f in targets:
        entry = mapping.get(f)
        if not entry:
            print(f"{f}: not linked")
            continue
        local = VAULT / f
        local_changed = not local.exists() or local_body_hash(local) != entry["hash"]
        meta = get_page_meta(cfg, s, entry["page_id"])
        remote_v = meta["version"]["number"]
        remote_changed = remote_v != entry["version"]
        state = {
            (False, False): "in sync",
            (True, False): "local changes (push needed)",
            (False, True): f"remote moved to v{remote_v} (pull needed)",
            (True, True): f"CONFLICT: local changes AND remote moved to v{remote_v}",
        }[(local_changed, remote_changed)]
        if is_legacy(entry):
            state += "  [legacy whole-file hash, run 'conf.py rebaseline']"
            legacy_seen = True
        print(f"{f}: v{entry['version']} local | v{remote_v} remote -> {state}")

    if legacy_seen:
        print("\nSome entries still use the pre-0.4.0 whole-file hash, which counted"
              "\nfrontmatter reformatting as a local change. Review any 'push needed'"
              "\nabove, then run 'conf.py rebaseline' to switch them to body-only.")


def cmd_link(args):
    cfg = get_config()
    s = api(cfg)
    meta = get_page_meta(cfg, s, args.page_id)
    mapping = load_json(MAPPING_FILE, {})
    f = rel(Path(args.file))
    local = VAULT / f
    mapping[f] = {
        "page_id": args.page_id,
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
    print(f"Linked {f} -> \"{meta['title']}\" (page {args.page_id}, remote v{meta['version']['number']})."
          f"\nRun 'conf.py pull {f}' to fetch it.")


def cmd_link_folder(args):
    cfg = get_config()
    s = api(cfg)
    meta = get_folder_meta(cfg, s, args.folder_id)
    local = Path(args.folder)
    if not local.is_dir():
        sys.exit(f"{local} is not an existing local folder (create it first, then link it)")
    folders = load_json(FOLDERS_FILE, {})
    f = rel(local)
    folders[f] = {
        "folder_id": args.folder_id,
        "title": meta["title"],
        "parent_id": meta.get("parentId"),
    }
    save_json(FOLDERS_FILE, folders)
    print(f"Linked folder {f} -> \"{meta['title']}\" (folder {args.folder_id})."
          f"\nRun 'conf.py pull --all' to keep its name in sync with Confluence.")


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


def cmd_pull(args):
    cfg = get_config()
    s = api(cfg)
    if args.all:
        sync_folders(cfg, s)
    mapping = load_json(MAPPING_FILE, {})
    targets = sorted(mapping.keys()) if args.all else [rel(Path(args.file))]
    for f in targets:
        entry = mapping.get(f)
        if not entry:
            print(f"{f}: not linked, skipping")
            continue
        local = VAULT / f
        page = get_page_body(cfg, s, entry["page_id"])
        remote_v = page["version"]["number"]
        remote_md = storage_to_md(page["body"]["storage"]["value"])

        local_dirty = local.exists() and local_body_hash(local) != entry["hash"]
        fm_fields = build_confluence_frontmatter(cfg, mapping, page)
        existing_fm = read_local_frontmatter(local)

        if local_dirty and remote_v != entry["version"] and not args.force:
            side = local.with_suffix(".remote.md")
            side.write_text(apply_frontmatter(remote_md, existing_fm, fm_fields), encoding="utf-8")
            print(f"{f}: CONFLICT - local edits + remote v{remote_v}."
                  f"\n  Remote saved to {side.name}. Merge manually, then push."
                  f"\n  (or re-run pull --force to overwrite local)")
            continue

        final_text = apply_frontmatter(remote_md, existing_fm, fm_fields)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(final_text, encoding="utf-8")
        entry.update(version=remote_v, hash=body_hash(final_text),
                     hash_algo=HASH_ALGO, title=page["title"])
        save_json(MAPPING_FILE, mapping)
        print(f"{f}: pulled v{remote_v} (\"{page['title']}\")")


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


def cmd_rebaseline(args):
    """Migrate mapping entries from the <=0.3.0 whole-file hash to the body-only hash.

    Deliberately a separate, explicit command rather than a silent migration on first
    run: a file could hold a genuine un-pushed local edit made before the upgrade, and
    silently re-baselining would bury it. --check reports without writing.
    """
    mapping = load_json(MAPPING_FILE, {})
    if not mapping:
        print("No files linked yet.")
        return

    stale, migrated, missing = [], [], []
    for f, entry in sorted(mapping.items()):
        if not is_legacy(entry):
            continue
        local = VAULT / f
        if not local.exists():
            missing.append(f)
            continue
        new_hash = local_body_hash(local)
        if args.check:
            state = "unchanged" if new_hash == entry["hash"] else "hash will change"
            stale.append(f"  {f}  ({state})")
            continue
        entry["hash"] = new_hash
        entry["hash_algo"] = HASH_ALGO
        migrated.append(f)

    if args.check:
        print("\n".join(stale) if stale else "Nothing to migrate.")
        for f in missing:
            print(f"  {f}  (local file missing, skipped)")
        print(f"\n{len(stale)} entr{'y' if len(stale) == 1 else 'ies'} would be migrated."
              "\nRe-run without --check to apply.")
        return

    for f in missing:
        print(f"{f}: local file missing, skipped")
    if not migrated:
        print("Nothing to migrate. All entries already use the body-only hash.")
        return
    save_json(MAPPING_FILE, mapping)
    for f in migrated:
        print(f"rebaselined: {f}")
    print(f"\n{len(migrated)} entr{'y' if len(migrated) == 1 else 'ies'} migrated to "
          f"body-only hashing. Confluence was not contacted and no note was modified.")


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


# Characters Confluence happily accepts in a title but Windows rejects in a filename.
ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(title: str) -> str:
    """Local file/dir name for a Confluence title (titles allow chars Windows does not)."""
    cleaned = ILLEGAL_NAME_CHARS.sub("-", title).rstrip(". ")
    return cleaned or "untitled"


def load_spec(path: Path) -> dict:
    """A scaffold spec is YAML or JSON - yaml.safe_load reads both."""
    if not path.exists():
        sys.exit(f"Spec file not found: {path}")
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "tree" not in spec:
        sys.exit("Spec must be a mapping with a top-level 'tree' key.")
    return spec


# ---------------------------------------------------------------- spec templating

VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def substitute(text, variables: dict):
    """Replace {placeholders} from `variables`; an unknown placeholder is left as-is.

    Left as-is rather than blanked so a typo shows up in the dry-run output as a literal
    {typo} instead of silently producing a half-empty title.
    """
    if not isinstance(text, str):
        return text
    return VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), text)


def render_title(node, variables: dict, subst_team, prefix_team):
    """Build a node's final Confluence title.

    Convention: "{key} - {title}", or "{key} - {team} - {title}" inside a team subtree.
    `raw: true` opts out entirely (still substituted, just not prefixed) - that is how a
    node like CLAUDE.md keeps its exact name.

    The two team arguments differ for exactly one node: the repeating wrapper itself,
    whose title is typically "{team}". It needs the substitution but not the prefix
    segment, or it would render as "KEY - Charting - Charting".
    """
    title = substitute(node.get("title", ""), {**variables, "team": subst_team or ""})
    if not title:
        sys.exit(f"Every node needs a 'title' (offending node: {node!r}).")
    if node.get("raw"):
        return title
    return " - ".join(p for p in (variables.get("key"), prefix_team, title) if p)


def expand_tree(nodes, variables: dict, team=None):
    """Resolve variables and expand `repeat_per_team` into a concrete tree.

    A `repeat_per_team` node is emitted once per team, and every node beneath it picks up
    the team segment in its title - Confluence enforces unique page titles per space, so
    two teams sharing a leaf title like "Scope definition" would otherwise collide on
    creation. The repeating node's own title carries the team already (it is typically
    "{team}"), so it does not get the segment twice.

    With `teams: []` the node collapses and splices its children into its parent, which
    is what makes single-team mode read exactly like the tree as written.

    `when: single_team` / `when: multi_team` drops a node (and its whole subtree) in the
    other mode. It exists because collapsing splices into the *immediate* parent, so a
    node that needs to sit at a different depth once the team wrapper disappears cannot
    be expressed by placement alone - it has to be written twice and gated. project.yaml
    uses it for the Dev folder: per-team inside "Product Owner" for a multi-team project,
    a single project-level folder otherwise.
    """
    out = []
    for node in nodes or []:
        kind = node.get("type", "page")
        if kind not in ("page", "folder"):
            sys.exit(f"Unknown node type {kind!r} (expected 'page' or 'folder').")

        # `when` gates a node on team mode (see docstring). Checked before repeat_per_team
        # so a gated-out subtree is never expanded at all.
        when = node.get("when")
        if when not in (None, "single_team", "multi_team"):
            sys.exit(f"Unknown when {when!r} on node {node.get('title')!r} "
                     f"(expected 'single_team' or 'multi_team').")
        if when and (when == "multi_team") != bool(variables.get("teams")):
            continue

        if node.get("repeat_per_team"):
            teams = variables.get("teams") or []
            if not teams:
                out.extend(expand_tree(node.get("children"), variables, team))
                continue
            for t in teams:
                out.append(render_node(node, variables, self_team=None, child_team=t))
            continue

        out.append(render_node(node, variables, self_team=team, child_team=team))
    return out


def render_node(node, variables: dict, self_team, child_team):
    kind = node.get("type", "page")
    rendered = {
        "type": kind,
        "title": render_title(node, variables,
                              subst_team=child_team if node.get("repeat_per_team") else self_team,
                              prefix_team=None if node.get("repeat_per_team") else self_team),
        "target": node.get("target", "both"),
    }
    if rendered["target"] not in ("both", "obsidian"):
        sys.exit(f"Unknown target {rendered['target']!r} on {rendered['title']!r} "
                 f"(expected 'both' or 'obsidian').")
    if node.get("name"):
        rendered["name"] = substitute(node["name"], {**variables, "team": child_team or ""})
    if node.get("body"):
        rendered["body"] = substitute(node["body"], {**variables, "team": child_team or ""})
    if node.get("anchor"):
        rendered["anchor"] = True
    if node.get("children"):
        rendered["children"] = expand_tree(node["children"], variables, child_team)
    return rendered


def local_path_for(node, base_dir: Path) -> Path:
    """Vault path mirroring a node: folders become directories, pages become <name>.md."""
    name = node.get("name") or safe_name(node["title"])
    if node["type"] == "folder":
        return base_dir / name
    return base_dir / (name if name.endswith(".md") else f"{name}.md")


def walk_spec(nodes, base_dir: Path, depth=0):
    """Yield (node, local_path, depth) depth-first, parents before their children."""
    for node in nodes or []:
        local = local_path_for(node, base_dir)
        yield node, local, depth
        if node["type"] == "folder":
            yield from walk_spec(node.get("children"), local, depth + 1)
        elif node.get("children"):
            sys.exit(f"Page {node['title']!r} has children - only folders can nest. "
                     f"Make it a folder, or move the children up.")


def seed_note(local: Path, body: str, extra_fm: dict):
    """Write a note that does not exist yet, with the spec's frontmatter keys on top.

    Those keys (typically `tags`) sit outside CONFSYNC_FM_KEYS, so every later pull/push
    preserves them as manual properties. An existing file is never touched - a note you
    have already written beats the template.
    """
    if local.exists():
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(render_frontmatter(extra_fm) + (body or ""), encoding="utf-8")
    return True


def cmd_scaffold(args):
    """Create a whole folder/page tree in Confluence and mirror it into the vault.

    Idempotent by design: a node whose local path is already in mapping.json/folders.json
    is skipped and its existing id is reused as the parent for its children, so a run
    interrupted halfway (network, permissions, a title clash) can simply be re-run.
    """
    cfg = get_config()
    s = api(cfg)
    spec = load_spec(Path(args.spec))

    variables = dict(spec.get("variables") or {})
    for override in args.set or []:
        if "=" not in override:
            sys.exit(f"--set expects key=value, got {override!r}")
        k, v = override.split("=", 1)
        variables[k] = [p.strip() for p in v.split(",") if p.strip()] if k == "teams" else v

    parent = args.parent or substitute(spec.get("parent"), variables)
    space = args.space or substitute(spec.get("space"), variables)
    space_id, root_parent_id = resolve_target(cfg, s, parent, space)

    base = substitute(spec.get("base"), variables)
    base_dir = (VAULT / base) if base else VAULT
    extra_fm = {k: substitute(v, variables) if isinstance(v, str) else
                [substitute(i, variables) for i in v] if isinstance(v, list) else v
                for k, v in (spec.get("frontmatter") or {}).items()}

    mapping = load_json(MAPPING_FILE, {})
    folders = load_json(FOLDERS_FILE, {})

    tree = expand_tree(spec["tree"], variables)
    plan = list(walk_spec(tree, base_dir))
    if not plan:
        sys.exit("Spec has an empty tree - nothing to create.")

    # The anchor is the note every other note points at with frontmatter `up`. Obsidian
    # wikilinks can only target notes, and in a folders-only tree a page's parent is
    # almost always a folder, which has no note behind it - so `up` would otherwise be
    # empty on nearly every page. Defaults to the first synced page in the tree (the
    # project's Read Me); mark another node `anchor: true` to override.
    anchor = next((n for n, _, _ in plan
                   if n["type"] == "page" and n.get("anchor") and n["target"] == "both"), None)
    if anchor is None:
        anchor = next((n for n, _, _ in plan
                       if n["type"] == "page" and n["target"] == "both"), None)
    anchor_stem = None
    if anchor is not None:
        anchor_stem = local_path_for(anchor, base_dir).stem

    teams = variables.get("teams") or []
    where = f"space {space_id}" + (f", under {root_parent_id}" if root_parent_id else ", at space root")
    print(f"Scaffolding {len(plan)} node(s) into {where}")
    if teams:
        print(f"teams: {', '.join(teams)}")
    if anchor_stem:
        print(f"up anchor: [[{anchor_stem}]]")
    print()

    # local dir -> confluence id, so each child can find the parent created moments ago
    parent_ids = {base_dir.resolve(): root_parent_id}
    created = skipped = local_only = 0

    for node, local, depth in plan:
        kind, title, target = node["type"], node["title"], node["target"]
        f = rel(local)
        indent = "  " * depth

        if target == "obsidian":
            if args.dry_run:
                print(f"{indent}+ {local.name}  [obsidian only]")
            else:
                wrote = seed_note(local, node.get("body", ""), extra_fm) if kind == "page" \
                    else (local.mkdir(parents=True, exist_ok=True) or True)
                print(f"{indent}{'+' if wrote else '-'} {local.name}  "
                      f"[obsidian only{'' if wrote else ', exists'}]")
            local_only += 1
            continue

        store = folders if kind == "folder" else mapping
        id_key = "folder_id" if kind == "folder" else "page_id"
        existing = store.get(f)
        if existing:
            print(f"{indent}- {title}  [exists, {id_key}={existing[id_key]}]")
            parent_ids[local.resolve()] = existing[id_key]
            skipped += 1
            continue

        if args.dry_run:
            print(f"{indent}+ {title}  [{kind}]")
            parent_ids[local.resolve()] = f"<{kind}:{title}>"
            created += 1
            continue

        node_parent = parent_ids.get(local.parent.resolve(), root_parent_id)
        if kind == "folder":
            entry = create_folder_here(cfg, s, space_id, title, node_parent, local, folders)
            parent_ids[local.resolve()] = entry["folder_id"]
        else:
            seed_note(local, node.get("body", ""), extra_fm)
            up = anchor_stem if anchor_stem and local_path_for(node, base_dir) != \
                local_path_for(anchor, base_dir) else None
            entry = create_page_here(cfg, s, space_id, title, node_parent, local, mapping,
                                     args.message or "Created from project template",
                                     up_note=up)
            parent_ids[local.resolve()] = entry["page_id"]
        print(f"{indent}+ {title}  [{kind} {parent_ids[local.resolve()]}]")
        created += 1

    verb = "would create" if args.dry_run else "created"
    print(f"\n{verb} {created} in Confluence, {local_only} Obsidian-only, "
          f"skipped {skipped} already-linked.")
    if not args.dry_run and created:
        print("Run 'conf.py status' to confirm, or edit the notes and 'push' them.")


def cmd_users(args):
    cfg = get_config()
    s = api(cfg)
    r = s.get(f"{cfg['base_url']}/wiki/rest/api/search/user",
              params={"cql": f'user.fullname ~ "{args.query}"', "limit": 10})
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        print("No users found.")
        return
    users = load_json(USERS_FILE, {})
    for res in results:
        u = res.get("user", {})
        name, acc = u.get("publicName") or u.get("displayName"), u.get("accountId")
        print(f"  {name}  ->  {acc}")
        if args.add:
            alias = name.split()[0].lower()
            users[alias] = {"account_id": acc, "display_name": name}
            print(f"    added as alias @{alias}")
    if args.add:
        save_json(USERS_FILE, users)


def main():
    p = argparse.ArgumentParser(description="Git-like Confluence sync for a markdown vault")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status"); sp.add_argument("file", nargs="?"); sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("link"); sp.add_argument("file"); sp.add_argument("page_id")
    sp.set_defaults(fn=cmd_link)

    sp = sub.add_parser("link-folder"); sp.add_argument("folder"); sp.add_argument("folder_id")
    sp.set_defaults(fn=cmd_link_folder)

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
