# confluence-sync

Git-like sync between your Obsidian vault (Markdown) and Confluence Cloud, driven by
Claude Code. No server: a Python script runs on demand and exits.

## Features
- `link / status / pull / push` with version messages and optimistic locking
  (push aborts if someone edited the page since your last sync)
- Linked notes get a YAML frontmatter block (page_id, confluence_url, parent link, last
  modified, author, ...) so the Confluence linkage is visible in Obsidian's Properties
  panel, not just in `.confsync/mapping.json`
- Conflict fallback: conflicting pulls write `<file>.remote.md` for manual merge
- Jira issue keys / `jira-issue` fences -> Confluence smart links
- `@alias` mentions -> real Confluence mentions (via `.confsync/users.json`)
- PlantUML fences -> rendered PNG attachments + preserved source (needs local
  `java` + `plantuml.jar` in `.confsync/`; graceful fallback without)

## Setup (once per person)
1. Create an Atlassian API token: https://id.atlassian.com/manage-profile/security/api-tokens
2. Export env vars (e.g. in ~/.zshrc):
   ```
   export CONFLUENCE_BASE_URL="https://yourcompany.atlassian.net"
   export CONFLUENCE_EMAIL="you@company.com"
   export CONFLUENCE_API_TOKEN="..."
   ```
3. `pip install -r skills/confluence-sync/scripts/requirements.txt`
4. In your vault: create `.confsync/config.json`:
   ```json
   { "jira_project_keys": ["RD", "MYLE", "CW", "MCA", "NPI", "PT"] }
   ```
5. Optional (PlantUML): drop `plantuml.jar` into `<vault>/.confsync/`.

## Usage (via Claude Code, in your vault)
- "link roadmap.md to page 5600870477"
- "pull the role model pages" / "what's the sync status?"
- "push decision-matrix.md with message 'added PT-1815 column'"

Claude runs `scripts/conf.py` for you and helps merge on conflicts.

## Caveats
Round-trip is lossy for Confluence-native macros/layouts. Keep synced pages
markdown-shaped. See `skills/confluence-sync/references/transforms.md`.
