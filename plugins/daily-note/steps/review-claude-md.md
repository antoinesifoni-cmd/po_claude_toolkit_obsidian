# Step: review-claude-md

**Goal:** flag the `CLAUDE.md` files that today's note makes out of date. Flag only, never edit them.

## Sources

1. **Today:** the note (Read `note` from the vault root) and `recaps.json` in the Run folder.
2. **Today's projects:** every project tag in the note, the entries of `tags.json`, and each recap's `pt`. At most 5, the ones with the most material today first.
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

Write `review-claude-md.md` in the Run folder. Link a project file by its full path, so the link opens that file. Made-up example:

```
- **Update** [[Confluence Projects/PT-2311 - Scheduling/CLAUDE|PT-2311 CLAUDE.md]] State is from 2026-08-28 and says the pilot starts in November. Today it moved to the week of October 5.
- **Update** vault CLAUDE.md: PT-2402 has a project folder but is not in Project tags.
```

Nothing to update: write the file empty. When no Review step finds anything, the note says `- Nothing to flag.` once.

## If it fails

Write `- **CLAUDE.md check incomplete**: <one line reason>.`
