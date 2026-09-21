# First-time setup

Load this when a command fails on credentials, missing packages, or a missing vault root -
not on every invocation. A working vault needs none of it.

## 1. Credentials (three environment variables)

| Variable | Value |
|---|---|
| `CONFLUENCE_BASE_URL` | `https://<yourcompany>.atlassian.net` (no `/wiki`) |
| `CONFLUENCE_EMAIL` | the Atlassian account email |
| `CONFLUENCE_API_TOKEN` | a token from https://id.atlassian.com/manage-profile/security/api-tokens |

**Never ask the user to paste the token into the chat, and never print or log it.** Give
them the commands and let them run them.

PowerShell, persisted for the user:

```powershell
[Environment]::SetEnvironmentVariable('CONFLUENCE_BASE_URL','https://yourcompany.atlassian.net','User')
[Environment]::SetEnvironmentVariable('CONFLUENCE_EMAIL','you@company.com','User')
[Environment]::SetEnvironmentVariable('CONFLUENCE_API_TOKEN','<token>','User')
```

macOS/Linux: `export` the same three from `~/.zshrc` or `~/.bashrc`.

A new terminal is needed afterwards - values set this way don't reach an already-running
shell.

## 2. Python dependencies

```
pip install -r ${CLAUDE_PLUGIN_ROOT}/scripts/requirements.txt
```

(`requests`, `markdown`, `markdownify`, `pyyaml`.)

## 3. The vault root

State lives in `<vault>/.confsync/`, and every command finds the root by walking up from
the working directory to the nearest `.confsync/`. If there isn't one, create it at the
vault root - that directory *is* the marker.

| File | Holds |
|---|---|
| `config.json` | settings, including `jira_project_keys` |
| `mapping.json` | note path → page id, last-synced version, body hash |
| `folders.json` | directory path → Confluence folder id |
| `users.json` | `@alias` → Confluence account id, for mentions |

## 4. Jira project keys

```json
{ "jira_project_keys": ["RD", "MYLE", "CW", "MCA", "NPI", "PT"] }
```

Without this, bare issue keys in a note push as plain text instead of smart links.

## 5. Should `.confsync/` be in git?

Ask once, then stop asking. Usually **yes** for `mapping.json` and `folders.json` - the
team then shares page links rather than each person re-linking every note. If the user
would rather not version sync state, add `.confsync/` to the vault's `.gitignore`.

Either way, add `*.remote.md` to `.gitignore`: those are transient conflict copies and
should never be committed.

## 6. Optional: PlantUML images

Drop `plantuml.jar` (https://plantuml.com/download) into `<vault>/.confsync/` and make
sure `java` is on the PATH. Without it, ` ```plantuml ` fences still push their source as
a collapsible section - just with no rendered image above it. Mermaid has no local
renderer and is always text-only.
