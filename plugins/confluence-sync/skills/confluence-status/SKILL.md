---
name: confluence-status
description: >
  Reports the sync state between local Markdown notes (an Obsidian vault) and the Confluence
  Cloud pages they are linked to: which notes have local edits, which pages moved upstream,
  which are in sync, and which are not linked at all. This skill should be used whenever the
  user says "sync" without naming a direction, or asks "what's the status", "is this up to
  date", "what changed", "what's linked to Confluence", "did anyone edit the page", "is it
  safe to push", or wants a drift check before editing. Read-only - it never writes to
  Confluence and never modifies a note. Once the state is known, hand off to the
  confluence-pull or confluence-push skill.
---

# Confluence status

Read-only. Nothing this skill does can lose work, so run it freely - and run it *first*
whenever the direction of travel isn't obvious yet.

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py status [file]
```

No argument checks every linked note. Run from inside the vault (the script walks up to
the nearest `.confsync/` directory to find the root).

If it exits complaining about credentials or missing packages, read
`${CLAUDE_PLUGIN_ROOT}/references/setup.md` and walk the user through first-time setup.

## "Sync my vault" means: status first

Users say "sync" to mean pull, push, or "tell me where things stand". Don't guess.
Run `status`, show what it says, then propose the direction. Acting on a guess here is
how someone's work gets overwritten.

The one exception: if the user names the direction ("push my changes", "get the latest
from Confluence"), skip straight to that skill.

## Reading the output

Each line is `<file>: v<local> local | v<remote> remote -> <state>`.

| State | Meaning | Next step |
|---|---|---|
| `in sync` | body hash matches, versions match | nothing to do |
| `local changes (push needed)` | you edited the note | confluence-push |
| `remote moved to vN (pull needed)` | someone edited the page | confluence-pull |
| `CONFLICT: local changes AND remote moved` | both sides moved | `references/conflicts.md` |
| `not linked` | no mapping entry for that path | confluence-link |

A `CONFLICT` line is a *prediction*, not damage. Nothing has happened yet - it is telling
you that a plain pull would have to choose. That is exactly the moment to read
`${CLAUDE_PLUGIN_ROOT}/references/conflicts.md` and follow the merge flow, before either
side is touched.

## The legacy-hash flag

A line tagged `[legacy whole-file hash, run 'conf.py rebaseline']` was written by v0.3.0
or earlier, when the stored hash covered the YAML frontmatter as well as the body. Those
entries report "push needed" the moment Obsidian reformats the properties block, whether
or not anything real changed.

Don't just run `rebaseline` to silence it. Any of those notes could hold a genuine
un-pushed edit from before the upgrade, and re-baselining would bury it. Review each
flagged file with the user first, push what's real, then:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py rebaseline --check   # report only
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py rebaseline           # write
```

`rebaseline` only rewrites `mapping.json`. It never contacts Confluence and never touches
a note.

## What "local changes" does not cover

The stored hash covers the markdown body only, never the frontmatter. So editing a manual
property (your own `status: draft`, a tag) will *not* show as "push needed" - which is
correct, because push strips frontmatter before uploading and pull preserves it, so
nothing can be lost either way. If a user insists their edit isn't being detected, check
whether they edited only frontmatter before assuming a bug.
