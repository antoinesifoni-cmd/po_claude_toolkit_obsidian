"""Find linked notes and folders that were renamed, moved or deleted inside the vault.

mapping.json and folders.json key everything by path, and Obsidian does not tell this
tool when a note or folder is renamed. A renamed note is still recognisable, though: its
frontmatter keeps the `page_id` that link/pull/push wrote there. So when a mapped file is
gone, the vault is searched for a note carrying the same page id.

Read-only. `status` reports what this finds, and `relink` / `unlink` act on it only after
the user said yes - nothing here ever changes the mapping on its own.

The vault is only scanned when something is missing, so a vault in order costs nothing.
State paths are read through `config.` at call time so tests can point them elsewhere.
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .frontmatter import split_frontmatter


# Obsidian's own folders and this plugin family's state: never notes of the user.
SKIP_DIRS = {".confsync", ".obsidian", ".trash", ".daily-note", ".git"}


@dataclass
class Issues:
    renamed: list = field(default_factory=list)          # (old, new, page_id)
    missing: list = field(default_factory=list)          # (old, page_id)
    ambiguous: list = field(default_factory=list)        # (old, [paths], page_id)
    folder_renamed: list = field(default_factory=list)   # (old, new, folder_id)
    folder_missing: list = field(default_factory=list)   # (old, folder_id)

    def __bool__(self):
        return any((self.renamed, self.missing, self.ambiguous,
                    self.folder_renamed, self.folder_missing))

    def lost(self) -> set:
        """Mapping keys whose file is gone - status reports these here, not as notes."""
        return ({o for o, _, _ in self.renamed} | {o for o, _ in self.missing}
                | {o for o, _, _ in self.ambiguous})


def note_page_id(path: Path):
    """The page_id in a note's frontmatter, as a string, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    pid = split_frontmatter(text)[0].get("page_id")
    return str(pid).strip() if pid not in (None, "") else None


def scan_page_ids(skip: set) -> dict:
    """{page_id: [vault keys]} for every note outside `skip` that carries a page_id."""
    found = {}
    vault = config.VAULT
    for p in vault.rglob("*.md"):
        relp = p.relative_to(vault)
        if any(part in SKIP_DIRS for part in relp.parts[:-1]):
            continue
        if p.name.endswith(".remote.md"):   # a pull's conflict copy, not a note
            continue
        key = relp.as_posix()
        if key in skip:
            continue
        pid = note_page_id(p)
        if pid:
            found.setdefault(pid, []).append(key)
    return found


def common_new_folder(old_folder: str, moves: list):
    """Where a missing folder went, judged from the notes that used to sit in it.

    Each note moved from <old_folder>/<rest> to somewhere new. Dropping as many trailing
    parts from the new path as <rest> had gives the folder's new place. Only when every
    note agrees, and that folder exists, is it a rename; otherwise None.
    """
    guesses = set()
    for old, new in moves:
        depth = len(old[len(old_folder) + 1:].split("/"))
        parts = new.split("/")
        if len(parts) <= depth:
            return None
        guesses.add("/".join(parts[:-depth]))
    if len(guesses) != 1:
        return None
    guess = guesses.pop()
    return guess if (config.VAULT / guess).is_dir() else None


def find_issues(mapping: dict, folders: dict) -> Issues:
    issues = Issues()
    vault = config.VAULT
    gone = [f for f in mapping if not (vault / f).exists()]
    gone_folders = [f for f in folders if not (vault / f).is_dir()]
    if not gone and not gone_folders:
        return issues

    found = scan_page_ids(skip=set(mapping))
    for old in sorted(gone):
        pid = str(mapping[old]["page_id"])
        places = found.get(pid, [])
        if len(places) == 1:
            issues.renamed.append((old, places[0], pid))
        elif places:
            issues.ambiguous.append((old, sorted(places), pid))
        else:
            issues.missing.append((old, pid))

    # Outermost first: a folder inside a renamed folder moves with it, so it is not
    # reported on its own.
    moves = [(o, n) for o, n, _ in issues.renamed]
    handled = []
    for old in sorted(gone_folders, key=lambda f: f.count("/")):
        if any(config.is_under(old, h) for h in handled):
            continue
        inside = [(o, n) for o, n in moves if config.is_under(o, old)]
        new = common_new_folder(old, inside) if inside else None
        fid = folders[old].get("folder_id")
        if new and new not in folders:
            issues.folder_renamed.append((old, new, fid))
            handled.append(old)
        else:
            issues.folder_missing.append((old, fid))
    return issues


def report_lines(issues: Issues) -> list:
    """One line per finding, in the words the skills and the daily note look for."""
    q = lambda p: f'"{p}"'  # noqa: E731 - paths have spaces, the commands need quotes
    lines = []
    for old, new, fid in issues.folder_renamed:
        lines.append(f"FOLDER RENAMED? {old} -> {new} (folder {fid}). "
                     f"Move its links: conf.py relink {q(old)} {q(new)}")
    for old, new, pid in issues.renamed:
        if any(config.is_under(old, o) for o, _, _ in issues.folder_renamed):
            continue  # covered by its folder's line
        lines.append(f"RENAMED? {old} -> {new} (page {pid}). "
                     f"Move the link: conf.py relink {q(old)} {q(new)}")
    for old, places, pid in issues.ambiguous:
        lines.append(f"AMBIGUOUS: {old} is gone and page {pid} is in {len(places)} notes: "
                     + ", ".join(places) + ". Ask which one to relink.")
    for old, pid in issues.missing:
        lines.append(f"MISSING: {old} (page {pid}) is gone from the vault. "
                     f"Unlink it: conf.py unlink {q(old)}")
    for old, fid in issues.folder_missing:
        lines.append(f"FOLDER MISSING: {old} (folder {fid}) is gone from the vault. "
                     f"Unlink it: conf.py unlink {q(old)}")
    return lines
