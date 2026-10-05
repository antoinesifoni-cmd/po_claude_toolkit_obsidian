#!/usr/bin/env python3
r"""
tasknote.py - the deterministic half of the task-note skill.

A task stays a Tasks plugin line: checkbox, dates, tags, Today and Overdue. When the user
asks for it, the task also gets a note to write in. The note is created from a template
through the Obsidian CLI, and a link to it goes in the task line, right before the Tasks
fields (📅 ➕ ⏫ and the others). Nothing else in the line changes.

Two ways in:
  single  the user calls the skill on a task line. Claudian gives the note and the line.
  batch   the user puts the keyword (#note) in tasks anywhere in the vault. end-my-day, or
          a request, picks them all up, and nothing happens before the user says yes.

Commands (run from the vault root, the folder that holds .obsidian/):
  scan                  batch: every task line in the vault that holds a rule's keyword
  scan NOTE LINE        single: that task line. LINE counts from 1, like the editor.
  scan NOTE FIRST-LAST  the task lines of a selection
                        Each scan writes .daily-note/run/task-note.json and prints the
                        items, with the ids that need a title from Claude: a text over
                        title_words words, or one with a tag past its start.
  check                 read the titles Claude wrote in task-titles.json and print what each
                        item gets: a new note, an existing one, or why it gets none. No change.
  apply [IDS]           create the notes with the Obsidian CLI, then put the links in the
                        task lines, after a backup. IDS, like 1,3, keeps only those items.

Why the CLI creates the notes and this script edits the lines: the user wants Obsidian to
create the notes, so the template, AutoDater and the other plugins see a normal creation.
No CLI command changes one line of a note, so the script does that part itself, the way
daynote.py writes the daily note: one read, one write, a backup first.

The CLI, as checked on Obsidian 1.13.7:
  - it always exits 0. An error only shows as output that starts with "Error"
  - `create` on a path that exists makes "Title 1.md" next to it, so the script checks
    first and never calls `create` on an existing note
  - it turns \n and \t in a value into a line break and a tab, with no escape. Titles,
    tags and links cannot hold a backslash, so no value the script sends can
  - from Git Bash, `obsidian` fails on commands with a colon, like property:set. From
    Python it is Obsidian.com, and it works

The task note never holds the task's status or dates. They stay in the line, so the two
cannot disagree. The user's template shows the task live with a Tasks query instead.

The rules (keyword, template, folder, link, properties) are the task_note key of the
plugin's config.json. Unlike daynote.py, this script reads them itself: applying a rule
must not depend on judgement.

Standard library only.
"""

import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from daynote import (ADDRESS, FENCE, STATE_DIR, Stop, frontmatter_end, join_eol, read_text,
                     split_eol)

CONFIG = Path(__file__).resolve().parent.parent / "config.json"
RUN_FILE = "task-note.json"         # written by scan, never by Claude
TITLES_FILE = "task-titles.json"    # written by Claude: {"titles": {"<id>": "<title>"}}
CLI_TIMEOUT = 30                    # seconds, for one CLI call
MAX_TITLE = 80                      # characters, so a path stays far from Windows' limit
DEFAULT_WORDS = 8                   # a cleaned task text this short is the title as is

# A task line: its start up to the checkbox (indent, quote, list marker, [ ]), then its
# text. Any status counts, done tasks too.
TASK = re.compile(r"^(\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+\[.\]\s+)(.*)$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONFLUENCE = re.compile(r"^confluence_url\s*:")

# The fields the Tasks plugin reads at the end of a task, emoji format. It reads them from
# the end backwards and stops at the first thing that is neither a field nor a tag, so a
# link must go before them, never after: after them, the task loses its dates.
FIELDS = (
    re.compile(r"\s+\^[A-Za-z0-9-]+$"),                                     # block link
    re.compile(r"\s*[🔺⏫🔼🔽⏬]️?$"),                                    # priority
    re.compile(r"\s*[📅📆🗓⏳⌛🛫➕✅❌]️?\s*\d{4}-\d{2}-\d{2}$"),         # dates
    re.compile(r"\s*🔁️?\s*[A-Za-z0-9, !]+$"),                         # recurrence
    re.compile(r"\s*🏁️?\s*[A-Za-z]+$"),                               # on completion
    re.compile(r"\s*⛔️?\s*[\w-]+(?:\s*,\s*[\w-]+)*$"),                 # depends on
    re.compile(r"\s*🆔️?\s*[\w-]+$"),                                  # id
)
END_TAG = re.compile(r"(?:^|\s+)#[^\s!@#$%^&*(),.?\":{}|<>]+$")   # a tag among the fields
TAG = re.compile(r"(?<!\S)#([\w/-]+)")          # a tag in the text: letters, digits, _ - /
LEADING_TAGS = re.compile(r"^(?:\s*#[\w/-]+)+\s*")

WIKILINK = re.compile(r"!?\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
# What a file name, or a name inside a [[link]], cannot hold.
FORBIDDEN = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
RESERVED = re.compile(r"^(?:con|prn|aux|nul|com\d|lpt\d)$", re.I)   # Windows device names


# ---------------------------------------------------------------- rules and files

def load_rules(path: Path = CONFIG) -> list:
    try:
        cfg = json.loads(read_text(path))
    except (OSError, ValueError) as e:
        raise Stop(f"The plugin's config.json could not be read ({e}).")
    rules = (cfg.get("task_note") or {}).get("rules") if isinstance(cfg, dict) else None
    if not isinstance(rules, list) or not rules:
        raise Stop("config.json has no task_note rules.")
    return [check_rule(r, n) for n, r in enumerate(rules, 1)]


def check_rule(r, n: int) -> dict:
    def bad(why):
        return Stop(f"task_note rule {n} in config.json: {why}.")
    if not isinstance(r, dict):
        raise bad("it is not an object")
    keyword = str(r.get("keyword") or "")
    if not re.fullmatch(r"#[\w/-]+", keyword):
        raise bad("keyword must be a tag, like #note")
    folder = str(r.get("folder") or "").replace("\\", "/").strip("/")
    if not folder or any(part in ("", ".", "..") or part.startswith(".")
                         for part in folder.split("/")):
        raise bad("folder must be a vault folder, like Tasks or Notes/Tasks")
    template = str(r.get("template") or "").strip()
    if not template:
        raise bad("template is missing")
    link = str(r.get("link") or "[[{title}]]")
    if not (link.startswith("[[") and link.endswith("]]") and "{title}" in link):
        raise bad("link must look like [[{title}]] or [[{title}|icon]]")
    words = r.get("title_words", DEFAULT_WORDS)
    if not isinstance(words, int) or isinstance(words, bool) or words < 1:
        raise bad("title_words must be a whole number, 1 or more")
    props = r.get("properties") or {}
    if not isinstance(props, dict):
        raise bad("properties must be an object")
    return {"keyword": keyword, "folder": folder, "template": template, "link": link,
            "alias": link[2:-2].split("|", 1)[1].strip() if "|" in link else "",
            "title_words": words, "properties": props,
            "kw": re.compile(r"(?<!\S)" + re.escape(keyword) + r"(?![\w/-])", re.I)}


def vault_root(root: Path):
    if not (root / ".obsidian").is_dir():
        raise Stop(f"Run this from the vault root: there is no .obsidian folder in {root}")


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        data = json.loads(read_text(path))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data):
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def note_rel(root: Path, rel: str) -> str:
    """A note path as the vault writes it: relative, with /, ending in .md."""
    p = Path(str(rel).strip().strip('"'))
    if p.is_absolute():
        try:
            p = p.relative_to(root)
        except ValueError:
            raise Stop(f"{rel} is not in this vault.")
    rel = p.as_posix()
    while rel.startswith("./"):
        rel = rel[2:]
    if ".." in rel.split("/") or not rel.lower().endswith(".md"):
        raise Stop(f"{rel} is not a note of this vault.")
    if not (root / rel).is_file():
        raise Stop(f"No note at {rel}.")
    return rel


def template_paths(root: Path):
    """The template folder and the daily note template, from Obsidian's settings: a keyword
    there belongs to a template, not to a task."""
    folders, files = set(), set()
    templates = read_json(root / ".obsidian" / "templates.json") or {}
    folder = str(templates.get("folder") or "").strip("/")
    if folder:
        folders.add(folder)
    daily = read_json(root / ".obsidian" / "daily-notes.json") or {}
    template = str(daily.get("template") or "").strip("/")
    if template:
        files.add(template if template.endswith(".md") else template + ".md")
    return folders, files


# ---------------------------------------------------------------- reading a note

def note_lines(path: Path):
    """(raw text, lines, end of line, bom), the way daynote.py reads a note."""
    raw = read_text(path)
    text, eol, bom = split_eol(raw)
    return raw, text.split("\n"), eol, bom


def synced(lines: list) -> bool:
    """A note linked to a Confluence page: a [[link]] in it is lost on the next pull."""
    return any(CONFLUENCE.match(line) for line in lines[:frontmatter_end(lines)])


def body_lines(lines: list):
    """(index, heading above it) for each line outside the properties and code blocks."""
    in_code, heading = False, ""
    for i in range(frontmatter_end(lines), len(lines)):
        if FENCE.match(lines[i]):
            in_code = not in_code
            continue
        if in_code:
            continue
        h = HEADING.match(lines[i])
        if h:
            heading = h.group(1)
            continue
        yield i, heading


def vault_index(root: Path) -> dict:
    """Every note of the vault by its name, lower-cased. A [[link]] by name alone is right
    only when no other note has that name. Dot folders are not part of the vault."""
    index = {}
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        index.setdefault(p.stem.casefold(), []).append(rel.as_posix())
    for paths in index.values():
        paths.sort()
    return index


def link_target(rel: str, index: dict) -> str:
    """How a link names a note: by its name when no other note has it, else by its path."""
    stem = Path(rel).stem
    others = [p for p in index.get(stem.casefold(), []) if p.casefold() != rel.casefold()]
    return rel[:-3] if others else stem


def resolve(target: str, index: dict, folder: str):
    """The note a [[link]] points to, or None. When several notes share the name, the one
    in the task folder wins."""
    target = target.split("#")[0].strip().replace("\\", "/")
    if target.lower().endswith(".md"):
        target = target[:-3]
    if "/" in target:
        want = (target + ".md").casefold()
        paths = index.get(Path(target).name.casefold(), [])
        return next((p for p in paths if p.casefold() == want), None)
    paths = index.get(target.casefold(), [])
    inside = [p for p in paths if p.startswith(folder + "/")]
    return (inside or paths or [None])[0]


def exists(root: Path, rel: str, index: dict) -> bool:
    paths = index.get(Path(rel).stem.casefold(), [])
    return (root / rel).exists() or any(p.casefold() == rel.casefold() for p in paths)


# ---------------------------------------------------------------- one task line

def drop_keyword(core: str, kw) -> str:
    """The text without the keyword, and without the space it leaves behind."""
    m = kw.search(core)
    while m:
        before, after = core[:m.start()], core[m.end():]
        if before.endswith(" ") and (after.startswith(" ") or not after):
            before = before[:-1]
        elif not before and after.startswith(" "):
            after = after[1:]
        core = before + after
        m = kw.search(core)
    return core


def field_start(core: str):
    """Where the first Tasks field starts at the end of a task's text, or None when it has
    none. Tags among the fields are read through, never chosen."""
    end, first = len(core), None
    while True:
        for rx in FIELDS:
            m = rx.search(core, 0, end)
            if m:
                end = first = m.start()
                break
        else:
            m = END_TAG.search(core, 0, end)
            if not m:
                return first
            end = m.start()


def put_link(core: str, link: str) -> str:
    """The link right before the first Tasks field, else at the end of the text."""
    at = field_start(core)
    if at is None:
        return f"{core} {link}" if core else link
    left, right = core[:at].rstrip(), core[at:].lstrip()
    return f"{left} {link} {right}" if left else f"{link} {right}"


def new_line(line: str, rule: dict, link) -> str:
    """The task line with the keyword gone and the link in. Only those two change: the
    start of the line, the text, the fields and the trailing spaces stay as they were."""
    prefix, body = TASK.match(line).groups()
    core = body.rstrip()
    tail = body[len(core):]
    core = drop_keyword(core, rule["kw"])
    if link and link not in core:
        core = put_link(core, link)
    return prefix + core + tail


def task_text(desc: str) -> str:
    """The task's words alone: no tags, links reduced to their text, no web addresses,
    no markup, no emojis."""
    def shown(m):
        return m.group(2) if m.group(2) is not None else m.group(1).split("#")[0].split("/")[-1]
    text = WIKILINK.sub(shown, desc)
    text = MDLINK.sub(r"\1", text)
    text = ADDRESS.sub("", text)
    text = TAG.sub("", text)
    for mark in ("`", "**", "~~", "=="):
        text = text.replace(mark, "")
    text = "".join(c for c in unicodedata.normalize("NFC", text)
                   if unicodedata.category(c) != "So" and c not in "️‍")
    return " ".join(text.split()).strip(" .,;:-")


def safe_title(title) -> str:
    """The title as a file name that also works inside a [[link]], cut at 80 characters on
    a word. "" when nothing usable is left, or when it would read as a daily note's date:
    daynote.py takes any YYYY-MM-DD note under the daily notes folder for a daily note."""
    t = FORBIDDEN.sub(" ", unicodedata.normalize("NFC", str(title or "")))
    t = " ".join(t.split()).strip(" .")
    if len(t) > MAX_TITLE:
        cut = t[:MAX_TITLE + 1]
        t = (cut.rsplit(" ", 1)[0] if " " in cut else cut[:MAX_TITLE]).strip(" .")
    if not t or DATE_NAME.match(t) or RESERVED.match(t):
        return ""
    first = t.split()[0]
    if first[0].islower() and first[1:] == first[1:].lower():   # "prep", not "iPhone"
        t = t[0].upper() + t[1:]
    return t


def note_link(core: str, rule: dict, index: dict):
    """The task note this line links to already: a link into the rule's folder, or one
    shown with the rule's icon, wherever that note went since."""
    for m in WIKILINK.finditer(core):
        if m.group(0).startswith("!"):
            continue
        path = resolve(m.group(1), index, rule["folder"])
        if path and path.startswith(rule["folder"] + "/"):
            return path
        if rule["alias"] and (m.group(2) or "").strip() == rule["alias"]:
            return path or m.group(1).strip()
    return None


def make_item(n: int, rel: str, at: int, line: str, heading: str, rule_no: int,
              rule: dict, index: dict) -> dict:
    core = drop_keyword(TASK.match(line).group(2).rstrip(), rule["kw"])
    first = field_start(core)
    desc = core if first is None else core[:first]
    task = task_text(desc)
    words = len(task.split())
    # Tags in front are labels. A tag further on can be a word of the sentence, as in
    # "plan the release for #PT-2003", and the text without it would read cut off.
    # Claude writes the title then, as for a long text.
    as_is = 0 < words <= rule["title_words"] and not TAG.search(LEADING_TAGS.sub("", desc))
    tags = []
    for t in TAG.findall(core):
        if not t.isdigit() and t.casefold() not in [x.casefold() for x in tags]:
            tags.append(t)
    stem = Path(rel).stem
    return {"id": n, "note": rel, "line": at + 1, "text": line, "rule": rule_no,
            "where": f"{stem} > {heading}" if heading else stem,
            "task": task, "words": words,
            "title": (safe_title(task) or None) if as_is else None,
            "tags": tags, "has_note": note_link(core, rule, index)}


# ---------------------------------------------------------------- scan

def scan_vault(root: Path, rules: list, index: dict):
    """Every task line that holds a rule's keyword, outside dot folders and templates."""
    folders, files = template_paths(root)
    items, refused = [], []
    for p in sorted(root.rglob("*.md")):
        relp = p.relative_to(root)
        rel = relp.as_posix()
        if (any(part.startswith(".") for part in relp.parts) or rel in files
                or any(rel.startswith(f + "/") for f in folders)):
            continue
        try:
            raw = read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        if not any(r["keyword"].casefold() in raw.casefold() for r in rules):
            continue
        lines = split_eol(raw)[0].split("\n")
        is_synced = synced(lines)
        for i, heading in body_lines(lines):
            rule_no = next((k for k, r in enumerate(rules) if r["kw"].search(lines[i])), None)
            if rule_no is None:
                continue
            if not TASK.match(lines[i]) or is_synced:
                stem = Path(rel).stem
                refused.append({
                    "note": rel, "line": i + 1,
                    "where": f"{stem} > {heading}" if heading else stem,
                    "reason": ("Confluence-synced note, a link there is lost on the next pull"
                               if is_synced else
                               f"{rules[rule_no]['keyword']} on a line that is not a task")})
                continue
            items.append(make_item(len(items) + 1, rel, i, lines[i], heading, rule_no,
                                   rules[rule_no], index))
    return items, refused


def scan_lines(root: Path, rel: str, spec: str, rules: list, index: dict) -> list:
    """The task lines of a selection, or the one line under the cursor."""
    rel = note_rel(root, rel)
    lines = note_lines(root / rel)[1]
    if synced(lines):
        raise Stop(f"{rel} is synced with Confluence. A [[link]] there is lost on the next "
                   "pull, so no task note is made from it.")
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(spec).strip())
    first = int(m.group(1)) if m else 0
    last = min(int(m.group(2) or first), len(lines)) if m else 0
    if not 1 <= first <= last:
        raise Stop(f"Line {spec} is not in {rel}, which has {len(lines)} lines.")
    items = []
    for i, heading in body_lines(lines):
        if first <= i + 1 <= last and TASK.match(lines[i]):
            rule_no = next((k for k, r in enumerate(rules) if r["kw"].search(lines[i])), 0)
            items.append(make_item(len(items) + 1, rel, i, lines[i], heading, rule_no,
                                   rules[rule_no], index))
    if not items:
        raise Stop(f"No task on line {spec} of {rel}.")
    return items


def scan(root: Path, args: list, rules=None) -> dict:
    vault_root(root)
    rules = rules or load_rules()
    index = vault_index(root)
    if args:
        if len(args) != 2:
            raise Stop("usage: tasknote.py scan NOTE LINE, or scan NOTE FIRST-LAST")
        mode, items, refused = "single", scan_lines(root, args[0], args[1], rules, index), []
    else:
        mode = "batch"
        items, refused = scan_vault(root, rules, index)
    run = root / STATE_DIR / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / TITLES_FILE).unlink(missing_ok=True)   # titles from an older scan never apply
    write_json(run / RUN_FILE, {"mode": mode, "items": items, "refused": refused})
    return {
        "mode": mode,
        "items": [{"id": it["id"], "where": it["where"], "task": it["task"],
                   "title": it["title"], "has_note": bool(it["has_note"])} for it in items],
        "need_titles": [it["id"] for it in items if not it["title"] and not it["has_note"]],
        "refused": [{"where": r["where"], "reason": r["reason"]} for r in refused],
    }


# ---------------------------------------------------------------- check and apply

def fill(text: str, title: str, source: str) -> str:
    return text.replace("{title}", title).replace("{source}", source)


def properties(rule: dict, item: dict, title: str, source: str) -> list:
    """(name, value, type) for each property the rule sets. In a list, "{tags}" stands for
    the line's tags. An empty value is not set."""
    out = []
    for name, value in rule["properties"].items():
        if isinstance(value, list):
            values = []
            for v in value:
                for x in item["tags"] if v == "{tags}" else [fill(str(v), title, source)]:
                    x = str(x).strip()
                    if x and x.casefold() not in [y.casefold() for y in values]:
                        values.append(x)
            if values:
                out.append((name, json.dumps(values, ensure_ascii=False), "list"))
        else:
            s = fill(str(value), title, source).strip()
            if s and s != "[[]]":
                out.append((name, s, "text"))
    return out


def plan(root: Path, rules=None) -> list:
    """What apply would do for each scanned item, from the scan and Claude's titles."""
    vault_root(root)
    rules = rules or load_rules()
    run = root / STATE_DIR / "run"
    scanned = read_json(run / RUN_FILE)
    if scanned is None:
        raise Stop("No scan to work from. Run scan first.")
    titles = (read_json(run / TITLES_FILE) or {}).get("titles") or {}
    index = vault_index(root)
    out, targets = [], {}
    for item in scanned.get("items") or []:
        if not isinstance(item.get("rule"), int) or not 0 <= item["rule"] < len(rules):
            raise Stop("The task_note rules changed since the scan. Run scan again.")
        rule = rules[item["rule"]]
        e = {"id": item["id"], "where": item["where"], "item": item, "rule": rule,
             "title": None, "note": None, "link": None, "props": [], "reason": None}
        out.append(e)
        if item.get("has_note"):
            e.update(state="has a note", note=item["has_note"], title=Path(item["has_note"]).stem)
            continue
        title = safe_title(titles.get(str(item["id"])) or item.get("title") or "")
        if not title:
            e.update(state="error", reason="no usable title")
            continue
        note = f"{rule['folder']}/{title}.md"
        key = note.casefold()
        if key in targets:
            state = f"same note as {targets[key]}"
        else:
            state = "exists" if exists(root, note, index) else "new"
            targets[key] = item["id"]
        source = link_target(item["note"], index)
        e.update(state=state, title=title, note=note,
                 link=rule["link"].replace("{title}", link_target(note, index)),
                 props=properties(rule, item, title, source))
    return out


def public(e: dict) -> dict:
    out = {"id": e["id"], "where": e["where"], "title": e["title"], "note": e["note"],
           "state": e["state"]}
    if e["reason"]:
        out["reason"] = e["reason"]
    return out


def check(root: Path, rules=None) -> dict:
    return {"items": [public(e) for e in plan(root, rules)]}


def run_cli(vault: str, *args) -> str:
    """One Obsidian CLI call, and its output: the exit code is always 0."""
    exe = shutil.which("obsidian")
    if not exe:
        return "Error: the obsidian command is not on the PATH"
    try:
        r = subprocess.run([exe, f"vault={vault}", *args], capture_output=True,
                           timeout=CLI_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return f"Error: the Obsidian CLI did not run ({e.__class__.__name__})"
    return "\n".join(s for s in (decode(r.stdout), decode(r.stderr)) if s.strip()).strip()


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:   # it echoes values in the console's code page
        return raw.decode("cp1252", errors="replace")


def failed(out: str) -> bool:
    return any(line.strip().startswith("Error") for line in str(out or "").splitlines())


def first_line(out: str) -> str:
    lines = [line.strip() for line in str(out or "").splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("Error")]
    return (errors or lines or [""])[0]


def wait_for(path: Path, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > end:
            return False
        time.sleep(0.1)
    return True


def create_note(root: Path, e: dict, cli) -> tuple:
    """(ok, detail). The note from the template, then its properties."""
    out = cli("create", f"path={e['note']}", f"template={e['rule']['template']}")
    if failed(out):
        return False, first_line(out)
    if not wait_for(root / e["note"]):
        return False, f"the CLI answered {first_line(out)!r}, but {e['note']} is not there"
    unset = []
    for name, value, kind in e["props"]:
        if failed(cli("property:set", f"path={e['note']}", f"name={name}",
                      f"value={value}", f"type={kind}")):
            unset.append(name)
    return True, f"properties not set: {', '.join(unset)}" if unset else ""


def locate(lines: list, number: int, text: str):
    """The task line, still where the scan saw it, or moved by lines added above it."""
    if 1 <= number <= len(lines) and lines[number - 1] == text:
        return number - 1
    found = [i for i, line in enumerate(lines) if line == text]
    return found[0] if len(found) == 1 else None


def lines_present(root: Path, entries: list) -> set:
    """The ids whose task line is still in its note, so no note is made for a line the
    user changed since the scan."""
    ids = set()
    for rel in dict.fromkeys(e["item"]["note"] for e in entries):
        try:
            lines = note_lines(root / rel)[1]
        except OSError:
            continue
        if synced(lines):
            continue
        for e in entries:
            item = e["item"]
            if item["note"] == rel and locate(lines, item["line"], item["text"]) is not None:
                ids.add(e["id"])
    return ids


def backup_note(root: Path, rel: str, now: datetime) -> str:
    folder = root / STATE_DIR / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{Path(rel).stem}"
    path, n = folder / f"{base}.md", 2
    while path.exists():
        path, n = folder / f"{base}-{n}.md", n + 1
    shutil.copy2(root / rel, path)
    return path.relative_to(root).as_posix()


def edit_note(root: Path, rel: str, group: list, now: datetime):
    """Put the links in one note's task lines: one read, a backup, one write.
    Returns (ids done, backup path or None, error or None)."""
    path = root / rel
    try:
        raw, lines, eol, bom = note_lines(path)
    except OSError as err:
        return set(), None, f"the note could not be read ({err})"
    if synced(lines):
        return set(), None, "Confluence-synced note"
    done = set()
    for e in group:
        at = locate(lines, e["item"]["line"], e["item"]["text"])
        if at is not None:
            lines[at] = new_line(lines[at], e["rule"], e["link"])
            done.add(e["id"])
    new = join_eol("\n".join(lines), eol, bom)
    if new == raw:
        return done, None, None
    backup = backup_note(root, rel, now)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    except OSError as err:
        return set(), backup, f"writing it failed ({err}), the note as it was is in {backup}"
    return done, backup, None


def apply(root: Path, ids=None, now=None, rules=None, cli=None) -> dict:
    """Create the notes, then link them in the task lines. Nothing changes when the CLI
    does not answer, a template or a folder is missing."""
    now = now or datetime.now().astimezone()
    cli = cli or (lambda *a: run_cli(root.name, *a))
    entries = plan(root, rules)
    unknown = sorted(set(ids or ()) - {e["id"] for e in entries})
    if ids is not None:
        entries = [e for e in entries if e["id"] in ids]
    present = lines_present(root, entries)

    new = [e for e in entries if e["state"] == "new" and e["id"] in present]
    if new:
        version = cli("version")
        if not version or failed(version):
            raise Stop(f"The Obsidian CLI did not answer ({first_line(version) or 'no output'}). "
                       "Is Obsidian open? Nothing was changed.")
        for folder in sorted({e["rule"]["folder"] for e in new}):
            if not (root / folder).is_dir():
                raise Stop(f"The folder {folder} does not exist. Create it in Obsidian, then "
                           "run this again. Nothing was changed.")
        for template in sorted({e["rule"]["template"] for e in new}):
            out = cli("template:read", f"name={template}")
            if failed(out):
                raise Stop(f"Template {template}: {first_line(out)} Nothing was changed.")

    results, ready = {}, []
    for e in entries:
        state = e["state"]
        if state == "error":
            results[e["id"]] = ("skipped", e["reason"])
            continue
        if e["id"] not in present:
            results[e["id"]] = ("skipped", "the task line changed since the scan")
            continue
        if state == "new":
            if (root / e["note"]).exists():   # made by hand since the check: link it
                results[e["id"]] = ("linked", "existing note")
            else:
                ok, detail = create_note(root, e, cli)
                if not ok:
                    results[e["id"]] = ("failed", detail)
                    continue
                results[e["id"]] = ("created", detail)
        elif state.startswith("same note as"):
            if not (root / e["note"]).exists():
                results[e["id"]] = ("failed", f"{state}, which was not created")
                continue
            results[e["id"]] = ("linked", state)
        elif state == "exists":
            results[e["id"]] = ("linked", "existing note")
        else:
            results[e["id"]] = ("has a note", "")
        ready.append(e)

    backups = []
    for rel in dict.fromkeys(e["item"]["note"] for e in ready):
        group = [e for e in ready if e["item"]["note"] == rel]
        done, backup, error = edit_note(root, rel, group, now)
        if backup:
            backups.append(backup)
        for e in group:
            if e["id"] in done:
                continue
            what, _ = results[e["id"]]
            why = error or "the task line changed since the scan"
            results[e["id"]] = (("note created, line not linked" if what == "created" else "skipped"),
                                why)

    out = []
    for e in entries:
        what, detail = results[e["id"]]
        row = {"id": e["id"], "where": e["where"], "title": e["title"], "note": e["note"],
               "result": what}
        if detail:
            row["detail"] = detail
        out.append(row)
    out += [{"id": n, "result": "skipped", "detail": "no such item"} for n in unknown]
    return {"results": out, "backups": backups}


# ---------------------------------------------------------------- command line

USAGE = ("usage: tasknote.py scan [NOTE LINE] | check | apply [IDS]   "
         "(run it from the vault root)")


def parse_ids(text: str) -> set:
    try:
        ids = {int(x) for x in text.split(",") if x.strip()}
    except ValueError:
        raise Stop(f"IDS must be numbers like 1,3, not {text!r}.")
    if not ids:
        raise Stop("IDS is empty.")
    return ids


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args, root = sys.argv[1:], Path.cwd()
    try:
        if args[:1] == ["scan"]:
            out = scan(root, args[1:])
        elif args == ["check"]:
            out = check(root)
        elif args[:1] == ["apply"] and len(args) <= 2:
            out = apply(root, parse_ids(args[1]) if len(args) == 2 else None)
        else:
            sys.exit(USAGE)
    except Stop as e:
        sys.exit(str(e))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
