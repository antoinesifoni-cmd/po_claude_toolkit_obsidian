---
name: confluence-sync
description: >
  Git-like sync between local Markdown files (Obsidian vault) and Confluence Cloud pages.
  Use whenever the user asks to pull, push, sync, link, or check the status of Confluence pages
  against local notes, mentions "conf pull", "conf push", version conflicts with Confluence,
  or wants to publish a note to Confluence with a version message. Also use to look up
  Confluence users for the mentions map (users.json).
---

# Confluence Sync

Sync local Markdown files with Confluence Cloud pages using `scripts/conf.py`, treating
Confluence like a git remote: the mapping file stores the last-synced version number per
file, and every push is optimistically locked against it.

## Setup check (first use in a vault)

1. Verify env vars are set: `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`.
   If missing, tell the user how to create a token (id.atlassian.com → Security → API tokens)
   and to export the three variables. Never ask the user to paste the token in chat.
2. Verify Python deps: `pip install -r ${CLAUDE_PLUGIN_ROOT}/skills/confluence-sync/scripts/requirements.txt`
3. State lives in `<vault>/.confsync/` (config.json, mapping.json, users.json). The script
   finds the vault root by walking up to the nearest `.confsync` directory; create it on
   first use. Recommend adding `.confsync/` and `*.remote.md` to the vault's `.gitignore`
   only if the user does NOT want sync state versioned (usually they DO want mapping.json
   in git so the team shares page links — ask once).
4. Set `jira_project_keys` in `.confsync/config.json` (e.g. `["RD","MYLE","CW","MCA","NPI","PT"]`)
   so bare issue keys become Jira links on push.

## Commands

Run with `python3 ${CLAUDE_PLUGIN_ROOT}/skills/confluence-sync/scripts/conf.py <cmd>` from
inside the vault.

- `link <file.md> <pageId>` — map a local file to an existing Confluence page. Page ID is
  the number in the page URL (`.../pages/<pageId>/Title`).
- `status [file]` — compare local hash + remote version for one or all linked files.
  Run this before pull/push when the user is unsure of state.
- `pull <file>` or `pull --all` — download remote as markdown. If the local file has
  uncommitted edits AND the remote moved, the script writes `<file>.remote.md` instead of
  overwriting, and reports a conflict.
- `push <file> -m "version message"` — upload. Aborts if the remote version moved since
  last sync (someone else edited). Always pass `-m`; if the user gave no message, propose
  one summarizing the diff and confirm it.
- `users <query> [--add]` — search Confluence users; `--add` stores them in users.json
  as `@firstname` aliases for mentions.

## Conflict handling

When pull reports a conflict:
1. Show the user a diff between `<file>.md` and `<file>.remote.md` (`git diff --no-index`
   or read both and summarize the differing sections).
2. Help merge: propose a merged version and, on approval, write it to `<file>.md` and
   delete `<file>.remote.md`.
3. Publish the merge with `push <file> --force -m "merge: ..."` — force is legitimate
   here because the merged content already contains the remote edits. Confirm with the
   user before running it.
4. In any other situation, never use `--force` (pull or push) without explicit user
   confirmation — it discards someone's work.

## Content transforms (automatic on push/pull)

See `references/transforms.md` for details. Summary:
- Jira: ```jira-issue fences and bare keys (RD-123) ↔ Jira links (render as smart links).
- Mentions: `@alias` / `@[Full Name]` ↔ real Confluence mentions via users.json.
  Push warns on unknown aliases; offer to run `users <name> --add`.
- PlantUML: ```plantuml fences → rendered PNG attachment + collapsed source on the page
  (requires java + `plantuml.jar` in `.confsync/`); falls back to a code block if absent.
  On pull, confsync-tagged diagrams come back as ```plantuml fences.

## Safety rules

- Pushing publishes to the company wiki and mentions notify people: before any push,
  state the target page title and version message and get user confirmation.
- Round-tripping is lossy for complex Confluence content (macros, layouts, statuses).
  Warn the user before the FIRST push to a page that was authored in Confluence:
  recommend pulling first and checking the markdown looks complete.
- Never print or log the API token.
