# Conflicts: the merge flow

Owned here, not in the skills. `confluence-pull` and `confluence-push` both land on this
file, and neither describes the flow in its own words - two descriptions of a merge
procedure drift, and the half that drifts is the half that loses someone's work.

## What a conflict is

Both sides moved since the last sync: the local note has edits that were never pushed,
**and** the Confluence page has a version number higher than the one recorded in
`mapping.json`.

Either alone is not a conflict - that's just "push needed" or "pull needed".

## How each command behaves

| Command | Behaviour on conflict |
|---|---|
| `status` | predicts it: `CONFLICT: local changes AND remote moved to vN`. Nothing written. |
| `pull` | writes the remote copy to `<file>.remote.md`, leaves `<file>.md` alone, reports. |
| `push` | aborts before uploading: `ABORT: remote is vN but you last synced vM`. |

In all three cases nothing has been lost and nothing has been decided. The two versions
just exist side by side.

## The flow

1. **Get both copies on disk.** If the conflict surfaced on push, run
   `conf.py pull <file>` to produce `<file>.remote.md`. If it surfaced on pull, that file
   already exists.

2. **Show the user the difference.** Don't summarize it from memory:

   ```
   git diff --no-index <file>.md <file>.remote.md
   ```

   If the vault isn't a git repo, read both and lay out the differing sections. Name who
   changed the remote side - the note's `author` frontmatter key has the last editor.

3. **Propose a merge, don't impose one.** Write out the merged version and get approval
   before it touches the note. Default to keeping both sides' substance: dropping
   someone's paragraph because it conflicted with yours is the failure mode this whole
   flow exists to prevent. When two edits genuinely contradict, ask - don't pick.

4. **Write the merge** to `<file>.md`, then delete `<file>.remote.md`. The stray
   `.remote.md` left behind is a trap: it looks like a note, and it is excluded from sync,
   so edits made in it silently go nowhere.

5. **Publish with force.**

   ```
   conf.py push <file> --force -m "merge: <what came from each side>"
   ```

   Force is correct *here and only here*: the local file now already contains the remote
   edits, so there is nothing left to clobber. Confirm with the user before running it,
   same as any push, and make the version message say it was a merge.

6. **Verify.** `conf.py status <file>` should read `in sync`.

## Force outside this flow

Never, without the user explicitly saying so about that specific file in this
conversation:

- `pull --force` discards the user's own unsynced writing.
- `push --force` discards a colleague's edits from the live page.

If someone asks to "just force it" to get past an error message, walk them through the
merge instead. It takes one extra step and nobody loses a paragraph.

## A conflict that isn't real

If a note flips to "local changes" seconds after a clean pull and the user swears they
edited nothing, check whether `status` flagged it `[legacy whole-file hash]`. Pre-0.4.0
entries hash the frontmatter too, so Obsidian reformatting the properties block reads as
an edit - and that false "dirty" flag then manufactures conflicts on every later pull.
`conf.py rebaseline` fixes it; see the confluence-status skill for why it isn't automatic.
