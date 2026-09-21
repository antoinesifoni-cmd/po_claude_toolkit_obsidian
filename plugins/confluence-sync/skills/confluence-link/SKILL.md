---
name: confluence-link
description: >
  Connects a local Markdown note or folder (in an Obsidian vault) to a Confluence Cloud page
  or folder, or creates the Confluence page/folder when it does not exist yet. This skill
  should be used when the user pastes a Confluence URL and wants a note attached to it, or
  says "link this note to that page", "connect this folder to Confluence", "find the page
  called X", "this note should live at <URL>", "create a Confluence page for this note", or
  reports that a note is "not linked". It also covers looking up a page or folder id by
  title. For syncing content on already-linked notes, use confluence-pull or confluence-push
  instead.
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
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py create-page   <file.md> --parent <id> [--title T]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/conf.py create-folder <dir>     --parent <id> [--title T]
```

Both create the Confluence side, create or reuse the local side, and link them in one
step. `--parent` takes a page id or a folder id.

**Creating is publishing.** Before running either, state the target space, the parent, and
the exact title, and get an explicit yes. Ask where it goes rather than guessing a parent;
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

## After linking

Nothing is published. `link` only writes `mapping.json` / `folders.json` and the note's
frontmatter, then pulls. The user's next move is usually to edit and push - hand off to
the confluence-push skill, which owns the confirmation for that.
