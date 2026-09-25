#!/usr/bin/env python3
"""
daynote.py - the deterministic half of the start-my-day skill.

Claude gathers the day (calendar, tasks, email, Jira, Confluence) and writes small files
into the run folder. This script does the two things that must not be left to judgement:
working out dates and paths, and changing the note.

Commands (run from the vault root, the folder that holds .obsidian/):
  today   print today's date, the note path and the email window as JSON, and empty the
          run folder so every file in it comes from this run
  write   build the note from the run folder, back it up, write it once, then open it in
          Obsidian through Advanced URI

Why a script does every write: the vault has no git and no undo. Keeping the one piece of
code that can damage a note small, in one place, and covered by tests is the safety net.
Claude never edits the note directly.

What write() owns in the note:
  - the block between the BEGIN and END markers (Summary and Alert), rebuilt on every run
  - meeting headings, added right after the block, and only while the note has no H1 of
    the user's own below it. Once he has written a heading, the skill stops adding any,
    which also means a re-run never duplicates them.
Everything else in the note is left byte for byte.

Text that came from outside (email, calendar, Jira, Confluence) is made inert before it
lands in the note: no code, no link targets, no addresses, no images, no HTML. Obsidian
loads remote images on its own, the PlantUML plugin sends code blocks to a public server,
and an Advanced URI link can overwrite a note in one click. [[wikilinks]] stay.

State lives in <vault>/.daily-note/ (a dot folder, so Obsidian hides it):
  run/       meetings.json, alert-*.md, summary.md   written by Claude, emptied by `today`
  backups/   <date>_<HHMMSS>.md                       the note as it was before each write

The only settings this script needs come from Obsidian itself (.obsidian/daily-notes.json),
so no value is stored twice. The skill's own settings (Gmail labels, Jira query, Summary
style) live in settings.json and are read by Claude, never by this script.

Standard library only. Dates come from datetime.now().astimezone(): zoneinfo has no time
zone database on this Windows install, while the OS clock already knows the local offset
and its daylight-saving rules.
"""

import html
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from urllib.parse import quote

BEGIN = "%% start-my-day:begin %%"
END = "%% start-my-day:end %%"
STATE_DIR = ".daily-note"
BOM = "\ufeff"   # the byte order mark some editors put at the start of a file

NO_SUMMARY = "_Summary not generated in this run._"
NO_ALERTS = "- Not checked in this run."

DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
H1 = re.compile(r"^#\s+(.+?)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
PT_ID = re.compile(r"^PT-\d+$")
HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

# Cleaning outside text. Order matters: images before links, since an image is a link
# with a "!" in front.
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HTML_TAG = re.compile(r"<[A-Za-z!/][^>]*>")
# "scheme:rest" catches https://, obsidian://, mailto:, file: and friends. It needs a letter
# first, so times like 10:30 survive, and it stops at ] so a [[wikilink]] is never cut.
ADDRESS = re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*:[^\s\[\]]+")
# Markers that would turn a line into a heading, list item, quote or task.
LEAD = re.compile(r"^(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+|\[[^\]]\]\s*)+")


class Stop(Exception):
    """Something the user must fix by hand. Printed as is, exit code 1, nothing written."""


# ---------------------------------------------------------------- vault and dates

def vault_config(root: Path) -> dict:
    """Read the Daily notes settings Obsidian already keeps."""
    if not (root / ".obsidian").is_dir():
        raise Stop(f"Run this from the vault root: there is no .obsidian folder in {root}")
    cfg_file = root / ".obsidian" / "daily-notes.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    fmt = cfg.get("format") or "YYYY-MM-DD"
    if fmt != "YYYY-MM-DD":
        raise Stop(f"Daily notes use the date format {fmt!r}. Only YYYY-MM-DD is supported.")
    template = (cfg.get("template") or "").strip("/")
    if template and not template.endswith(".md"):
        template += ".md"   # Obsidian sometimes stores the template path without it
    return {"folder": (cfg.get("folder") or "").strip("/"), "template": template}


def note_rel(cfg: dict, day: date) -> str:
    name = f"{day.isoformat()}.md"
    return f"{cfg['folder']}/{name}" if cfg["folder"] else name


def local_midnight(day: date) -> datetime:
    # A naive midnight, then astimezone(): Python asks the OS for the offset that applies on
    # that date, so a daylight-saving change between today and tomorrow comes out right.
    return datetime.combine(day, dtime()).astimezone()


def last_note_day(root: Path, folder: str, today: date) -> date:
    """The newest daily note dated before today, month subfolders included.

    The email window starts there rather than at "yesterday", so a Monday, a long weekend
    or a week off still covers every email since the last day a note was written.
    """
    base = root / folder if folder else root
    days = []
    for p in base.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if DATE_NAME.match(p.stem):
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if d < today:
                days.append(d)
    if days:
        return max(days)
    d = today - timedelta(days=1)
    while d.weekday() >= 5:   # Saturday or Sunday
        d -= timedelta(days=1)
    return d


def today_cmd(root: Path, now: datetime = None) -> dict:
    now = now or datetime.now().astimezone()
    cfg = vault_config(root)
    day = now.date()

    # Emptied at every start, so a file in here always means "produced by this run".
    # Only plain files, directly inside: the folder holds nothing else of value.
    run = root / STATE_DIR / "run"
    run.mkdir(parents=True, exist_ok=True)
    for f in run.iterdir():
        if f.is_file():
            f.unlink()

    since = last_note_day(root, cfg["folder"], day)
    return {
        "date": day.isoformat(),
        "note": note_rel(cfg, day),
        "day_start": local_midnight(day).isoformat(),
        "day_end": local_midnight(day + timedelta(days=1)).isoformat(),
        "mail_since": since.isoformat(),
        # Epoch seconds, because Gmail reads after:YYYY/MM/DD as midnight Pacific time.
        "mail_after": int(local_midnight(since).timestamp()),
    }


# ---------------------------------------------------------------- reading and cleaning

def read_text(path: Path) -> str:
    # newline="" keeps \r\n as is. Python on this PC defaults to cp1252, hence utf-8.
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def split_eol(raw: str):
    """Work on "\\n" only, and remember how to put the file's own endings and BOM back."""
    bom = raw.startswith(BOM)
    if bom:
        raw = raw[1:]
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), eol, bom


def join_eol(text: str, eol: str, bom: bool) -> str:
    if eol != "\n":
        text = text.replace("\n", eol)
    return (BOM if bom else "") + text


def clean(text: str) -> str:
    """Make outside text inert: no code, link target, address, image or HTML survives."""
    text = html.unescape(text)          # first, so &lt;img&gt; is caught as a tag below
    for token in ("%%", "~~~", "`"):
        text = text.replace(token, "")
    text = IMAGE.sub("", text)
    text = HTML_TAG.sub("", text)
    text = LINK.sub(r"\1", text)
    text = text.replace("![[", "[[")    # an embed becomes a plain link
    text = ADDRESS.sub("", text)
    return text


def summary_line(text: str) -> str:
    """The Summary as one plain line: it can never become a heading, list, quote or task."""
    parts = []
    for line in clean(text).split("\n"):
        line = LEAD.sub("", line.strip()).strip()
        if line and not re.fullmatch(r"[-=*_ ]+", line):   # a lone --- would be a rule
            parts.append(line)
    return re.sub(r"\s{2,}", " ", " ".join(parts))


def alert_lines(text: str) -> list:
    """Only "- " bullets survive, and never as a task, heading or quote."""
    out = []
    for line in clean(text).split("\n"):
        line = line.strip()
        if line.startswith("- "):
            body = re.sub(r"\s{2,}", " ", LEAD.sub("", line[2:].strip())).strip()
            if body:
                out.append("- " + body)
    return out


def heading_text(text: str) -> str:
    text = clean(text)
    for token in ("[[", "]]", "#", "\r", "\n"):
        text = text.replace(token, " ")
    text = LEAD.sub("", re.sub(r"\s{2,}", " ", text).strip()).strip()
    return text or "Meeting"


def hhmm(value) -> tuple:
    m = HHMM.match(str(value or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def read_meetings(run: Path):
    """The meetings to turn into headings, or None when the calendar was not checked."""
    f = run / "meetings.json"
    if not f.exists():
        return None
    try:
        data = json.loads(read_text(f))
    except ValueError:
        return None
    meetings = data.get("meetings") if isinstance(data, dict) else None
    if not isinstance(meetings, list):
        return None
    # Stable sort: anything without a valid start keeps its place at the end.
    return sorted((m for m in meetings if isinstance(m, dict)),
                  key=lambda m: hhmm(m.get("start")) or (99, 99))


# ---------------------------------------------------------------- building the note

def build_block(run: Path) -> list:
    summary = ""
    if (run / "summary.md").exists():
        summary = summary_line(read_text(run / "summary.md"))
    alerts = []
    for f in sorted(run.glob("alert-*.md")):
        alerts += alert_lines(read_text(f))
    return [BEGIN, "", "# Summary", "", summary or NO_SUMMARY, "",
            "## Alert", "", *(alerts or [NO_ALERTS]), "", END]


def frontmatter_end(lines: list) -> int:
    """Index of the first line after the YAML properties block, or 0 if there is none."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def put_block(lines: list, block: list, note_name: str):
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
        return lines[:begins[0]] + block + lines[ends[0] + 1:], "replaced"
    if not begins and not ends:
        at = frontmatter_end(lines)
        return lines[:at] + block + [""] + lines[at:], "inserted"
    raise Stop(f"The start-my-day markers are broken in {note_name}: it needs exactly one "
               f"'{BEGIN}' line, then one '{END}' line. Fix them by hand. Nothing was written.")


def h1_titles(lines: list) -> list:
    titles, in_code = [], False
    for line in lines:
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code:
            m = H1.match(line)
            if m:
                titles.append(m.group(1))
    return titles


def template_h1s(template_text: str) -> set:
    """The H1s the template itself brings below the block, like "# Task"."""
    lines = template_text.split("\n")
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    return set(h1_titles(lines[ends[0] + 1:] if ends else lines))


def add_headings(lines: list, meetings, own_h1s_to_ignore: set):
    if meetings is None:
        return lines, "not added, the calendar was not checked"
    if not meetings:
        return lines, "none, no meeting today"
    end = next(i for i, line in enumerate(lines) if line.strip() == END)
    if any(t not in own_h1s_to_ignore for t in h1_titles(lines[end + 1:])):
        return lines, "not added, the note already has headings"

    added = []
    for m in meetings:
        added += ["", "# " + heading_text(str(m.get("heading") or m.get("title") or "")), ""]
        pt = str(m.get("pt") or "")
        if PT_ID.match(pt):
            added.append("#" + pt)
        start, stop = hhmm(m.get("start")), hhmm(m.get("end"))
        if start and stop:
            added.append("*%02d:%02d-%02d:%02d*" % (*start, *stop))
    # One blank line after the last meeting: a "---" right under a line of text would turn
    # that text into a heading.
    added.append("")
    return lines[:end + 1] + added + lines[end + 1:], f"added {len(meetings)}"


def backup_path(root: Path, day: date, now: datetime) -> Path:
    folder = root / STATE_DIR / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{day.isoformat()}_{now.strftime('%H%M%S')}"
    path, n = folder / f"{base}.md", 2
    while path.exists():
        path, n = folder / f"{base}-{n}.md", n + 1
    return path


def write(root: Path, now: datetime = None) -> dict:
    """Apply the run folder to today's note. Never opens anything, so tests can call it."""
    now = now or datetime.now().astimezone()
    cfg = vault_config(root)
    day = now.date()
    rel = note_rel(cfg, day)
    note = root / rel
    run = root / STATE_DIR / "run"

    template_raw = ""
    if cfg["template"]:
        template_file = root / cfg["template"]
        if not template_file.exists():
            raise Stop(f"The daily note template is missing: {cfg['template']}")
        template_raw = read_text(template_file)
    template = split_eol(template_raw)[0]

    exists = note.exists()
    raw = read_text(note) if exists else template_raw
    text, eol, bom = split_eol(raw)

    lines, block_state = put_block(text.split("\n"), build_block(run), rel)
    lines, headings = add_headings(lines, read_meetings(run), template_h1s(template))
    new = join_eol("\n".join(lines), eol, bom)

    result = {"note": rel, "created": not exists, "block": block_state,
              "headings": headings, "backup": None}
    if exists and new == raw:
        result["block"] = "unchanged"
        return result

    if exists:
        backup = backup_path(root, day, now)
        shutil.copy2(note, backup)
        result["backup"] = backup.relative_to(root).as_posix()
        try:
            with open(note, "w", encoding="utf-8", newline="") as f:
                f.write(new)
        except OSError as e:
            raise Stop(f"Writing {rel} failed ({e}). The note as it was is in {result['backup']}.")
    else:
        note.parent.mkdir(parents=True, exist_ok=True)
        try:
            # "x": if Obsidian created the note a moment ago, never write over it.
            with open(note, "x", encoding="utf-8", newline="") as f:
                f.write(new)
        except FileExistsError:
            raise Stop(f"{rel} appeared during the run. Run the skill again.")
    return result


def open_note(vault_name: str, rel: str):
    """Open the note in Obsidian through Advanced URI. Returns (opened, uri).

    os.startfile hands the URI to Windows like a double-click, so no shell ever has to
    quote the & and % in it. The path is the one just written: Advanced URI creates an
    empty note when a path does not exist, so a guessed path would leave a stray file.
    """
    target = rel[:-3] if rel.endswith(".md") else rel
    uri = (f"obsidian://adv-uri?vault={quote(vault_name, safe='')}"
           f"&filepath={quote(target, safe='')}&openmode=true")
    time.sleep(1)   # let Obsidian notice the write before the URI arrives
    try:
        os.startfile(uri)
        return True, uri
    except (AttributeError, OSError):
        return False, uri


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2 or sys.argv[1] not in ("today", "write"):
        sys.exit("usage: daynote.py today|write   (run it from the vault root)")
    root = Path.cwd()
    try:
        if sys.argv[1] == "today":
            out = today_cmd(root)
        else:
            out = write(root)
            out["opened"], uri = open_note(root.name, out["note"])
            if not out["opened"]:
                out["uri"] = uri
    except Stop as e:
        sys.exit(str(e))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
