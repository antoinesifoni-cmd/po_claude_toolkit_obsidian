---
name: confluence-push
description: >
  Publishes a linked local Markdown note (from an Obsidian vault) to its Confluence Cloud
  page, with a version message and optimistic locking against concurrent edits. This skill
  should be used when the user asks to "push", "publish this note", "send it to Confluence",
  "update the wiki page", "share this with the team", or wants their local edits to become
  the live page. Pushing writes to the company wiki and @mentions in the note notify real
  people, so it always requires explicit confirmation first.
---

# Pushing to Confluence

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py push <file> -m "version message"
```

This is the one command in the plugin that changes what other people see. Everything below
exists because of that.

## Confirm before every push

State three things and get an explicit yes:

1. **The target** - the page title, not just the filename.
2. **The version message** - the `-m` text that lands in the page's history.
3. **Anyone who will be notified** - every `@alias` in the note becomes a real Confluence
   mention that sends a notification. Read them out. A mention added in passing during
   drafting is the most common unintended side effect of a push.

Always pass `-m`. If the user didn't give a message, propose one that summarizes what
actually changed and confirm it. "Update" is not a version message.

## When push aborts

```
ABORT: remote is vN but you last synced vM.
```

Someone edited the page since your last sync. This is the lock doing its job - nothing was
written. Do not reach for `--force`.

Follow `${CLAUDE_PLUGIN_ROOT}/references/conflicts.md`, which owns the merge flow shared
with confluence-pull. The short version: pull, merge, then push the merged copy. Force is
legitimate only at the end of that sequence, because by then the local file already
contains the other person's edits.

## First push to a page authored in Confluence

If the page was written in Confluence rather than by this workflow, its macros, layouts,
and inline comments do not exist in the Markdown - so pushing replaces a rich page with a
flattened one. Before the first push to such a page:

- Pull it, and have the user confirm the local note actually looks complete.
- Say explicitly that anything not visible in the note will be gone from the page.

Pages already owned by this workflow are fine; this is a one-time risk per adopted page.
See `${CLAUDE_PLUGIN_ROOT}/references/transforms.md` for what converts and what doesn't.

## What gets transformed on the way up

Handled automatically (details in `references/transforms.md`):

- **Jira keys** - bare keys like `PT-1947` and ` ```jira-issue ` fences become links that
  Confluence renders as smart links with live status. Only for project keys listed in
  `.confsync/config.json`.
- **Mentions** - `@alias` becomes a real mention via `users.json`. An unknown alias is
  pushed as plain text with a warning; offer to run
  `conf.py users "<name>" --add` and push again rather than leaving it as text.
- **Diagrams** - ` ```plantuml ` and ` ```mermaid ` fences push their source into a
  collapsible section, plus a rendered PNG for PlantUML when `java` and `plantuml.jar` are
  available locally.
- **Frontmatter** - stripped before upload. It never appears on the page.

## There is no unpublish

No delete command exists, on purpose. If a push went to the wrong page, the fix is to pull
the correct content back or fix it in Confluence - tell the user which page needs
attention rather than trying to undo it from here.
