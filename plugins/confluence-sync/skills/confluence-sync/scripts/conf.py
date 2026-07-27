#!/usr/bin/env python3
"""
conf.py - Git-like sync between local Markdown files and Confluence Cloud.

Commands:
  status  [file]              Compare local files vs remote versions
  pull    <file|--all>        Download remote page(s) -> markdown (conflict-safe)
  push    <file> -m "msg"     Upload local markdown -> Confluence (optimistic lock)
  link    <file> <pageId>     Map a local file to an existing Confluence page
  users   <query>             Search Confluence users (to populate users.json)

Auth (env vars):
  CONFLUENCE_BASE_URL   e.g. https://medfar.atlassian.net
  CONFLUENCE_EMAIL      your Atlassian account email
  CONFLUENCE_API_TOKEN  API token from https://id.atlassian.com/manage-profile/security/api-tokens

State lives in <vault>/.confsync/:
  config.json    { "base_url": "...", "jira_project_keys": ["RD","MYLE",...] }
  mapping.json   { "<relative/path.md>": {"page_id": "...", "version": N, "hash": "sha256..."} }
  users.json     { "alias": {"account_id": "...", "display_name": "..."} }

mapping.json remains the source of truth for the optimistic-lock version/hash. Every
link/pull/push also mirrors human-readable metadata (page_id, confluence_url, author,
last_modified, ...) into each note's YAML frontmatter for visibility in Obsidian's
Properties panel - see CONFSYNC_FM_KEYS. Those keys are regenerated on every sync; don't
hand-edit them.

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


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(VAULT))


# ---------------------------------------------------------------- REST helpers

def get_page_meta(cfg, s, page_id):
    """Metadata only - v2 API returns version without body unless body-format is asked."""
    r = s.get(f"{cfg['base_url']}/wiki/api/v2/pages/{page_id}")
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
    "title", "page_id", "parent_page_id", "confluence_space",
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

    parent_id = meta.get("parentId")
    if parent_id:
        fields["parent_page_id"] = str(parent_id)
        for rel_path, entry in mapping.items():
            if str(entry.get("page_id")) == str(parent_id):
                fields["up"] = f"[[{Path(rel_path).stem}]]"
                break

    webui = (meta.get("_links") or {}).get("webui", "")
    space_match = re.match(r"/spaces/([^/]+)/pages", webui)
    if space_match:
        fields["confluence_space"] = space_match.group(1)
    if webui:
        fields["confluence_url"] = cfg["base_url"] + "/wiki" + webui

    version = meta.get("version") or {}
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
PLANTUML_FENCE_RE = re.compile(r"```plantuml\n(.*?)```", re.DOTALL)
MENTION_RE = re.compile(r"@\[([^\]]+)\]|@([A-Za-z0-9_.-]+)")


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


def render_plantuml_blocks(md_text: str, cfg, s, page_id):
    """Render ```plantuml fences to PNG, upload as attachments, replace with placeholders.

    Returns (md_text, attachments_map) where placeholders CONFSYNC-PUML-i are later
    swapped for <ac:image> + collapsed source in the storage HTML.
    """
    blocks = PLANTUML_FENCE_RE.findall(md_text)
    if not blocks:
        return md_text, {}

    have_renderer = PLANTUML_JAR.exists()
    attachments = {}
    for i, src in enumerate(blocks):
        token = f"CONFSYNCPUML{i}"
        if have_renderer:
            with tempfile.TemporaryDirectory() as tmp:
                puml = Path(tmp) / f"diagram_{page_id}_{i}.puml"
                puml.write_text(f"@startuml\n{src.strip()}\n@enduml\n"
                                if "@startuml" not in src else src, encoding="utf-8")
                subprocess.run(
                    ["java", "-jar", str(PLANTUML_JAR), "-tpng", str(puml)],
                    check=True, capture_output=True,
                )
                png = puml.with_suffix(".png")
                name = upload_attachment(cfg, s, page_id, png)
                attachments[token] = {"filename": name, "source": src.strip()}
        else:
            attachments[token] = {"filename": None, "source": src.strip()}
        md_text = md_text.replace(f"```plantuml\n{src}```", f"\n{token}\n", 1)
    return md_text, attachments


def inject_plantuml_storage(html: str, attachments) -> str:
    for token, info in attachments.items():
        if info["filename"]:
            block = (
                f'<ac:image><ri:attachment ri:filename="{info["filename"]}"/></ac:image>'
                f'<ac:structured-macro ac:name="expand">'
                f'<ac:parameter ac:name="title">PlantUML source (confsync)</ac:parameter>'
                f'<ac:rich-text-body><ac:structured-macro ac:name="code">'
                f'<ac:plain-text-body><![CDATA[{info["source"]}]]></ac:plain-text-body>'
                f"</ac:structured-macro></ac:rich-text-body></ac:structured-macro>"
            )
        else:  # no renderer available: keep source visible as a code block
            block = (
                f'<ac:structured-macro ac:name="code">'
                f'<ac:parameter ac:name="title">plantuml (not rendered - plantuml.jar missing)</ac:parameter>'
                f'<ac:plain-text-body><![CDATA[{info["source"]}]]></ac:plain-text-body>'
                f"</ac:structured-macro>"
            )
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
    md_text, puml = render_plantuml_blocks(md_text, cfg, s, page_id)
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    html = inject_plantuml_storage(html, puml)
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

    # confsync plantuml expand blocks -> fences (drop the rendered image)
    def puml_back(m):
        return f"\n```plantuml\n{m.group(1).strip()}\n```\n"

    html = re.sub(
        r'<ac:image>.*?</ac:image>\s*<ac:structured-macro ac:name="expand">.*?'
        r"PlantUML source \(confsync\).*?<!\[CDATA\[(.*?)\]\]>.*?</ac:structured-macro>",
        puml_back, html, flags=re.DOTALL,
    )

    text = html_to_md(html, heading_style="ATX", bullets="-")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# ---------------------------------------------------------------- commands

def cmd_status(args):
    cfg = get_config()
    s = api(cfg)
    mapping = load_json(MAPPING_FILE, {})
    targets = [args.file] if args.file else sorted(mapping.keys())
    if not targets:
        print("No files linked yet. Use: conf.py link <file> <pageId>")
        return
    for f in targets:
        entry = mapping.get(f)
        if not entry:
            print(f"{f}: not linked")
            continue
        local = VAULT / f
        local_changed = (
            not local.exists() or sha256(local.read_text(encoding="utf-8")) != entry["hash"]
        )
        meta = get_page_meta(cfg, s, entry["page_id"])
        remote_v = meta["version"]["number"]
        remote_changed = remote_v != entry["version"]
        state = {
            (False, False): "in sync",
            (True, False): "local changes (push needed)",
            (False, True): f"remote moved to v{remote_v} (pull needed)",
            (True, True): f"CONFLICT: local changes AND remote moved to v{remote_v}",
        }[(local_changed, remote_changed)]
        print(f"{f}: v{entry['version']} local | v{remote_v} remote -> {state}")


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
        "hash": sha256(local.read_text(encoding="utf-8")) if local.exists() else "",
    }

    if local.exists():
        existing_fm, body = split_frontmatter(local.read_text(encoding="utf-8"))
        fields = build_confluence_frontmatter(cfg, mapping, meta)
        final_text = apply_frontmatter(body, existing_fm, fields)
        local.write_text(final_text, encoding="utf-8")
        mapping[f]["hash"] = sha256(final_text)

    save_json(MAPPING_FILE, mapping)
    print(f"Linked {f} -> \"{meta['title']}\" (page {args.page_id}, remote v{meta['version']['number']})."
          f"\nRun 'conf.py pull {f}' to fetch it.")


def cmd_pull(args):
    cfg = get_config()
    s = api(cfg)
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

        local_dirty = local.exists() and sha256(local.read_text(encoding="utf-8")) != entry["hash"]
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
        entry.update(version=remote_v, hash=sha256(final_text), title=page["title"])
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

    entry.update(version=result["version"]["number"], hash=sha256(final_text))
    save_json(MAPPING_FILE, mapping)
    print(f"{f}: pushed as v{result['version']['number']} - \"{message}\"")


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

    sp = sub.add_parser("pull"); sp.add_argument("file", nargs="?")
    sp.add_argument("--all", action="store_true"); sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_pull)

    sp = sub.add_parser("push"); sp.add_argument("file")
    sp.add_argument("-m", "--message", default=None); sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_push)

    sp = sub.add_parser("users"); sp.add_argument("query")
    sp.add_argument("--add", action="store_true"); sp.set_defaults(fn=cmd_users)

    args = p.parse_args()
    if args.cmd == "pull" and not args.all and not args.file:
        p.error("pull needs a file or --all")
    args.fn(args)


if __name__ == "__main__":
    main()
