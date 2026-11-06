# PO Claude Toolkit (Obsidian)

A Claude Code plugin marketplace for Product Owners using Obsidian as their
documentation workbench with Confluence as the company source of truth.

## Install
```
/plugin marketplace add antoinesifoni-cmd/po_claude_toolkit_obsidian
/plugin install confluence-sync@po-claude-toolkit
/plugin install daily-note@po-claude-toolkit
/plugin install user-stories@po-claude-toolkit
```

To pick up a new version later, refresh the marketplace first, then update — a plugin
update alone will not see a release the cached marketplace does not know about yet:
```
claude plugin marketplace update po-claude-toolkit
claude plugin update confluence-sync@po-claude-toolkit
```
Restart Claude Code afterwards to load it.

## Plugins

| Plugin | Purpose |
|---|---|
| confluence-sync | Two-way sync between vault Markdown and Confluence pages — pull, push, conflict detection — plus creation of new pages, folders, and whole project trees from a template. Panels, decisions, tasks, statuses, images and page links that round-trip, Jira smart links, real user mentions, Mermaid and PlantUML diagrams. A note renamed or moved in the vault keeps its link, and pages new on Confluence under your linked folders are reported, to add to the vault or ignore. |
| daily-note | Morning and evening routines. `/daily-note:start-my-day` builds today's daily note: a short bullet Summary, an Alert list (Confluence pages that moved or are new, a day left unclosed), what waits on you (Slack mentions, Confluence, Jira and Docs asks), and one heading per meeting, tagged by a Meeting map. `/daily-note:end-my-day` completes it: missing meetings, transcript links with a short recap, the notes of the day, the decisions made on Slack, project tags, `text-corrector` fixes, a short bullet End of day, and a Review it then goes through with you, one question per item: create the task, add the date, update the project CLAUDE.md, comment on Jira. `/daily-note:end-my-day yesterday` closes a past day. Say "I'm back" after time off for a catch-up note, "fetch resume of this meet" to recap one meeting, or "make a note for this task" to give a task a note of its own. |
| user-stories | Works anywhere, not only in Obsidian. Say "craft MYLE-123" (or paste a draft, or open its note) and `us-craft` turns it into a finished story in the template. It reads the parent epic, related stories, the Confluence feature page and Figma, asks you what is still open, and proposes a split when the story is too big. Questions never go in the ticket. Writes to Jira only after your yes. |

See each plugin's README for setup.

### Skills are split by risk, not by feature

`confluence-sync` ships four skills rather than one, so that asking a harmless question
doesn't load the instructions for publishing to the company wiki:

| Skill | Risk | Owns |
|---|---|---|
| `confluence-status` | none — read only | "sync", "what's the status", "what changed" |
| `confluence-link` | low, reversible | a pasted Confluence URL, "link this", "find the page called X" |
| `confluence-pull` | overwrites **your** work | "pull", "fetch the latest", "refresh everything" |
| `confluence-push` | publishes, notifies people | "push", "publish this", "update the wiki page" |

The ambiguous word "sync" routes to `status`, because checking state is the right first
move whichever direction you turn out to want. Ground that belongs to more than one skill —
the conflict merge flow, first-time setup, the content transforms — lives in the plugin's
`references/` folder, so no skill restates another's rules.

## What this is for

The working assumption is that writing happens in Obsidian, where Markdown, backlinks and
local search are pleasant, while Confluence remains where the company reads and comments.
The plugin treats Confluence like a git remote: every note remembers the page version it
last synced, and a push that would overwrite someone else's edit is refused rather than
resolved silently.

Nothing runs in the background. Claude invokes a Python script on demand and it exits.
