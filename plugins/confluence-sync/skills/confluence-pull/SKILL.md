---
name: confluence-pull
description: >
  Downloads Confluence Cloud page content into linked local Markdown notes in an Obsidian
  vault, one note or the whole vault, and renames local folders to match their Confluence
  folder titles. This skill should be used when the user asks to "pull", "fetch the latest",
  "get the current version from Confluence", "bring down what's on the wiki", "refresh
  everything", or when status reported that a page moved upstream. It also handles the case
  where a pull cannot proceed because both sides changed. Pulling overwrites local note
  bodies, so it is the direction that can lose the user's own writing.
---

# Pulling from Confluence

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py pull <file>     # one note
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py pull --all      # every linked note
```

Pull overwrites the local body with the remote one. It is safe by default - the script
refuses rather than clobbering unsynced edits - but the thing at risk here is the user's
own writing, not the wiki.

## `--all` is not just "pull, repeatedly"

`pull --all` is the only command that **renames local folders**. Every linked directory is
renamed to match its Confluence folder's current title (one-way, Confluence wins), and a
rename cascades into every mapped path nested underneath it.

So treat it as a deliberate full-sync, not a convenience:

- Say that folders may be renamed before running it, especially if the user has the vault
  open in Obsidian or under git.
- If a rename is skipped with a warning ("already exists locally"), don't try to force it.
  Show the user the collision and let them resolve it by hand, then re-run.
- A single-file `pull` never renames anything.

## When pull reports CONFLICT

The script writes the remote copy to `<file>.remote.md` and leaves `<file>.md` untouched.
Nothing is lost and nothing is decided yet.

Follow `${CLAUDE_PLUGIN_ROOT}/references/conflicts.md` - it owns the merge flow end to end,
for both this skill and confluence-push. Do not improvise a merge; do not delete the
`.remote.md` file until the merged content is published.

## `--force` discards the user's local edits

`pull --force` overwrites the local note even when it has unsynced changes. That is a
destructive act against the user's own work, so:

- Never run it as a way of getting past a conflict message.
- Only run it when the user has explicitly said the local copy is disposable, in this
  conversation, about this file.
- Say plainly what will be lost before running it.

The legitimate use of force lives on the *push* side, after a merge - see the conflicts
reference.

## What does not survive the round trip

Confluence-native content flattens on the way into Markdown: macros (status lozenges, page
properties, tables of contents, children displays), layouts and columns, and inline
comments are dropped; complex tables become plain ones. Diagrams and mentions do come back
- see `${CLAUDE_PLUGIN_ROOT}/references/transforms.md`.

This matters most on the **first** pull of a page that was authored in Confluence rather
than by this workflow. Warn the user, pull once, and have them check the note looks
complete before they start treating it as the source.

Frontmatter is preserved: the nine confsync-owned keys are rewritten from live metadata,
and any manual property the user added is left alone.
