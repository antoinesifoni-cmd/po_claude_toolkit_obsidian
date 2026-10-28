---
name: confluence-pull
description: >
  Downloads Confluence Cloud page content into linked local Markdown notes in an Obsidian
  vault, one note or the whole vault, and renames local folders to match their Confluence
  folder titles. This skill should be used when the user asks to "pull", "fetch the latest",
  "get the current version from Confluence", "bring down what's on the wiki", "refresh
  everything", or when status reported that a page moved upstream. It also handles the
  notes a pull leaves alone because they hold unpushed edits, putting a comparison table
  and the choice (push, overwrite, merge, leave) to the user. Pulling with --force
  overwrites local note bodies, so it is the direction that can lose the user's own writing.
---

# Pulling from Confluence

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py pull <file>     # one note
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py pull --all      # every linked note
```

Pull only writes a note when Confluence has something new **and** the note has no unpushed
edits. A note with local edits is never touched, whether or not the page moved; it is
listed under `DECISIONS NEEDED` at the end of the output instead. The thing at risk here is
the user's own writing, not the wiki.

## When pull leaves notes untouched: put the decision to the user

The output ends with one row per note it left alone:

```
DECISIONS NEEDED - 2 notes left untouched:
  <file> | push needed | yours: edited <when>, +38 -5 | Confluence: v14 by <who> on <date>, no change since your last sync
  <file> | CONFLICT | yours: edited <when>, +3 -1 | Confluence: v9 by <who> on <date>, +4 -0 since your last sync | remote copy: <name>.remote.md
```

Line counts are against the last synced version. Never act on these notes before the user
has chosen. Show them as a table first:

| Note | Your edit | Confluence page | Edited on Confluence since your last sync? |
|---|---|---|---|
| PRD - Alertes cliniques | today 10:42, +38 / −5 lines | v14, Marie-Ève Tremblay, Oct 9 | No |
| Notes rencontre équipe | Oct 13 16:10, +3 / −1 lines | v9, Julien Côté, Oct 12 | Yes, +4 / −0 lines |

Then the options side by side. Show only the rows that apply to these notes. Merge and
"Push mine" only exist when Confluence changed too (a CONFLICT row):

| Option | Your note | Confluence page | Risk |
|---|---|---|---|
| **Push** (Confluence unchanged) | kept | updated with your version | notifies anyone you @mention |
| **Merge** (Confluence changed) | gets both sides' changes, after you approve | updated with the merge when you push | none, you review it before anything is written |
| **Push mine** (Confluence changed) | kept | your version replaces theirs | their edits disappear from the page (still in Confluence's page history) |
| **Overwrite** | replaced by the Confluence version | unchanged | your edits are lost for good |
| **Leave** | kept | unchanged | none, they stay out of sync |

Recommend Merge for a CONFLICT and Push for "push needed". Ask whether one choice applies
to every note or whether to go note by note. Then, for each note:

- **Push**: hand off to confluence-push, which confirms the target, message and mentions.
- **Merge**: follow `${CLAUDE_PLUGIN_ROOT}/references/conflicts.md`.
- **Push mine**: confluence-push with `--force`. Say whose edits will disappear from the
  live page and confirm once more.
- **Overwrite**: `conf.py pull <file> --force`. Say what will be lost (the line count from
  the table) before running it.
- **Leave**: nothing. Mention that `status` will keep showing the note.

## `--all` is not just "pull, repeatedly"

`pull --all` is the only command that **renames local folders**. Every linked directory is
renamed to match its Confluence folder's current title (one-way, Confluence wins), and a
rename cascades into every mapped path nested underneath it.

So treat it as a deliberate full-sync, not a convenience:

- Say that folders may be renamed before running it, especially if the user has the vault
  open in Obsidian or under git.
- The rename happens on disk, not through Obsidian, so wikilinks that spell out a folder
  path (`[[Projets/Alertes/PRD]]`) are not updated. Plain `[[PRD]]` links are fine. If the
  user relies on path links, they can rename the folder in Obsidian first, then run pull.
- If a rename is skipped with a warning ("already exists locally"), don't try to force it.
  Show the user the collision and let them resolve it by hand, then re-run.
- A single-file `pull` never renames anything.

## "its folder no longer exists locally"

Pull will not recreate a note whose folder is gone. That almost always means the folder
was moved or renamed outside this tool and the link is stale, not that the page is new.
Writing it would rebuild the old folder next to the real one. Find where the note lives
now and re-link it there with confluence-link.

## `--force` discards the user's local edits

`pull --force` overwrites the local note even when it has unpushed changes. That is a
destructive act against the user's own work, so:

- Never run it as a way of getting past a skipped note or a conflict.
- Only run it when the user picked **Overwrite** for that note, in this conversation, or
  has otherwise said explicitly that the local copy is disposable.
- Say plainly what will be lost before running it.

## What does not survive the round trip

Panels, decisions, tasks, statuses, dates, images, page links, code blocks, diagrams and
mentions come back as Obsidian Markdown (callouts, `- [ ]`, `` `🟢 text` ``, `![[...]]`,
`[[...]]`). Images are downloaded into the vault's attachment folder. Anything else (a TOC,
an app macro, a layout) becomes a `%%confluence-keep:<id> Label%%` line that push puts
back, so it is not lost. Only table cell colours, column widths, merged cells and text
colour flatten, and inline comments stay in Confluence - see
`${CLAUDE_PLUGIN_ROOT}/references/transforms.md`.

If the user asks what a `%%confluence-keep` line is: it stands for a piece of the page
with no Markdown. Leave it where it is to keep it, delete it to remove it on next push.

This matters most on the **first** pull of a page that was authored in Confluence rather
than by this workflow. Warn the user, pull once, and have them check the note looks
complete before they start treating it as the source.

Frontmatter is preserved: the nine confsync-owned keys are rewritten from live metadata,
and any manual property the user added is left alone.
