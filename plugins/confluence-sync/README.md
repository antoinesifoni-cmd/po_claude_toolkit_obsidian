# confluence-sync

Git-like sync between your Obsidian vault (Markdown) and Confluence Cloud, driven by
Claude Code. No server: a Python script runs on demand and exits.

You keep writing Markdown in Obsidian. Confluence stays the company source of truth.
`push` publishes, `pull` fetches, and every push is optimistically locked so you cannot
silently clobber someone's edit.

## Commands

Claude runs these for you — you talk to it in plain language. They are listed so you can
see what the plugin can actually do.

| Command | What it does |
|---|---|
| `status [file]` | compare local hash + remote version, for one file or all |
| `pull <file>` / `pull --all` | fetch remote as Markdown; conflicts land in `<file>.remote.md` |
| `push <file> -m "msg"` | publish, with a version message. Aborts if the remote moved |
| `link <file> <pageId>` | map a note to a page that already exists |
| `link-folder <dir> <folderId>` | map a local directory to an existing Confluence folder |
| `create-page <file> --parent <id>` | create a **new** page from a note, and link it |
| `create-folder <dir> --parent <id>` | create a **new** folder plus the local directory |
| `scaffold <spec.yaml>` | create a whole nested tree in one pass — see below |
| `users <query> [--add]` | look up Confluence users for the `@mention` map |
| `rebaseline [--check]` | one-off migration for notes linked before v0.4.0 |

## Features

- **Creation, not just sync.** `create-page` / `create-folder` / `scaffold` make new
  Confluence content. `scaffold` builds a whole tree from one YAML spec, mirrors it into
  the vault, and links every node. It is idempotent, so a run that dies halfway is fixed
  by re-running the same command.
- **A project template.** The Medfar project tree ships as
  `skills/confluence-sync/templates/project.yaml`: variables for the Jira key and project
  name, an optional per-team split, Obsidian-only nodes (`CLAUDE.md`), and frontmatter
  tags applied to every note.
- **Frontmatter mirroring.** Linked notes carry `page_id`, `confluence_version`,
  `confluence_url`, `up`, `last_modified`, `author` and friends, so the Confluence linkage
  shows up in Obsidian's Properties panel rather than hiding in `.confsync/mapping.json`.
  Properties you add yourself are preserved untouched.
- **Optimistic locking.** `push` aborts if the page moved since your last sync; a
  conflicting `pull` writes `<file>.remote.md` instead of overwriting, and Claude helps
  you merge.
- **Folder name sync.** `pull --all` renames local directories to match their Confluence
  folder's current title (one-way — Confluence wins), cascading into the stored paths of
  everything nested underneath.
- **Jira links.** Bare issue keys (`PT-1947`) and ```jira-issue fences become Confluence
  smart links with live status.
- **Real mentions.** `@alias` becomes a Confluence mention that actually notifies, via
  `.confsync/users.json`.
- **Diagrams.** ```plantuml and ```mermaid fences push their source into a collapsible
  section. PlantUML additionally renders a PNG when local `java` + `plantuml.jar` are
  available in `.confsync/`.

## Setup (once per person)

1. Create an Atlassian API token:
   https://id.atlassian.com/manage-profile/security/api-tokens
2. Set three environment variables. **PowerShell** (persists for your user):
   ```powershell
   [Environment]::SetEnvironmentVariable('CONFLUENCE_BASE_URL','https://yourcompany.atlassian.net','User')
   [Environment]::SetEnvironmentVariable('CONFLUENCE_EMAIL','you@company.com','User')
   [Environment]::SetEnvironmentVariable('CONFLUENCE_API_TOKEN','<your token>','User')
   ```
   On macOS/Linux, `export` the same three in `~/.zshrc` or `~/.bashrc`. Open a new
   terminal afterwards so the values are picked up. Never paste the token into a chat.
3. Install the Python dependencies:
   ```
   pip install -r skills/confluence-sync/scripts/requirements.txt
   ```
4. In your vault, create `.confsync/config.json` so bare Jira keys become links:
   ```json
   { "jira_project_keys": ["RD", "MYLE", "CW", "MCA", "NPI", "PT"] }
   ```
5. Optional (PlantUML images): drop `plantuml.jar` into `<vault>/.confsync/`.

State lives in `<vault>/.confsync/` — `config.json`, `mapping.json`, `folders.json`,
`users.json`. Keeping `mapping.json` in git is usually what you want, so the team shares
page links.

## Usage (via Claude Code, from inside your vault)

Syncing what already exists:
- "link roadmap.md to page 5600870477"
- "pull the role model pages" / "what's the sync status?"
- "push decision-matrix.md with message 'added PT-1815 column'"
- "link folder 'Charting PPR' to Confluence folder 5641404462"

Creating something new:
- "create a page for this note under Confluence page 1154842646"
- "create the PT-1947 project for CNESST under the MYLE page, teams Charting and L&D Rx"

For that last one Claude fills in the shipped template, dry-runs it, shows you the whole
tree, and creates it only once you say yes.

## Caveats

Round-tripping is lossy for Confluence-native content. Macros (status lozenges, page
properties, TOC), layouts and columns, and inline comments do not survive the storage →
Markdown conversion; complex tables flatten to plain ones. Keep pages owned by this
workflow Markdown-shaped, and for a page heavily authored in Confluence, pull once and
inspect before adopting it.

See `skills/confluence-sync/references/transforms.md` for the full transform reference and
for the Confluence constructs that are deliberately not implemented yet.
