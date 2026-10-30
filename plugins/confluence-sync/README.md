# confluence-sync

Git-like sync between your Obsidian vault (Markdown) and Confluence Cloud, driven by
Claude Code. No server: a Python script runs on demand and exits.

You keep writing Markdown in Obsidian. Confluence stays the company source of truth.
`push` publishes, `pull` fetches, and every push is optimistically locked so you cannot
silently clobber someone's edit.

## Four skills, split by risk

Claude picks one from what you say — you don't invoke them by name. They're separate so
that asking a harmless question doesn't load the instructions for publishing to the
company wiki.

| Skill | Risk | Owns phrasings like |
|---|---|---|
| `confluence-status` | none — read only | "sync", "what's the status", "is this up to date", "what changed", "did anyone edit it" |
| `confluence-link` | low, reversible | "link this to that page", a pasted Confluence URL, "find the page called X", "create a page for this note" |
| `confluence-pull` | overwrites **your** work only with `--force`, which it asks for first | "pull", "fetch the latest", "refresh everything", "get the current version" |
| `confluence-push` | publishes, notifies people | "push", "publish this", "send it to Confluence", "update the wiki page" |

**"Sync" goes to `status`.** It's the one ambiguous word, and checking state is the correct
first move regardless of which direction you turn out to want.

Shared ground that no single skill owns lives in `references/`: `conflicts.md` (the merge
flow, used by both pull and push), `creating.md` (create-page, create-folder, scaffold),
`project-docs.md` (proposing Read Me and CLAUDE.md updates after a push), `setup.md`
(first-time setup), `transforms.md` (what converts, what doesn't).

## Commands

Claude runs these for you. Listed so you can see what the plugin can actually do.

| Command | What it does |
|---|---|
| `status [file]` | compare local hash + remote version, for one file or all |
| `pull <file>` / `pull --all` | fetch remote as Markdown. Never writes over unpushed edits; conflicts land in `<file>.remote.md` |
| `push <file> -m "msg"` | publish, with a version message. Aborts if the remote moved |
| `push <file> --draft` | send the note as unpublished changes on the page, to review and publish from the Confluence editor. A note's first push wants this or `--first-publish` |
| `resolve <file>` | record that a conflict was merged into the note, so a normal push publishes it |
| `find <title> [--space K]` | search Confluence by title, to get an id without leaving the editor |
| `link <path> <url-or-id>` | map a note **or** folder to an existing page/folder, then pull it |
| `link-folder <path> <url-or-id>` | alias for `link`, forced to folder |
| `create-page <file> --parent <id> [--draft]` | create a **new** page from a note, and link it. `--draft` keeps it unpublished until you publish it in Confluence |
| `create-folder <dir> --parent <id>` | create a **new** folder plus the local directory |
| `scaffold <spec.yaml>` | create a whole nested tree in one pass |
| `users <query> [--add]` | look up Confluence users for the `@mention` map |
| `rebaseline [--check]` | one-off migration for notes linked before v0.4.0 |

## Features

- **One `link` for both kinds.** Paste a Confluence URL and the command works out whether
  it names a page or a folder; a bare id is probed against both. Linking a page then pulls
  it, because a just-linked note is usually empty or stale and its first push would
  otherwise publish over the real page (`--no-pull` opts out).
- **`find` by title.** Getting a page id no longer means going to Confluence to copy a URL.
- **Creation, not just sync.** `create-page` / `create-folder` / `scaffold` make new
  Confluence content. `scaffold` builds a whole tree from one YAML spec, mirrors it into
  the vault, and links every node. Idempotent, so a run that dies halfway is fixed by
  re-running the same command.
- **A project template.** The Medfar project tree ships as `templates/project.yaml`:
  variables for the Jira key and project name, an optional per-team split, Obsidian-only
  nodes (`CLAUDE.md`), and frontmatter tags applied to every note.
- **Project docs stay current.** After a push that changes scope, decisions, teams, Jira
  epics, dates or the folder structure, Claude proposes short edits to the project's Read
  Me and CLAUDE.md (Yes / No / Only CLAUDE.md). On Yes it edits both and pushes the Read
  Me, after its own confirmation. Small edits don't trigger it.
- **Frontmatter mirroring.** Linked notes carry `page_id`, `confluence_version`,
  `confluence_url`, `up`, `last_modified`, `author` and friends, so the linkage shows up in
  Obsidian's Properties panel rather than hiding in `.confsync/mapping.json`. Properties
  you add yourself are preserved untouched.
- **Your edits are never pulled over.** `pull` skips any note with unpushed edits and
  lists it with a comparison (your changes, the page's version, who edited it and when).
  Claude then asks what to do with each: push, merge, overwrite or leave it.
- **Optimistic locking.** `push` aborts if the page moved since your last sync; a
  conflicting `pull` writes `<file>.remote.md` instead of overwriting, and Claude merges
  the two against the last synced copy (kept in `.confsync/base/`) for you to approve.
- **Folder name sync.** `pull --all` renames local directories to match their Confluence
  folder's current title (one-way — Confluence wins), cascading into the stored paths of
  everything nested underneath. Stored paths always use `/`, so this works on Windows too.
- **Jira links.** Bare issue keys (`PT-1947`) and ` ```jira-issue ` fences become Confluence
  smart links with live status.
- **Real mentions.** `@alias` becomes a Confluence mention that actually notifies, via
  `.confsync/users.json`.
- **Rich pages that round-trip.** Obsidian callouts become Confluence panels, decisions
  and expand sections; `- [ ]` tasks become Confluence tasks (with `📅` dates); a code span
  like `` `🟢 In scope` `` becomes a status lozenge; `![[image.png|409]]` uploads the image;
  `[[Note]]` links to the note's page; code blocks keep their language; highlight,
  strikethrough and underline survive. Push a note, pull it back, and it is identical.
- **Nothing is silently dropped.** Confluence content with no Markdown equivalent (a TOC,
  an app macro...) is kept byte for byte behind a marker line and put back on push.
- **Diagrams.** ` ```mermaid ` fences are drawn live on Confluence by the Mermaid app,
  ` ```plantuml ` fences render a PNG when local `java` + `plantuml.jar` are available in
  `.confsync/`. The source always goes in a collapsible section.

## Setup (once per person)

Full walkthrough in `references/setup.md`. The short version:

1. Create an Atlassian API token:
   https://id.atlassian.com/manage-profile/security/api-tokens
2. Set `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` as environment
   variables. Never paste the token into a chat.
3. `pip install -r scripts/requirements.txt`
4. Create `<vault>/.confsync/config.json` with your Jira project keys:
   ```json
   { "jira_project_keys": ["RD", "MYLE", "CW", "MCA", "NPI", "PT"] }
   ```
5. Optional (PlantUML images): drop `plantuml.jar` into `<vault>/.confsync/`.

State lives in `<vault>/.confsync/` — `config.json`, `mapping.json`, `folders.json`,
`users.json`, plus `keep/`, `emoji.json` and `attachments.json` written by pull and push. Keeping `mapping.json` in git is usually what you want, so the team shares
page links.

## Usage (via Claude Code, from inside your vault)

Syncing what already exists:
- "what's the sync status?" / "sync my vault"
- "link this note to https://medfar.atlassian.net/wiki/spaces/PD/pages/5600870477/Roadmap"
- "find the page about the role model"
- "pull the role model pages"
- "push decision-matrix.md with message 'added PT-1815 column'"

Creating something new:
- "create a page for this note under Confluence page 1154842646"
- "create the PT-1947 project for CNESST under the MYLE page, teams Charting and L&D Rx"

For that last one Claude fills in the shipped template, dry-runs it, shows you the whole
tree, and creates it only once you say yes.

## Caveats

Table cell colours, column widths and merged cells have no Markdown, so they flatten;
text colour is dropped; inline comments stay in Confluence. Panels, tasks and decisions
inside a table cell are kept as markers rather than converted. For a page heavily authored
in Confluence, pull once and inspect before adopting it.

See `references/transforms.md` for every conversion, with its exact syntax.
