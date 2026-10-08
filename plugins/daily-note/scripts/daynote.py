#!/usr/bin/env python3
"""
daynote.py - the deterministic half of the daily-note skills.

Claude gathers the day (calendar, tasks, email, Jira, Confluence, meeting notes) and writes
small files into the run folder. This script does the things that must not be left to
judgement: working out dates and paths, and changing the note.

Commands (run from the vault root, the folder that holds .obsidian/):
  today   print today's date, the note path and the email window as JSON, and empty the
          run folder so every file in it comes from this run
  write   start-my-day: build the note from the run folder, back it up, write it once,
          then open it in Obsidian through Advanced URI
  prose   end-my-day: save the lines the user wrote in today's note to prose.json, so
          text-corrector sees them as they were when the run started
  close   end-my-day: apply the run folder to the note (text corrections, missing
          meetings, project tags, meeting recaps, the End of day block), back it up,
          write it once, then open it
  recap   meeting-recap: add one meeting's recap under its heading, back up, write once

Why a script does every write: the vault has no git and no undo. Keeping the one piece of
code that can damage a note small, in one place, and covered by tests is the safety net.
Claude never edits the note directly.

What write() owns in the note:
  - the block between the BEGIN and END markers (Summary and Alert), rebuilt on every run
  - meeting headings, added right after the block, and only while the note has no H1 of
    the user's own below it. Once he has written a heading, the skill stops adding any,
    which also means a re-run never duplicates them.
What close() and recap() own in the note:
  - the block between EOD_BEGIN and EOD_END (End of day and Review), rebuilt on every
    run, placed above the template's closing part (the "---" before "# Task")
  - the lines they add and never touch again: a heading for a meeting the note has no
    section for, a "#PT-xxxx" tag, the "**Recap:**" and "**Transcript:**" lines
  - text corrections, applied only to lines the user wrote, and only when every link,
    tag, date, time, emoji and list marker in the line stays exactly as it was
Everything else in the note is left byte for byte.

Text that came from outside (email, calendar, Jira, Confluence, meeting notes) is made
inert before it lands in the note: no code, no link targets, no addresses, no images, no
HTML. Obsidian loads remote images on its own, the PlantUML plugin sends code blocks to a
public server, and an Advanced URI link can overwrite a note in one click. [[wikilinks]]
stay. The one link the script writes, to a transcript, is built from a checked Google Doc
id, never copied from outside text.

State lives in <vault>/.daily-note/ (a dot folder, so Obsidian hides it):
  run/       meetings.json, alert-*.md, summary.md           written by Claude, emptied by `today`
             prose.json (by this script), corrections.json, tags.json, recaps.json,
             review-*.md, wrapup.md
  backups/   <date>_<HHMMSS>.md                       the note as it was before each write

The only settings this script needs come from Obsidian itself (.obsidian/daily-notes.json),
so no value is stored twice. The skills' own settings (Gmail labels, Jira query, text
style) live in config.json and are read by Claude, never by this script.

Standard library only. Dates come from datetime.now().astimezone(): zoneinfo has no time
zone database on this Windows install, while the OS clock already knows the local offset
and its daylight-saving rules.
"""

import difflib
import html
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from urllib.parse import quote

BEGIN = "%% start-my-day:begin %%"
END = "%% start-my-day:end %%"
STATE_DIR = ".daily-note"
BOM = "﻿"   # the byte order mark some editors put at the start of a file

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

# end-my-day and meeting-recap.
EOD_BEGIN = "%% end-my-day:begin %%"
EOD_END = "%% end-my-day:end %%"
NO_WRAPUP = "_End of day not generated in this run._"
NO_REVIEW = "- Not checked in this run."
NOTHING_TO_FLAG = "- Nothing to flag."

PROJECT_ID = re.compile(r"^[A-Z]{2,}-\d+$")                      # a project folder's id
PROJECT_TAG = re.compile(r"#[A-Z]{2,}-\d+(?![\w-])")
LEAD_ID = re.compile(r"^[A-Z]{2,}-?\d+\s*[-:]?\s*")              # "PT-2311: ", "PT2311 - "
TAG = re.compile(r"#[\w/-]+")                  # an Obsidian tag stops at the first * or space
CLOCK = r"(\d{1,2})(?::(\d{2})|[hH](\d{2})?)"  # 10:45, 8h30, 8h
TIME_RANGE = re.compile(r"^[\s*_]*" + CLOCK + r"\s*-\s*" + CLOCK + r"[\s*_]*$")
DOC_ID = re.compile(r"^[A-Za-z0-9_-]{25,64}$")                   # a Google Doc id
TAB_ID = re.compile(r"^t\.[A-Za-z0-9_-]{1,40}$")                 # a tab inside that doc

# Text corrections. A fix may change the words of a line, never these parts of it.
KEEP = re.compile(
    r"!?\[\[[^\]]*\]\]"                        # [[wikilinks]] and ![[embeds]]
    r"|!?\[[^\]]*\]\([^)]*\)"                  # [links](...) and ![images](...)
    r"|`[^`]*`"                                # inline code
    r"|<[^>]*>"                                # HTML, <autolinks>
    r"|\b[A-Za-z][A-Za-z0-9+.\-]*://\S+"       # web addresses
    r"|#[^\s#]+"                               # #tags
    r"|\b\w+_\w+\b"                            # identifiers like note_style
    r"|\b[A-Z][A-Z0-9]+-\d+\b"                 # ticket keys and project ids
    r"|\d{4}-\d{2}-\d{2}"                      # dates
    r"|\d{1,2}:\d{2}"                          # times
)
# The start of a line that makes it a quote, callout, list item or task.
PREFIX = re.compile(r"^\s*(?:>\s*)*(?:\[![^\]]*\][+-]?\s*)?(?:[-*+]\s+|\d+[.)]\s+)?(?:\[.\]\s+)?")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
UNDERLINE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")   # under a line of text, makes it a heading
WORD = re.compile(r"[^\W\d_]{2,}")             # two letters in a row, in any language
ADDED = ("**Recap:**", "**Transcript:**")      # lines the skills write under a meeting
SAME_ENOUGH = 0.6                              # below this, a "fix" is a rewrite


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
        "now": now.strftime("%H:%M"),
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


def summary_lines(text: str) -> list:
    """The Summary or End of day as "- " bullets; text with no bullet at all stays one plain line."""
    lines = alert_lines(text)
    if lines:
        return lines
    line = summary_line(text)
    return [line] if line else []


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
    meetings = read_list(run / "meetings.json", "meetings")
    if meetings is None:
        return None
    # Stable sort: anything without a valid start keeps its place at the end.
    return sorted(meetings, key=lambda m: hhmm(m.get("start")) or (99, 99))


def read_list(path: Path, key: str):
    """The entries under `key` in a run file, or None when the step left no usable file."""
    if not path.exists():
        return None
    try:
        data = json.loads(read_text(path))
    except ValueError:
        return None
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


# ---------------------------------------------------------------- building the note

def build_block(run: Path) -> list:
    summary = []
    if (run / "summary.md").exists():
        summary = summary_lines(read_text(run / "summary.md"))
    alerts = []
    for f in sorted(run.glob("alert-*.md")):
        alerts += alert_lines(read_text(f))
    return [BEGIN, "", "# Summary", "", *(summary or [NO_SUMMARY]), "",
            "## Alert", "", *(alerts or [NO_ALERTS]), "", END]


def frontmatter_end(lines: list) -> int:
    """Index of the first line after the YAML properties block, or 0 if there is none."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def put_block(lines: list, block: list, note_name: str):
    at = find_block(lines, BEGIN, END, note_name, "start-my-day")
    if at:
        return lines[:at[0]] + block + lines[at[1] + 1:], "replaced"
    at = frontmatter_end(lines)
    return lines[:at] + block + [""] + lines[at:], "inserted"


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
        added += [""] + meeting_block(m)
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
    d = open_day(root, now)
    run = root / STATE_DIR / "run"
    lines, block_state = put_block(d["lines"], build_block(run), d["rel"])
    lines, headings = add_headings(lines, read_meetings(run), d["tail_titles"])
    result = {"note": d["rel"], "created": not d["exists"], "block": block_state,
              "headings": headings, "backup": None}
    written, result["backup"] = save(root, d, lines)
    if not written:
        result["block"] = "unchanged"
    return result


# ---------------------------------------------------------------- shared by every write

def open_day(root: Path, now: datetime = None) -> dict:
    """Today's note as lines, or the template when the note does not exist yet."""
    now = now or datetime.now().astimezone()
    cfg = vault_config(root)
    day = now.date()
    rel = note_rel(cfg, day)
    note = root / rel

    template_raw = ""
    if cfg["template"]:
        template_file = root / cfg["template"]
        if not template_file.exists():
            raise Stop(f"The daily note template is missing: {cfg['template']}")
        template_raw = read_text(template_file)

    exists = note.exists()
    raw = read_text(note) if exists else template_raw
    text, eol, bom = split_eol(raw)
    return {"now": now, "day": day, "rel": rel, "path": note, "exists": exists, "raw": raw,
            "lines": text.split("\n"), "eol": eol, "bom": bom,
            "tail_titles": template_h1s(split_eol(template_raw)[0])}


def save(root: Path, d: dict, lines: list):
    """Write the note once, after a backup. Returns (written, backup path or None)."""
    new = join_eol("\n".join(lines), d["eol"], d["bom"])
    if new == d["raw"]:
        return False, None
    if d["exists"]:
        backup = backup_path(root, d["day"], d["now"])
        shutil.copy2(d["path"], backup)
        backup_rel = backup.relative_to(root).as_posix()
        try:
            with open(d["path"], "w", encoding="utf-8", newline="") as f:
                f.write(new)
        except OSError as e:
            raise Stop(f"Writing {d['rel']} failed ({e}). The note as it was is in {backup_rel}.")
        return True, backup_rel
    d["path"].parent.mkdir(parents=True, exist_ok=True)
    try:
        # "x": if Obsidian created the note a moment ago, never write over it.
        with open(d["path"], "x", encoding="utf-8", newline="") as f:
            f.write(new)
    except FileExistsError:
        raise Stop(f"{d['rel']} appeared during the run. Run the skill again.")
    return True, None


def find_block(lines: list, begin: str, end: str, note_name: str, name: str):
    """(first, last) line of a skill's block, or None when the note has none."""
    begins = [i for i, line in enumerate(lines) if line.strip() == begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
        return begins[0], ends[0]
    if not begins and not ends:
        return None
    raise Stop(f"The {name} markers are broken in {note_name}: it needs exactly one "
               f"'{begin}' line, then one '{end}' line. Fix them by hand. Nothing was written.")


def meeting_block(m: dict) -> list:
    """One meeting heading, in the note's compact shape: the heading, then the tag and the
    time together on the next line, "#PT-2311 *10:45-11:00*", with no blank line between."""
    out = ["# " + heading_text(str(m.get("heading") or m.get("title") or ""))]
    pt = str(m.get("pt") or "")
    meta = ["#" + pt] if PT_ID.match(pt) else []
    start, stop = hhmm(m.get("start")), hhmm(m.get("end"))
    if start and stop:
        meta.append("*%02d:%02d-%02d:%02d*" % (*start, *stop))
    return out + ([" ".join(meta)] if meta else [])


# ---------------------------------------------------------------- finding meetings in the note

def managed(lines: list, note_name: str) -> set:
    """Lines the user does not write in: the properties and the two skill blocks."""
    skip = set(range(frontmatter_end(lines)))
    for begin, end, name in ((BEGIN, END, "start-my-day"), (EOD_BEGIN, EOD_END, "end-my-day")):
        at = find_block(lines, begin, end, note_name, name)
        if at:
            skip.update(range(at[0], at[1] + 1))
    return skip


def tail_start(lines: list, skip: set, tail_titles: set) -> int:
    """First line of the template's closing part, the "---" above "# Task". Whatever the
    skills add goes above it. len(lines) when the note has no such part."""
    top, in_code = frontmatter_end(lines), False
    for i in range(top, len(lines)):
        if i in skip:
            continue
        if FENCE.match(lines[i]):
            in_code = not in_code
            continue
        m = None if in_code else H1.match(lines[i])
        if m and m.group(1) in tail_titles:
            j = i
            while j > top and not lines[j - 1].strip():
                j -= 1
            return j - 1 if j > top and lines[j - 1].strip() == "---" else i
    return len(lines)


def time_range(line: str):
    """The time range of a line that holds only that and tags, as 4 ints, else None.
    Reads what the skills write, "#PT-2311 *10:45-11:00*", and what the user types by
    hand, like "#PT-2311*10:45-11:00*" or "*7:30-8h30*"."""
    m = TIME_RANGE.match(TAG.sub(" ", line))
    if not m:
        return None
    h1, m1, m1h, h2, m2, m2h = m.groups()
    return int(h1), int(m1 or m1h or 0), int(h2), int(m2 or m2h or 0)


def section_time(lines: list, at: int, stop: int):
    """The time range right under a heading, past blank lines and tag lines."""
    for j in range(at + 1, stop):
        s = lines[j].strip()
        if not s:
            continue
        when = time_range(s)
        if when or TAG.sub("", s).strip():
            return when
    return None


def sections(lines: list, skip: set, tail: int) -> list:
    """The H1 sections the user writes in: meetings and his own topics. Each one runs to
    the next H1, the next skill block or the tail, whichever comes first."""
    heads, in_code = [], False
    for i in range(tail):
        if i in skip:
            continue
        if FENCE.match(lines[i]):
            in_code = not in_code
            continue
        m = None if in_code else H1.match(lines[i])
        if m:
            heads.append((i, m.group(1)))
    out = []
    for k, (at, title) in enumerate(heads):
        stop = heads[k + 1][0] if k + 1 < len(heads) else tail
        stop = next((j for j in range(at + 1, stop) if j in skip), stop)
        out.append({"at": at, "stop": stop, "title": title,
                    "time": section_time(lines, at, stop)})
    return out


def layout(lines: list, note_name: str, tail_titles: set):
    skip = managed(lines, note_name)
    tail = tail_start(lines, skip, tail_titles)
    return skip, tail, sections(lines, skip, tail)


def title_key(text) -> str:
    """A heading reduced to its words, so "# #PT-2311 Scheduling sync ✌️" and the
    calendar's "PT-2311 - Scheduling Sync" compare equal."""
    text = TAG.sub(" ", clean(str(text or "")))
    text = LEAD_ID.sub("", text.strip())
    return " ".join(re.sub(r"\W+", " ", text.casefold()).split())


def slot(item: dict):
    start, stop = hhmm(item.get("start")), hhmm(item.get("end"))
    return (*start, *stop) if start and stop else None


def match(items: list, secs: list, reserved: set) -> dict:
    """Pair each meeting with its section: same title first, then the same time slot,
    which covers a heading the user renamed. A section pairs with one meeting at most, and
    a section titled like another of today's meetings (`reserved`) is never taken by time.
    Returns {item index: section index}."""
    keys = [title_key(s["title"]) for s in secs]
    found, taken = {}, set()
    for n, item in enumerate(items):
        key = title_key(item.get("heading") or item.get("title"))
        k = next((k for k in range(len(secs)) if k not in taken and key and keys[k] == key), None)
        if k is not None:
            found[n] = k
            taken.add(k)
    for n, item in enumerate(items):
        when = slot(item)
        if n in found or not when:
            continue
        k = next((k for k in range(len(secs)) if k not in taken and secs[k]["time"] == when
                  and keys[k] not in reserved), None)
        if k is not None:
            found[n] = k
            taken.add(k)
    return found


# ---------------------------------------------------------------- end-my-day

def own_lines(lines: list, note_name: str) -> list:
    """Indexes of the lines the user wrote in prose, the only ones text-corrector may fix.
    Never the properties, the skill blocks, code, headings, tables, comments or rules."""
    skip = managed(lines, note_name)
    out, in_code = [], False
    for i, line in enumerate(lines):
        if i in skip:
            continue
        if FENCE.match(line):
            in_code = not in_code
            continue
        s = line.strip()
        if (in_code or not s or HEADING.match(line) or RULE.match(line) or s.startswith("|")
                or "%%" in s or s.startswith(ADDED) or time_range(s)):
            continue
        if WORD.search(KEEP.sub(" ", line)):
            out.append(i)
    return out


def kept(line: str) -> tuple:
    """Every part of a line a correction must leave exactly as it is."""
    rest = KEEP.sub(" ", line)
    return (PREFIX.match(line).group(0), KEEP.findall(line),
            [c for c in rest if unicodedata.category(c) == "So"],   # emojis: 📅 ✅ ➕ ⏳
            line.count("*"), line.count("~"), line.count("="))


def safe_fix(before: str, after: str) -> bool:
    if not after.strip() or "\n" in after or "\r" in after:
        return False
    if kept(before) != kept(after):
        return False
    words = KEEP.sub(" ", after)
    if "—" in words or ";" in words:   # the em dash and semicolon ban
        return False
    return difflib.SequenceMatcher(None, before, after).ratio() >= SAME_ENOUGH


def apply_corrections(lines: list, corrections, note_name: str):
    if corrections is None:
        return lines, "not run"
    by_text = {}
    for i in own_lines(lines, note_name):
        by_text.setdefault(lines[i], []).append(i)
    lines = list(lines)
    applied = refused = skipped = 0
    for c in corrections:
        before, after = c.get("before"), c.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            refused += 1
            continue
        after = after.rstrip() + before[len(before.rstrip()):]   # keep trailing spaces
        if after == before:
            continue
        at = by_text.pop(before, None)
        if not at:
            skipped += 1   # not a line the user wrote, or it changed during the run
            continue
        if not safe_fix(before, after):
            refused += 1
            continue
        for i in at:
            lines[i] = after
        applied += 1
    return lines, f"{applied} applied, {refused} refused, {skipped} skipped"


def insert_section(lines: list, m: dict, note_name: str, tail_titles: set) -> list:
    """Add a meeting heading in time order: before the first section that starts later,
    else after the last section, else above the End of day block or the tail."""
    skip, tail, secs = layout(lines, note_name, tail_titles)
    start = hhmm(m.get("start"))
    later = [s for s in secs if start and s["time"] and s["time"][:2] > start]
    if later:
        pos = later[0]["at"]
    elif secs:
        pos = secs[-1]["stop"]
    else:
        eod = find_block(lines, EOD_BEGIN, EOD_END, note_name, "end-my-day")
        pos = eod[0] if eod and eod[0] < tail else tail
    new = meeting_block(m) + [""]
    if pos > 0 and lines[pos - 1].strip():
        new = [""] + new
    return lines[:pos] + new + lines[pos:]


def add_meetings(lines: list, meetings, note_name: str, tail_titles: set):
    if meetings is None:
        return lines, "not checked"
    reserved = {title_key(m.get("heading") or m.get("title")) for m in meetings}
    found = match(meetings, layout(lines, note_name, tail_titles)[2], reserved)
    missing = [m for n, m in enumerate(meetings) if n not in found]
    for m in missing:
        lines = insert_section(lines, m, note_name, tail_titles)
    return lines, f"added {len(missing)}" if missing else "none missing"


def insert_tag(lines: list, s: dict, tag: str) -> list:
    """The tag goes where start-my-day puts it: at the start of the time line, or on its
    own line right under the heading when the section has no time line."""
    j = s["at"] + 1
    while j < s["stop"] and not lines[j].strip():
        j += 1
    if j < s["stop"] and time_range(lines[j]):
        return lines[:j] + [f"#{tag} {lines[j].lstrip()}"] + lines[j + 1:]
    at = s["at"] + 1
    new = ["#" + tag]
    if at < len(lines) and needs_gap(lines[at]):
        new.append("")
    return lines[:at] + new + lines[at:]


def needs_gap(line: str) -> bool:
    """A line that cannot come right under a line of text: a --- or === would turn the
    text above it into a heading, and a table or a code block needs a blank line first."""
    return bool(UNDERLINE.match(line) or FENCE.match(line) or line.lstrip().startswith("|"))


def add_tags(lines: list, tags, reserved: set, note_name: str, tail_titles: set):
    """Tag a section only when it has no project tag at all, so a re-run adds nothing."""
    if tags is None:
        return lines, "not run"
    added = 0
    for t in tags:
        tag = str(t.get("tag") or "").lstrip("#")
        if not PROJECT_ID.match(tag):
            continue
        secs = layout(lines, note_name, tail_titles)[2]
        found = match([t], secs, reserved - {title_key(t.get("heading"))})
        if 0 not in found:
            continue
        s = secs[found[0]]
        if PROJECT_TAG.search("\n".join(lines[s["at"]:s["stop"]])):
            continue
        lines = insert_tag(lines, s, tag)
        added += 1
    return lines, f"added {added}"


def doc_url(doc: str, tab) -> str:
    url = f"https://docs.google.com/document/d/{doc}/edit"
    return url + f"?tab={tab}" if TAB_ID.match(str(tab or "")) else url


def insert_recap(lines: list, s: dict, r: dict) -> list:
    """The recap goes at the end of the meeting's section, after what the user wrote."""
    text = summary_line(str(r.get("recap") or ""))
    new = [""] + ([f"**Recap:** {text}"] if text else [])
    new.append(f"**Transcript:** [Google Doc]({doc_url(r['doc'], r.get('tab'))})")
    pos = s["stop"]
    while pos > s["at"] + 1 and not lines[pos - 1].strip():
        pos -= 1
    if pos < len(lines) and lines[pos].strip():
        new.append("")
    return lines[:pos] + new + lines[pos:]


def add_recaps(lines: list, recaps, reserved: set, note_name: str, tail_titles: set):
    """One recap per meeting doc. A doc id already in the note, put there by an earlier
    run or by hand, means the meeting is done."""
    if recaps is None:
        return lines, "not run"
    added = linked = headings = refused = 0
    for r in recaps:
        if not DOC_ID.match(str(r.get("doc") or "")):
            refused += 1
            continue
        if r["doc"] in "\n".join(lines):
            linked += 1
            continue
        others = reserved - {title_key(r.get("heading") or r.get("title"))}
        secs = layout(lines, note_name, tail_titles)[2]
        found = match([r], secs, others)
        if 0 not in found:   # a meeting the note has no heading for yet
            lines = insert_section(lines, r, note_name, tail_titles)
            headings += 1
            secs = layout(lines, note_name, tail_titles)[2]
            found = match([r], secs, others)
        if 0 not in found:
            refused += 1
            continue
        lines = insert_recap(lines, secs[found[0]], r)
        added += 1
    out = [f"added {added}"]
    if headings:
        out.append(f"with {headings} new heading{'s' if headings > 1 else ''}")
    if linked:
        out.append(f"{linked} already in the note")
    if refused:
        out.append(f"{refused} refused, bad doc id or no heading")
    return lines, ", ".join(out)


def build_eod_block(run: Path) -> list:
    wrapup = []
    if (run / "wrapup.md").exists():
        wrapup = summary_lines(read_text(run / "wrapup.md"))
    # A review step that found nothing leaves its file empty, so "nothing" is said once.
    files = sorted(run.glob("review-*.md"))
    review = []
    for f in files:
        review += alert_lines(read_text(f))
    if not review:
        review = [NOTHING_TO_FLAG if files else NO_REVIEW]
    return [EOD_BEGIN, "", "# End of day", "", *(wrapup or [NO_WRAPUP]), "",
            "## Review", "", *review, "", EOD_END]


def put_eod_block(lines: list, block: list, note_name: str, tail_titles: set):
    at = find_block(lines, EOD_BEGIN, EOD_END, note_name, "end-my-day")
    if at:
        return lines[:at[0]] + block + lines[at[1] + 1:], "replaced"
    skip = managed(lines, note_name)
    pos = tail_start(lines, skip, tail_titles)
    new = list(block)
    if pos > 0 and lines[pos - 1].strip():
        new = [""] + new
    # A blank line after the marker: a "---" right under it would make it a heading.
    new.append("")
    return lines[:pos] + new + lines[pos:], "inserted"


def prose(root: Path, now: datetime = None) -> dict:
    """The user's own lines, once each, in note order, for text-corrector."""
    now = now or datetime.now().astimezone()
    rel = note_rel(vault_config(root), now.date())
    note = root / rel
    lines = split_eol(read_text(note))[0].split("\n") if note.exists() else []
    own = list(dict.fromkeys(lines[i] for i in own_lines(lines, rel)))
    run = root / STATE_DIR / "run"
    run.mkdir(parents=True, exist_ok=True)
    with open(run / "prose.json", "w", encoding="utf-8", newline="") as f:
        json.dump({"note": rel, "lines": own}, f, ensure_ascii=False, indent=1)
    return {"note": rel, "lines": len(own)}


def close(root: Path, now: datetime = None) -> dict:
    """Apply the run folder to today's note. Never opens anything either."""
    d = open_day(root, now)
    run = root / STATE_DIR / "run"
    rel, tail_titles = d["rel"], d["tail_titles"]
    meetings = read_meetings(run)
    reserved = {title_key(m.get("heading") or m.get("title")) for m in meetings or []}

    lines, fixes = apply_corrections(d["lines"], read_list(run / "corrections.json", "corrections"), rel)
    lines, added = add_meetings(lines, meetings, rel, tail_titles)
    lines, tags = add_tags(lines, read_list(run / "tags.json", "tags"), reserved, rel, tail_titles)
    lines, recaps = add_recaps(lines, read_list(run / "recaps.json", "recaps"), reserved, rel, tail_titles)
    lines, block_state = put_eod_block(lines, build_eod_block(run), rel, tail_titles)

    result = {"note": rel, "created": not d["exists"], "corrections": fixes,
              "meetings": added, "tags": tags, "recaps": recaps, "block": block_state,
              "backup": None}
    written, result["backup"] = save(root, d, lines)
    if not written:
        result["block"] = "unchanged"
    return result


# ---------------------------------------------------------------- meeting-recap

def recap(root: Path, now: datetime = None) -> dict:
    """Only the recaps, plus a heading for a meeting the note lacks."""
    d = open_day(root, now)
    run = root / STATE_DIR / "run"
    reserved = {title_key(m.get("heading") or m.get("title")) for m in read_meetings(run) or []}
    lines, recaps = add_recaps(d["lines"], read_list(run / "recaps.json", "recaps"), reserved,
                               d["rel"], d["tail_titles"])
    result = {"note": d["rel"], "created": not d["exists"], "recaps": recaps, "backup": None}
    written, result["backup"] = save(root, d, lines)
    result["written"] = written
    return result


def open_note(vault_name: str, rel: str):
    """Open the note in Obsidian through Advanced URI. Returns (opened, uri).

    os.startfile hands the URI to Windows like a double-click, so no shell ever has to
    quote the & and % in it. The path is the one just written: Advanced URI creates an
    empty note when a path does not exist, so a guessed path would leave a stray file.
    The command toggles the tab's pin: start-my-day opens a fresh tab and pins it, and
    end-my-day lands on that pinned tab and unpins it, which is wanted.
    """
    target = rel[:-3] if rel.endswith(".md") else rel
    uri = (f"obsidian://adv-uri?vault={quote(vault_name, safe='')}"
           f"&filepath={quote(target, safe='')}&openmode=true"
           f"&commandid={quote('workspace:toggle-pin', safe='')}")
    time.sleep(1)   # let Obsidian notice the write before the URI arrives
    try:
        os.startfile(uri)
        return True, uri
    except (AttributeError, OSError):
        return False, uri


COMMANDS = {"today": today_cmd, "write": write, "prose": prose, "close": close, "recap": recap}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: daynote.py {'|'.join(COMMANDS)}   (run it from the vault root)")
    root = Path.cwd()
    try:
        out = COMMANDS[sys.argv[1]](root)
        if sys.argv[1] in ("write", "close"):
            out["opened"], uri = open_note(root.name, out["note"])
            if not out["opened"]:
                out["uri"] = uri
    except Stop as e:
        sys.exit(str(e))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
