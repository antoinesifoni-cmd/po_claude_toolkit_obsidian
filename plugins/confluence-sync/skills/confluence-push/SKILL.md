---
name: confluence-push
description: >
  Publishes a linked local Markdown note (from an Obsidian vault) to its Confluence Cloud
  page, with a version message and optimistic locking against concurrent edits. This skill
  should be used when the user asks to "push", "publish this note", "send it to Confluence",
  "update the wiki page", "share this with the team", or wants their local edits to become
  the live page. Also covers sending the note as an unpublished draft on its page, to
  review and publish from Confluence: "push as a draft", "don't publish yet", "I'll
  publish it myself", "I want to review it before it goes live", "envoie-le en
  brouillon", "je publierai moi-même". Pushing writes to the company wiki and
  @mentions in the note notify real people, so it always requires explicit confirmation
  first.
---

# Pushing to Confluence

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py push <file> -m "version message"
```

This is the one command in the plugin that changes what other people see. Everything below
exists because of that.

## Publish or draft

Two modes, picked from the user's words:

- **Draft** (`--draft`, see [Draft push](#draft-push)) when they say the page should not
  go live yet: "as a draft", "en brouillon", "don't publish", "pas encore publier",
  "I'll publish it myself", "je publierai moi-même", "I want to review it in Confluence
  first", "let me check it in the editor", "I'll check it in the editor".
- **Publish** (the default) for a plain "push", "publish", "update the page", "send it to
  Confluence", "share it with the team", "pousse", "publie", "mets à jour la page",
  "partage-la avec l'équipe".
- **First push: draft by default.** A note never pushed to its page from here (linked
  with `link`, nothing published since) goes up as a draft unless the user asks to
  publish. If they do, confirm it is the first publish of this note to that page, then
  run `push --first-publish -m "..."`. Without either flag the script stops with
  `FIRST PUSH: ...`, which is the cue to apply this rule, not an error to work around.
- **A draft cue wins.** When a request has a publish verb and a draft cue ("send it to
  Confluence but don't publish yet", "push it, I'll check it in the editor"), it is a
  draft: the cue is the part the user added on purpose.
- **Ask** when the words fit both, such as "push it so I can have a look", "put it on
  Confluence for review" (review by whom: you in the editor, or the team on the live
  page?). Don't guess: a publish can't be taken back, a draft can sit there unnoticed.

A draft push needs a linked page. For a note with no page yet, that is confluence-link:
`create-page --draft` creates the page as an unpublished draft, its default.

## Confirm before every push

State these and get an explicit yes:

1. **The mode** - "publish now, as a new version everyone sees" or "send as a draft,
   nothing published until you publish it in Confluence". Say it that plainly, in the
   user's language, so a wrong pick is caught here.
2. **The target** - the page title, not just the filename.
3. **The version message** (publish only) - the `-m` text that lands in the page's
   history. A draft has none: don't pass `-m` with `--draft`. If the user gave one, tell
   them to type it in Confluence when they publish.
4. **Anyone who will be notified** - every `@alias` in the note becomes a real Confluence
   mention that sends a notification. Read them out. A mention added in passing during
   drafting is the most common unintended side effect of a push.

Always pass `-m` when publishing. If the user didn't give a message, propose one that summarizes what
actually changed and confirm it. "Update" is not a version message.

## After a successful push

After a draft push, give the user the edit URL the script printed, and stop there: the
step below waits until the draft is published and pulled back.

After a publish, check whether the change is big enough to update the project's Read Me and CLAUDE.md, and
if so propose the edits. Follow `${CLAUDE_PLUGIN_ROOT}/references/project-docs.md`, which
owns when to ask, what to propose and how the Read Me gets pushed. It needs the note's
previous version from `.confsync/base/`, so read that before running the push.

## When push aborts

```
ABORT: remote is vN but you last synced vM.
```

Someone edited the page since your last sync. This is the lock doing its job - nothing was
written. Do not reach for `--force`.

Follow `${CLAUDE_PLUGIN_ROOT}/references/conflicts.md`, which owns the merge flow shared
with confluence-pull. The short version: pull, merge, `resolve`, then an ordinary push of
the merged copy - no `--force`, so the lock still catches anyone who edits in between.

The one time `push --force` is right is when the user, shown the decision table, chose to
publish their version over a colleague's for that note (the "Push mine" option in
`references/conflicts.md`).

## First push to a page authored in Confluence

This is why the first push defaults to a draft (see [Publish or draft](#publish-or-draft)):
the user sees in the editor what the flattening did before anyone else does.

If the page was written in Confluence rather than by this workflow, a few things have no
Markdown: table cell colours, column widths, merged cells, text colour, and inline
comments. Everything else either converts or is kept behind a
`%%confluence-keep:...%%` marker that push puts back. Before the first push to such a page:

- Pull it, and have the user confirm the local note actually looks complete.
- Say explicitly that table colours/merges and text colour will be flattened, and that a
  deleted `%%confluence-keep` marker removes that piece from the page.

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
- **Diagrams** - ` ```mermaid ` fences are drawn by the Mermaid app on Confluence,
  ` ```plantuml ` fences get a PNG when `java` and `plantuml.jar` are available locally.
  The source always goes in a collapsible section.
- **Rich content** - callouts become panels/decisions/expands, `- [ ]` tasks become
  Confluence tasks, `` `🟢 text` `` becomes a status, `![[image.png|409]]` is uploaded
  (only if it changed), `[[Note]]` links to the note's page, `%%confluence-keep%%` markers
  are swapped back for the content they kept. An image that can't be found in the vault is
  pushed as text with a warning: tell the user.
- **Frontmatter** - stripped before upload. It never appears on the page.

## Draft push

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py push <file> --draft
```

Sends the note as unsaved changes on the page's editor draft instead of a new published
version. The user opens the printed edit URL, reviews, and publishes from Confluence. No
`-m`: Confluence drops it, and the version message is typed when publishing there.

What it does and doesn't touch:

- **The published page, its version and its history do not move.** Nor does the note:
  frontmatter, `confluence_version`, `mapping.json`'s version and `.confsync/base/` stay
  as they were. Only a `draft` record in `mapping.json` and
  `.confsync/base/<page_id>.draft.md` are written.
- **It replaces the whole draft.** Confluence has one shared draft per page, so a draft
  push wipes unpublished edits anyone has in the editor. The script refuses when the
  draft holds text that is neither published nor sent by this note:
  `UNPUBLISHED EDITS: ... last saved <when> UTC by <who>`. Show the user that line and the
  edit URL; re-run with `--replace-draft` only if they say to replace those edits.
- **Images upload for real.** They join the page's attachment list straight away, but
  appear on the page only once the draft is published.
- **The title is not changed.** Push never renames a page, in either mode.
- **Same lock as a normal push.** If the page moved since the last sync it aborts, and
  the conflict flow applies.

Confirm the mode, the page and the `@mentions` as above. Mentions should notify only once the user
publishes (unverified - say so if the note has any).

After the user publishes in Confluence, `status` reads `remote moved to vN, most likely
your draft ... published`, and a plain pull takes the published version, including
whatever was changed in the editor before publishing - no conflict, as long as the note
was not edited after the draft push. If it was, it is an ordinary conflict, merged from
the draft (see `references/conflicts.md`).

A normal push after a draft push also rewrites that old draft with what was published,
since the editor would otherwise still hold the older text.

The draft-specific states `status` can show are listed in the confluence-status skill.

## There is no unpublish

No delete command exists, on purpose. If a push went to the wrong page, the fix is to pull
the correct content back or fix it in Confluence - tell the user which page needs
attention rather than trying to undo it from here.
