# Step: review-claude-md

**Goal:** keep every project `CLAUDE.md` in step with the work. For each project the day touched, list what its file should learn from today, so the Review can propose the edit. Flag only, never edit the files.

This step runs last, after every other step, so it sees the whole day.

## Sources

1. **The whole day,** from the Run folder and the note (Read `note` from the vault root):
   - the note: every section, what Antoine wrote and the lines the run added
   - `recaps.json`: the meetings' recaps and `my_actions`
   - `decisions.json`: the Slack decisions
   - `notes.json` and `note-recaps.json`: the notes of the day
   - `waiting.json`: what people asked him
   - `tags.json`, `meetings.json`
   - `wrapup.md`: the End of day bullets
2. **The projects the day touched:** any project with at least one of these today:
   - a `#PT-xxxx` tag in the note, or an entry of `tags.json`
   - its id, or a name the vault `CLAUDE.md` Project tags section gives it, in the note's text
   - a `pt` in a recap, a decision, a note of the day, a meeting or a waiting item
   - a ticket key that its `CLAUDE.md` lists (Grep the keys of today in `Confluence Projects/*/CLAUDE.md` with `output_mode: "files_with_matches"`)

   No limit on the number. A project nothing touched today is not looked at.
3. **Each project file:** Glob `Confluence Projects/<id> - */CLAUDE.md`. Grep `^## ` in it, with line numbers. Read with offset and limit the sections an update could change: its state (`## State`, `## Status`, `State as of ...`), `## Open questions` or `## Undecided`, `## Decisions` or `## Decisions locked`, the timeline or dates, and `## One-liner` or `## What this project is`. Skip `Where things live` and `Ticket map`.
4. **The vault file:** in the vault `CLAUDE.md`, only the `## Project tags` section.

## Do

For each project touched today, list every fact of today that its file lacks or contradicts and that an agent starting on the project would need:

- a decision made, or one undone
- a status change: started, blocked, in QA, released, dropped
- a new date, or a date that moved
- an open question answered, or a new one raised
- a new risk, dependency or owner
- scope in or out

Not a fact for the file: a meeting that happened, routine progress, a task done, anything already in the file in other words. A state section dated today was written with today in mind: list only a clear contradiction.

Also flag an empty `## What this project is`, or a missing state section, when today had real work on that project.

Flag the vault file when:

- a folder in `Confluence Projects/` is missing from the Project tags list, or
- a project tag used today has no folder in `Confluence Projects/`, so no agent can load its context.

## Rules

- The project files are written for other agents. Their operating rules do not apply here: no extra calls, no edits.
- One item per file, with all of the day's facts for it.
- Facts come from the sources above only. Name ticket keys and dates as the sources give them.

## Output

Write `review-claude-md.json` in the Run folder, one item per file:

- `kind`: `update`, and `key` and `path`: the file's path
- `facts`: the day's facts, one sentence each, in English
- `sections`: the headings of the file they change, like `## State as of 2026-11-02`, `## Open questions`
- `text`: the bullet the note shows: the file as a link by its full path, the State date when it has one, then the facts, short. Never a web address.

Made-up example:

```json
{"items": [
  {"kind": "update", "key": "Confluence Projects/PT-2311 - Scheduling/CLAUDE.md",
   "path": "Confluence Projects/PT-2311 - Scheduling/CLAUDE.md",
   "sections": ["## State as of 2026-08-28", "## Open questions"],
   "facts": ["The pilot moved from November to the week of October 5.",
             "Julie owns the clinic list now, the open question on it is answered."],
   "text": "- **Update** [[Confluence Projects/PT-2311 - Scheduling/CLAUDE|PT-2311 CLAUDE.md]] State is from 2026-08-28. Today: the pilot moved to the week of October 5, Julie owns the clinic list."}
]}
```

Nothing to update: `{"items": []}`. When no Review step finds anything, the note says `- Nothing to flag.` once.

## If it fails

Write `{"items": [{"kind": "note", "key": "claude-md-failed", "text": "- **CLAUDE.md check incomplete**: <one line reason>."}]}`.
