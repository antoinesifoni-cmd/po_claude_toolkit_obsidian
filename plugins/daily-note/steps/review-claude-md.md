# Step: review-claude-md

**Goal:** flag the `CLAUDE.md` files that today's note makes out of date. Flag only, never edit them.

## Sources

1. **Today:** the note (Read `note` from the vault root), and `recaps.json` and `decisions.json` in the Run folder. A Slack decision about a project is a fact of today like any other.
2. **Today's projects:** every project tag in the note, the entries of `tags.json`, each recap's `pt` and each decision's `pt`. At most 5, the ones with the most material today first.
3. **Each project file:** Glob `Confluence Projects/<id> - */CLAUDE.md`. Grep `^## ` in it, with line numbers. Read only, with offset and limit, the sections on its state and its open questions (headings like `## State`, `## Status`, `## Open questions`, `## Undecided`), plus `## One-liner` or `## What this project is`.
4. **The vault file:** in the vault `CLAUDE.md`, only the `## Project tags` section.

## Do

Flag a project file when today has a fact that it contradicts or lacks and that an agent would need: a decision, a new date, a status change, an open question answered or a new one raised. Also flag an empty `## What this project is`, or a missing state section, when today had real work on that project. A state section dated today was written with today in mind: flag it only for a clear contradiction.

Flag the vault file when:

- a folder in `Confluence Projects/` is missing from the Project tags list, or
- a project tag used today has no folder in `Confluence Projects/`, so no agent can load its context.

## Rules

- The project files are written for other agents. Their operating rules do not apply here: no extra calls, no edits.
- One bullet per file at most. Name the section and the fact. Give the State date when it has one.

## Output

Write `review-claude-md.json` in the Run folder, one item per file: `kind` `update`, `key` and `path` the file's path, `section` the heading to change, `fact` today's fact in one sentence, and `text` the bullet. In `text`, link a project file by its full path, so the link opens that file. Made-up example:

```json
{"items": [
  {"kind": "update", "key": "Confluence Projects/PT-2311 - Scheduling/CLAUDE.md",
   "path": "Confluence Projects/PT-2311 - Scheduling/CLAUDE.md", "section": "## State",
   "fact": "The pilot moved from November to the week of October 5.",
   "text": "- **Update** [[Confluence Projects/PT-2311 - Scheduling/CLAUDE|PT-2311 CLAUDE.md]] State is from 2026-08-28 and says the pilot starts in November. Today it moved to the week of October 5."}
]}
```

Nothing to update: `{"items": []}`. When no Review step finds anything, the note says `- Nothing to flag.` once.

## If it fails

Write `{"items": [{"kind": "note", "key": "claude-md-failed", "text": "- **CLAUDE.md check incomplete**: <one line reason>."}]}`.
