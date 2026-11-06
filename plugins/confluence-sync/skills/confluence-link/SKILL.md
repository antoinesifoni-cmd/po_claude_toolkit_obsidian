---
name: confluence-link
description: >
  Connects a local Markdown note or folder (in an Obsidian vault) to a Confluence Cloud page
  or folder, or creates the Confluence page/folder when it does not exist yet. This skill
  should be used when the user pastes a Confluence URL and wants a note attached to it, or
  says "link this note to that page", "connect this folder to Confluence", "find the page
  called X", "this note should live at <URL>", "create a Confluence page for this note"
  (created as an unpublished draft by default), or
  reports that a note is "not linked". It also covers looking up a page or folder id by
  title, and repairing links after a note or folder was renamed, moved or deleted in the
  vault: "fix my Confluence links", "I renamed this note", "répare mes liens Confluence",
  or status lines starting RENAMED?, MISSING, AMBIGUOUS or FOLDER. Also brings pages that
  are new on Confluence under linked folders into the vault, or ignores them: "add it to my
  vault", "add the new pages", "ignore that page", or status lines starting NEW. For
  syncing content on already-linked notes, use confluence-pull or confluence-push instead.
---

# Linking a note to Confluence

Two branches, and picking the right one is the only real decision here:

- **The page already exists** in Confluence → `link`
- **It doesn't exist yet** → `create-page` / `create-folder`

Everything else - parsing the URL, telling a page from a folder, fetching the content - is
handled by the script.

## Link to something that exists

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py link <path> <url-or-id>
```

Paste the Confluence URL straight in. The command works out from the URL whether it names
a page or a folder, and falls back to probing the id if given a bare number. `link-folder`
still exists as an alias forced to folder, but you rarely need it.

**Linking a page then pulls it.** A just-linked note is empty or stale far more often than
it is authoritative, and the first `push` on a note that was never pulled publishes over
the real page. Let the pull happen. Only pass `--no-pull` when the local note is
deliberately the newer copy - and say so out loud before you do, because the user then has
a note that will overwrite Confluence on the next push.

Folders link without pulling: a Confluence folder has no body, only a name. Name sync
happens later, on `pull --all`.

## Don't have the URL? Search for it

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py find "<title fragment>" [--space PD]
```

Prints kind, id, space, title and URL for each match. Use this instead of sending the user
off to Confluence to copy a link. Show the matches and let them pick when more than one
looks plausible - never link to a guess.

## Create, when there is nothing to link to

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py create-page   <file.md> --parent <id> [--title T] --draft
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py create-folder <dir>     --parent <id> [--title T]
```

Both create the Confluence side, create or reuse the local side, and link them in one
step. `--parent` takes a page id or a folder id.

**A new page starts as a draft.** `create-page --draft` is the default: the page exists
but nobody sees it until the user publishes it from the Confluence editor (the script
prints the edit URL; give it to them). Leave out `--draft` only when the user asks for the
page to be published straight away, and then confirm that in so many words: "this
publishes a new page everyone in the space can see". Afterwards:

- While it is a draft, `status` and `pull` report "still a draft in Confluence" and leave
  the note alone. More edits go up with `push --draft` (confluence-push).
- Once published, it is v1 and a plain `pull` takes it, with whatever was changed in the
  editor. A plain `push` before that is refused with `FIRST PUSH: ...`.
- Images upload to the draft page as usual.

Folders have no draft state: `create-folder` always creates a visible folder. `scaffold`
creates published pages too: its tree is the structure the team works in.

**Creating is visible.** Before running either, state the target space, the parent, the
exact title and, for a page, draft or published, and get an explicit yes. Ask where it goes rather than guessing a parent;
if the user still won't say, fall back to `--space personal` and tell them that's what you
did.

For a whole project tree rather than one page, see
`${CLAUDE_PLUGIN_ROOT}/references/creating.md` - that is the `scaffold` command, and it
always gets a `--dry-run` shown to the user first.

## Which note, which page

Be concrete before writing anything:

- If the user says "this note", confirm the filename you resolved it to.
- If the local file doesn't exist yet, `link` still works (the pull creates it) - but say
  so, so they aren't surprised by a new file.
- `create-folder` needs the Confluence side to be a real *folder*, not a page. If the
  parent URL says `/pages/`, a folder can still be created under it - Confluence allows
  either as a parent.
- Re-linking a path that is already mapped silently replaces the mapping and resets its
  version to 0. If the path is already in `mapping.json`, say so and confirm, rather than
  quietly repointing a note at a different page.

## Fix links after a rename or delete

Links are stored by path, so renaming or moving a linked note or folder in Obsidian, or
deleting it, leaves a link pointing at nothing. Run status first (from the vault root):

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py status
```

Then take its `RENAMED?`, `FOLDER RENAMED?`, `MISSING`, `FOLDER MISSING` and `AMBIGUOUS`
lines **one at a time**, and ask before each change. Never batch them silently, even when
the match looks certain: the user wants to confirm every one.

| Line | Ask | On yes |
|---|---|---|
| `RENAMED? <old> -> <new>` | "`<old>` was renamed to `<new>`. Move the link?" | `conf.py relink "<old>" "<new>"` |
| `FOLDER RENAMED? <old> -> <new>` | "Folder `<old>` was renamed to `<new>`. Move its link and the links of the notes inside?" | `conf.py relink "<old>" "<new>"` (one command moves them all) |
| `MISSING: <old>` | "`<old>` is gone from the vault. Unlink it?" Offer **Unlink** and **Keep for now** | `conf.py unlink "<old>"` |
| `FOLDER MISSING: <old>` | the same, for a folder | `conf.py unlink "<old>"` |
| `AMBIGUOUS: ...` | "Page N is in A and B. Which one is the linked note?" Offer each, and **Neither** | `conf.py relink "<old>" "<chosen>"`, nothing for Neither |

Use the exact paths printed, quoted: they contain spaces.

What these commands do, so you can say it plainly:

- They only rewrite `.confsync/mapping.json` / `folders.json`, after copying both to
  `.confsync/backups/`. Nothing is sent to Confluence.
- **A local rename never renames the Confluence page.** The page keeps its title. Don't
  offer to rename it.
- `relink` keeps the note's version and sync state, so status reads as before the rename.
  It refuses a note whose properties carry another page id.
- `unlink` leaves the Confluence page alone and keeps the page's saved copy, so the note
  can be linked again later.

"Keep for now" changes nothing. The line comes back on the next status, and the morning
daily note keeps flagging it as **Link lost**.

## New pages on Confluence

A whole-vault status lists, as `NEW:` and `NEW FOLDER:` lines, what was created lately
under the linked folders and pages and is not in the vault. Take them one at a time, and
ask before each one:

| Ask | On yes |
|---|---|
| "`<title>` by `<who>` is new in `<folder>`. Add it to the vault?" Offer **Add**, **Ignore** and **Later** | `conf.py add <id>` |
| For a folder: "Folder `<title>` is new in `<folder>`, with K pages. Add it with its pages?" | `conf.py add <id>` (one command brings them all) |
| **Ignore** | `conf.py ignore <id>` |

- `add` makes the note in the folder the line names, named after the page title, links it
  and pulls it. Folders on the way that the vault does not have yet are made and linked
  too. It never writes over a note: if one has that name, it stops and says how to link it
  by hand. It backs up `mapping.json` and `folders.json` first.
- `ignore` remembers the id in `.confsync/ignored.json`, with everything under it for a
  folder. To undo, remove it from that file.
- **Later** changes nothing: the line comes back on the next status while the page is less
  than 14 days old.
- Nothing is sent to Confluence either way.

## After linking

Nothing is published. `link` only writes `mapping.json` / `folders.json` and the note's
frontmatter, then pulls. The user's next move is usually to edit and push - hand off to
the confluence-push skill, which owns the confirmation for that.
