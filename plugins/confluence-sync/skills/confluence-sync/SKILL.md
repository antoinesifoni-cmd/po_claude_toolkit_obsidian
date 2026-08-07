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
- `link-folder <folder> <folderId>` — map a local Obsidian folder to an existing
  Confluence *folder* (the organizational container, not a page - no body content).
  Folder id is the number in `.../wiki/spaces/<space>/folder/<folderId>`.
- `rebaseline [--check]` — one-time migration of `mapping.json` entries written by
  v0.3.0 or earlier to body-only hashing (see below). `--check` reports without writing.
  Touches only `mapping.json`: never contacts Confluence, never modifies a note.

## Change detection: the hash covers the body, not the frontmatter

`mapping.json` stores a hash of each note so `status` and `pull` can tell whether you
have local edits. Since v0.4.0 that hash covers the **markdown body only** and ignores
YAML frontmatter entirely (entries are tagged `"hash_algo": "body1"`).

Why: `push` strips frontmatter before uploading, so frontmatter can never be
push-relevant. Hashing it meant Obsidian's Properties panel reformatting the YAML
(it writes block sequences at 2-space indent and double quotes, PyYAML writes them at
zero indent with single quotes, so the two never agree) flipped every synced note to
"local changes (push needed)" within seconds of being pulled.

That mattered beyond noise: a permanently-dirty flag also poisoned the pull conflict
check, which fires on `local_dirty AND remote moved`. Clean pulls became spurious
CONFLICTs demanding a manual merge, and genuine local edits became indistinguishable
from formatter noise.

Consequences to know:
- A change to a **manual** frontmatter property (e.g. your own `status: draft`) no
  longer shows as "push needed". That is correct, since push would not upload it and
  pull preserves it, so nothing can be lost.
- `status` flags any entry still on the old whole-file hash and points at `rebaseline`.
  Migration is deliberately manual, not silent: a note could hold a genuine un-pushed
  edit made before the upgrade, and a silent re-baseline would bury it. Review the
  flagged files first, then run `rebaseline`.

## Folder name sync (one-way, Confluence wins)

Confluence folders have no body to conflict on, so this is simpler than page sync: on
every `pull --all`, each linked folder's local directory is renamed to match the
Confluence folder's *current* title if it has drifted. Local renames are never pushed
back - Confluence is the source of truth for folder names, matching this vault's
"Confluence as company source of truth" setup.
- Runs only as part of `pull --all`, not a single-file `pull` (renaming a directory is
  more disruptive than editing a note, so it only happens on the deliberate full-sync).
- A rename cascades: every mapping.json/folders.json entry nested under the renamed
  folder gets its path rewritten too, so linked pages inside it don't go stale.
- If the target name already exists locally, the rename is skipped with a warning
  instead of overwriting - resolve by hand, then re-run `pull --all`.

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

## Frontmatter properties (automatic on link/pull/push)

Every `link`/`pull`/`push` rewrites a block of YAML frontmatter at the top of the note so
the Confluence linkage is visible in Obsidian's Properties panel, not just in mapping.json:
`title`, `page_id`, `confluence_version` (the page's current Confluence version number),
`parent_page_id`, `confluence_space`, `confluence_url`, `up` (a `[[wikilink]]` to the
parent note, only when that parent is also linked locally), `last_modified`, `author`.

- These 9 keys are fully owned by confsync and regenerated every sync — **don't hand-edit
  them**, edits will be overwritten on the next pull/push. Any other frontmatter property
  already on the note is left alone.
- `mapping.json` is still the actual source of truth for the optimistic-lock `version`/
  `hash` (frontmatter is a display mirror only), so a stray edit to `page_id` in Obsidian
  can't corrupt sync state — it'll just get corrected on the next sync. Frontmatter is
  also excluded from the change hash, so reformatting it never reads as a local edit.
- `author` resolves the last editor's Confluence account id through `users.json`, same as
  mentions; if it shows a raw account id, add that person with `users <name> --add`.

## Content transforms (automatic on push/pull)

See `references/transforms.md` for details. Summary:
- Jira: ```jira-issue fences and bare keys (RD-123) ↔ Jira links (render as smart links).
- Mentions: `@alias` / `@[Full Name]` ↔ real Confluence mentions via users.json.
  Push warns on unknown aliases; offer to run `users <name> --add`.
- Diagrams: ```plantuml / ```mermaid fences → always pushed as a collapsible section
  containing the raw source (title `"<Lang> source (confsync)"`). PlantUML additionally
  renders a PNG shown above the section when java + `plantuml.jar` are available in
  `.confsync/`; Mermaid has no local renderer, so it's always text-only. On pull, either
  comes back as an inline ```plantuml / ```mermaid fence (a plain fence is what "a
  section in the text" means once it's markdown — the image, if any, is dropped locally).

## Safety rules

- Pushing publishes to the company wiki and mentions notify people: before any push,
  state the target page title and version message and get user confirmation.
- Round-tripping is lossy for complex Confluence content (macros, layouts, statuses).
  Warn the user before the FIRST push to a page that was authored in Confluence:
  recommend pulling first and checking the markdown looks complete.
- Never print or log the API token.
