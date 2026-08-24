# PO Claude Toolkit (Obsidian)

A Claude Code plugin marketplace for Product Owners using Obsidian as their
documentation workbench with Confluence as the company source of truth.

## Install
```
/plugin marketplace add antoinesifoni-cmd/po_claude_toolkit_obsidian
/plugin install confluence-sync@po-claude-toolkit
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
| confluence-sync | Two-way sync between vault Markdown and Confluence pages — pull, push, conflict detection — plus creation of new pages, folders, and whole project trees from a template. Jira smart links, real user mentions, PlantUML and Mermaid diagrams. |

See each plugin's README for setup.

## What this is for

The working assumption is that writing happens in Obsidian, where Markdown, backlinks and
local search are pleasant, while Confluence remains where the company reads and comments.
The plugin treats Confluence like a git remote: every note remembers the page version it
last synced, and a push that would overwrite someone else's edit is refused rather than
resolved silently.

Nothing runs in the background. Claude invokes a Python script on demand and it exits.
