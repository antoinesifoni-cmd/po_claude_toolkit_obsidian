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
| `pull` | writes the remote copy to `<file>.remote.md`, leaves `<file>.md` alone, lists the note under `DECISIONS NEEDED`. |
| `push` | aborts before uploading: `ABORT: remote is vN but you last synced vM`. |

In all three cases nothing has been lost and nothing has been decided. The two versions
just exist side by side.

## The flow

This is the **Merge** option from the decision table in the confluence-pull skill. The
user has already picked it; this is how to carry it out.

1. **Get the three versions.** If the conflict surfaced on push, run `conf.py pull <file>`
   to produce `<file>.remote.md`. Then read:
   - the note, `<file>.md`: the user's version
   - `<file>.remote.md`: the Confluence version
   - `.confsync/base/<page_id>.md`: the page as it was at the last sync, the common
     ancestor. `page_id` is in the note's frontmatter.

     Exception: if `status` showed `[draft sent ..., note edited since]`, the note went up
     with `push --draft` and the page grew out of that draft. Then the ancestor is
     `.confsync/base/<page_id>.draft.md`, the body that draft sent.

   The base is what makes the merge accurate. A paragraph that is in one version only was
   added on that side if the base lacks it, and deleted on the other side if the base has
   it. A note linked before 0.11.0 may have no base yet: say so, and treat every
   difference as something to ask about instead of guessing who changed it.

2. **Sort the changes** into three groups: changed by the user only, changed on
   Confluence only, and changed on both sides in the same passage. The first two merge
   on their own. Only the third needs a decision.

3. **Write the proposal to `<file>.merged.md`**, never into the note yet. Default to
   keeping both sides' substance: dropping someone's paragraph because it conflicted with
   yours is the failure mode this whole flow exists to prevent. Keep the note's
   frontmatter as it is.

4. **Show a short summary and get approval:** "kept your 3 changes, added Marie-Ève's 2,
   one real conflict in *Critères d'acceptation*: here's what I suggest." Name who changed
   the remote side (from the decision row, or the `author` frontmatter key in
   `.remote.md`). When two edits genuinely contradict, ask - don't pick.

5. **Apply it.** Once approved, copy `<file>.merged.md` into `<file>.md`, delete the
   `.merged.md`, then record the merge:

   ```
   conf.py resolve <file>
   ```

   `resolve` moves the note's sync point to the Confluence version that was merged in and
   removes `<file>.remote.md`. A stray `.remote.md` or `.merged.md` left behind is a
   trap: it looks like a note, and it is not linked, so edits made in it go nowhere.

6. **Push it like any other edit,** through confluence-push, with a version message that
   says it was a merge: `-m "merge: <what came from each side>"`. No `--force`: if someone
   edited the page again while you were merging, the push aborts and the flow starts over
   with their new edit, instead of silently erasing it.

7. **Verify.** `conf.py status <file>` should read `in sync`.

## Force outside this flow

Never, without the user explicitly choosing it for that specific note in this
conversation (the **Overwrite** and **Push mine** options in the decision table):

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
