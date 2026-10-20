# Keeping the project's Read Me and CLAUDE.md current

Used by confluence-push, after a successful push. A project scaffolded from
`templates/project.yaml` has two notes that describe the whole project: the **Read Me**
(synced to Confluence) and **CLAUDE.md** (Obsidian-only, never pushed). They go stale
quietly, because nobody opens them when they change a meeting note. The moment a
significant change is published is the cheapest time to catch that.

Pull does not run this. A pulled change was made by someone else, and asking about it there
would be noise.

## When to skip it entirely

Say nothing and finish the push when any of these hold:

- The push failed, aborted, or is part of a conflict merge that isn't published yet.
- The pushed note **is** the Read Me or CLAUDE.md. This also stops the Read Me push below
  from asking again.
- The project has no Read Me or CLAUDE.md to update (see Finding the two notes).
- The change is small: typos, wording, formatting, attendee lists, routine meeting notes,
  action items, a new Jira key in passing.

## When to ask

Ask when the change shifts what someone needs to know to understand the project:

- **Scope** - something moved in or out, a phase was added or dropped.
- **A decision** that changes direction, not a detail inside the current direction.
- **People and teams** - a team joined or left, an owner changed.
- **Jira** - a new epic or a different project key.
- **Timeline** - milestones, release or pilot dates.
- **Structure** - new folders or pages, so "Where things live" in CLAUDE.md is out of date.

Read the Read Me and CLAUDE.md first. If they already say what changed, don't ask.

## Seeing what changed

Compare the note as pushed with `.confsync/base/<page_id>.md`, which still holds the
previous synced version until the push succeeds. Read it before running the push, then
compare after. With no base (a note linked before 0.11.0), use the version message and the
edits made in this conversation, and say the comparison is partial.

## Finding the two notes

- **Read Me** - the note named in the pushed note's `up` frontmatter (`[[...]]`). It is the
  project's anchor page.
- **CLAUDE.md** - in the same folder as the Read Me.

If `up` is empty or points at a missing note, skip. Don't search the vault for a likely
match.

## The question

One question per push, with the multiple-choice prompt. Keep each proposed change to one
short bullet naming the note and section it goes in:

> This change seems big enough to update the project's Read Me and CLAUDE.md. Proposed changes:
> - Read Me > Scope: add "Offline mode is out of scope for v1"
> - CLAUDE.md > Where things live: add the Dev folder
>
> **Yes** / **No** / **Only CLAUDE.md**

Leave out an option for a note that needs no change. "Other" lets the user rewrite the
bullets; apply what they say.

## On Yes

1. Edit CLAUDE.md in place. It is local only, so that's the whole job.
2. Edit the Read Me in place, under the sections named in the bullets. Keep its heading
   structure; add, don't rewrite what's there.
3. Push the Read Me right away. It's an ordinary push, so the confluence-push rules apply
   in full: confirm the page title, the version message (for example "Scope: offline mode
   out of v1"), and any `@mentions` in the Read Me. A Yes to the question is not a Yes to
   this push.
4. If that push aborts, follow `references/conflicts.md` as for any other note. The Read Me
   edit stays in the local note either way.

On **Only CLAUDE.md**, do step 1. On **No**, do nothing and don't bring it up again for
this change.
