---
name: confluence-sync
description: >
  Git-like sync between local Markdown files (Obsidian vault) and Confluence Cloud pages,
  and creation of new Confluence pages, folders, or a whole page tree from a spec.
  Use whenever the user asks to pull, push, sync, link, or check the status of Confluence pages
  against local notes, mentions "conf pull", "conf push", version conflicts with Confluence,
  or wants to publish a note to Confluence with a version message. Also use when they want to
  CREATE a new Confluence page or folder from a vault note, or scaffold a nested structure in
  Confluence and Obsidian at once. Also use to look up Confluence users for the mentions map.
---

# Confluence Sync

Sync local Markdown files with Confluence Cloud pages using `scripts/conf.py`, treating
Confluence like a git remote: the mapping file stores the last-synced version number per
file, and every push is optimistically locked against it.

## Setup check (first use in a vault)

1. Verify env vars are set: `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`.
   If missing, tell the user how to create a token (id.atlassian.com → Security → API tokens)
   and to export the three variables. Never ask the user to paste the token in chat.
2. Verify Python deps: `pip install -r ${CLAUDE_PLUGIN_ROOT}/skills/confluence-sync/scripts/requirements.txt`
3. State lives in `<vault>/.confsync/` (config.json, mapping.json, users.json). The script
   finds the vault root by walking up to the nearest `.confsync` directory; create it on
   first use. Recommend adding `.confsync/` and `*.remote.md` to the vault's `.gitignore`
   only if the user does NOT want sync state versioned (usually they DO want mapping.json
   in git so the team shares page links — ask once).
4. Set `jira_project_keys` in `.confsync/config.json` (e.g. `["RD","MYLE","CW","MCA","NPI","PT"]`)
   so bare issue keys become Jira links on push.

## Commands

Run with `python3 ${CLAUDE_PLUGIN_ROOT}/skills/confluence-sync/scripts/conf.py <cmd>` from
inside the vault.

- `link <file.md> <pageId>` — map a local file to an existing Confluence page. Page ID is
  the number in the page URL (`.../pages/<pageId>/Title`).
- `status [file]` — compare local hash + remote version for one or all linked files.
  Run this before pull/push when the user is unsure of state.
- `pull <file>` or `pull --all` — download remote as markdown. If the local file has
  uncommitted edits AND the remote moved, the script writes `<file>.remote.md` instead of
  overwriting, and reports a conflict.
- `push <file> -m "version message"` — upload. Aborts if the remote version moved since
  last sync (someone else edited). Always pass `-m`; if the user gave no message, propose
  one summarizing the diff and confirm it.
- `users <query> [--add]` — search Confluence users; `--add` stores them in users.json
  as `@firstname` aliases for mentions.
- `link-folder <folder> <folderId>` — map a local Obsidian folder to an existing
  Confluence *folder* (the organizational container, not a page - no body content).
  Folder id is the number in `.../wiki/spaces/<space>/folder/<folderId>`.

### Creating (as opposed to linking)

`link`/`link-folder` attach to something that already exists. These make new ones and
link them in the same step:

- `create-page <file.md> --parent <id> [--title T] [--space <id>|personal]` — create a new
  Confluence page from a local note (empty note is fine) and link it. `--parent` accepts a
  page id **or** a folder id. Title defaults to the filename.
- `create-folder <dir> --parent <id> [--title T] [--space <id>|personal]` — create a new
  Confluence folder, create the matching local directory, and link them.
- `scaffold <spec.yaml> [--parent <id>] [--space ...] [--dry-run]` — create a whole nested
  tree in one pass. **This is the command to use for a new project.** See below.
- `rebaseline [--check]` — one-time migration of `mapping.json` entries written by
  v0.3.0 or earlier to body-only hashing (see below). `--check` reports without writing.
  Touches only `mapping.json`: never contacts Confluence, never modifies a note.

## Change detection: the hash covers the body, not the frontmatter

`mapping.json` stores a hash of each note so `status` and `pull` can tell whether you
have local edits. Since v0.4.0 that hash covers the **markdown body only** and ignores
YAML frontmatter entirely (entries are tagged `"hash_algo": "body1"`).

Why: `push` strips frontmatter before uploading, so frontmatter can never be
push-relevant. Hashing it meant Obsidian's Properties panel reformatting the YAML
(it writes block sequences at 2-space indent and double quotes, PyYAML writes them at
zero indent with single quotes, so the two never agree) flipped every synced note to
"local changes (push needed)" within seconds of being pulled.

That mattered beyond noise: a permanently-dirty flag also poisoned the pull conflict
check, which fires on `local_dirty AND remote moved`. Clean pulls became spurious
CONFLICTs demanding a manual merge, and genuine local edits became indistinguishable
from formatter noise.

Consequences to know:
- A change to a **manual** frontmatter property (e.g. your own `status: draft`) no
  longer shows as "push needed". That is correct, since push would not upload it and
  pull preserves it, so nothing can be lost.
- `status` flags any entry still on the old whole-file hash and points at `rebaseline`.
  Migration is deliberately manual, not silent: a note could hold a genuine un-pushed
  edit made before the upgrade, and a silent re-baseline would bury it. Review the
  flagged files first, then run `rebaseline`.

## Scaffolding a new structure (`scaffold`)

`scaffold` reads a YAML (or JSON) spec describing a tree, then walks it parents-first,
creating each node in Confluence and mirroring it into the vault at the matching path.

```yaml
space: "103514172"        # optional. an id, or "personal". omit to inherit from parent
parent: "1154842646"      # optional. page id OR folder id. omit to land at space root
base: "Confluence Projects"   # optional. vault-relative dir the tree is created under
tree:
  - type: folder
    title: "PT-1947 - CNESST, Obstetrical Files"
    children:
      - type: page
        title: "PT-1947 - Read Me"
        body: |
          ## Informations
          ...markdown...
      - type: folder
        title: "PT-1947 - Initial Analysis"
        children:
          - type: page
            title: "PT-1947 - User Interviews"
```

- Local path mirrors the Confluence tree: folder nodes become directories, page nodes
  become `<title>.md` inside their parent directory. Characters Confluence allows in a
  title but Windows forbids in a filename (`: / \ ? * " < > |`) are replaced with `-`;
  set `name:` on a node to control the local basename explicitly.
- Only folders can have `children` — a page with children is an error, not a silent
  reparent. Nest under a folder instead.
- `body:` seeds the local note before creation. It is skipped if the file already exists,
  so a hand-written note is never clobbered by the spec.
- **Idempotent.** A node whose local path is already in `mapping.json`/`folders.json` is
  skipped and its existing id reused as the parent for its children. If a run dies
  halfway (network, permissions, a duplicate title), just re-run the same spec.
- **Always `--dry-run` first** and show the user the tree. Creating 15 pages in the wrong
  parent is annoying to undo.
- The Medfar project tree ships as `templates/project.yaml`. For a new project, start
  there rather than hand-writing a spec — see "Creating a new project" below.

### Spec templating

A spec can carry variables and a per-team split, so one template serves every project.

```yaml
variables:
  key: "PT-1947"                 # Jira key. prefixes every title
  name: "CNESST, Obstetrical Files"
  teams: []                      # [] = single team. ["Charting","L&D Rx"] = per-team split
parent: "1154842646"
base: "Confluence Projects"
frontmatter:                     # merged into every note as manual properties
  tags: ["{key}"]
tree: ...
```

Override any variable from the command line: `--set key=PT-1947 --set teams=Charting,"L&D Rx"`
(`teams` is comma-split; every other value is taken literally). `--set` beats the spec.

**Title convention.** A node's title renders as `"{key} - {title}"`, or
`"{key} - {team} - {title}"` inside a team subtree. The team segment is not decoration:
Confluence enforces unique page titles per space, so two teams sharing a leaf title like
`Scope definition` would fail on creation. `raw: true` opts a node out of the prefix
entirely — that is how `CLAUDE.md` keeps its exact filename.

**`repeat_per_team`.** Put it on a folder titled `"{team}"`. That folder is emitted once
per team, and everything beneath it inherits the team segment. With `teams: []` the folder
**collapses** and splices its children into its parent, so single-team mode reads exactly
like the tree as written (bar nodes gated with `when:`, below). Unknown `{placeholders}` are left verbatim so a typo shows up in
the dry run instead of silently producing a half-empty title.

**`when`.** `single_team` or `multi_team` on any node drops it, and its whole subtree, in
the other mode. Needed because a collapsing `repeat_per_team` wrapper splices its children
into its *immediate* parent — so a node that belongs at a different depth once the wrapper
disappears cannot be expressed by placement alone. Write it twice and gate each copy.
`project.yaml` uses this for `Dev`: one project-level folder beside `Product Owner` for a
single-team project, one Dev per team inside `Product Owner` when there are several. Any
other value is an error, caught in the dry run.

**`target`.** `both` (default) creates in Confluence and in the vault. `obsidian` creates
a local note only — never pushed, never linked, absent from mapping.json. Use it for
`CLAUDE.md` and any working note that should not reach the wiki. There is deliberately no
Confluence-only target: mapping.json is keyed by local path, so a page with no note behind
it could not be tracked, pushed, or pulled.

**Only folders can have children.** A page with children is an error, not a silent
reparent. If a section needs both a body and children, make it a folder plus a page
inside it.

### The `up` anchor

Obsidian wikilinks can only point at notes, and in a folders-only tree a page's parent is
almost always a *folder* — which has no note behind it. So `up` would be empty on nearly
every page. Instead, one page is the anchor (`anchor: true`, defaulting to the first
synced page in the tree, i.e. the project's Read Me) and every other note's `up` points
there.

The anchor is stored per entry in mapping.json as `up_note`, so it survives every later
pull and push. It is *not* derived from Confluence ancestry, because the anchor is
typically a sibling of the folders rather than an ancestor of anything — ancestry can
never find it.

### Where does it go?

Space and parent resolve in this order: an explicit `--space` wins; otherwise the space is
inherited from `--parent` (so a single page id is usually all you need); with no parent at
all, the tree lands at the root of the user's personal space.

**Ask the user for the parent if they did not say where.** Do not guess a parent. If they
still give nothing after being asked, fall back to the personal space (`--space personal`).

## Creating a new project

This is the flow when the user says "create a new project", "set up PT-1947", "scaffold
the Confluence structure for X". The tree ships as `templates/project.yaml`.

### 1. Collect four things

| Variable | Notes |
|---|---|
| `key` | Jira key, e.g. `PT-1947`. Extract it from a Jira link if one was given. Required — every title is prefixed with it. |
| `name` | Project name without the key, e.g. `CNESST, Obstetrical Files`. |
| `parent` | Confluence page or folder id the project nests under. |
| `teams` | Omit for a single-team project. Otherwise the list, e.g. `Charting, L&D Rx`. |

Ask for whatever was not in the prompt, in **one** batch of questions, not one at a time.

**On `parent`:** ask where it goes; do not guess. Real projects live under a product page
in the PD space (`MYLE`, `CareWay`, `Careway Mobile`), so offering those as options is
usually right. If the user still gives nothing after being asked, fall back to their
personal space with `--space personal` and say that is what you did.

### 2. Dry run, then confirm

```
conf.py scaffold <plugin>/skills/confluence-sync/templates/project.yaml \
  --set key=PT-1947 --set "name=CNESST, Obstetrical Files" \
  --set "teams=Charting,L&D Rx" --parent 1154842646 --dry-run
```

Show the user the whole tree it prints and get an explicit yes. A 24-page tree in the
wrong parent is tedious to unpick — there is no undo command.

### 3. Create

Same command without `--dry-run`. If it dies partway (a duplicate title, a permissions
error), fix the cause and **re-run the identical command** — already-created nodes are
skipped, so it resumes rather than duplicating.

### 4. Report

Give the user the root page URL (in the Read Me note's `confluence_url` frontmatter) and
mention the tree is now live in both places.

### Customising per project

Do not edit `templates/project.yaml` for a one-off. Copy it into the vault, adjust, and
scaffold from the copy. Reserve edits to the shipped template for changes that should
apply to every future project.

Adding a team later is safe: re-run with the fuller `--set teams=...` and only the new
team's branch is created.

## Folder name sync (one-way, Confluence wins)

Confluence folders have no body to conflict on, so this is simpler than page sync: on
every `pull --all`, each linked folder's local directory is renamed to match the
Confluence folder's *current* title if it has drifted. Local renames are never pushed
back - Confluence is the source of truth for folder names, matching this vault's
"Confluence as company source of truth" setup.
- Runs only as part of `pull --all`, not a single-file `pull` (renaming a directory is
  more disruptive than editing a note, so it only happens on the deliberate full-sync).
- A rename cascades: every mapping.json/folders.json entry nested under the renamed
  folder gets its path rewritten too, so linked pages inside it don't go stale.
- If the target name already exists locally, the rename is skipped with a warning
  instead of overwriting - resolve by hand, then re-run `pull --all`.

## Conflict handling

When pull reports a conflict:
1. Show the user a diff between `<file>.md` and `<file>.remote.md` (`git diff --no-index`
   or read both and summarize the differing sections).
2. Help merge: propose a merged version and, on approval, write it to `<file>.md` and
   delete `<file>.remote.md`.
3. Publish the merge with `push <file> --force -m "merge: ..."` — force is legitimate
   here because the merged content already contains the remote edits. Confirm with the
   user before running it.
4. In any other situation, never use `--force` (pull or push) without explicit user
   confirmation — it discards someone's work.

## Frontmatter properties (automatic on link/pull/push)

Every `link`/`pull`/`push` rewrites a block of YAML frontmatter at the top of the note so
the Confluence linkage is visible in Obsidian's Properties panel, not just in mapping.json:
`title`, `page_id`, `confluence_version` (the page's current Confluence version number),
`parent_page_id`, `confluence_space`, `confluence_url`, `up`, `last_modified`, `author`.

`up` is a `[[wikilink]]` to the parent note when the parent is itself a linked page. When
the parent is a *folder* (which has no note, so nothing to link) it falls back to the
scaffold's anchor note, stored per entry in mapping.json as `up_note` — see "The `up`
anchor" above.

- These 9 keys are fully owned by confsync and regenerated every sync — **don't hand-edit
  them**, edits will be overwritten on the next pull/push. Any other frontmatter property
  already on the note is left alone.
- That is what makes the spec's `frontmatter:` block stick: `tags` and anything else it
  writes sit outside the owned set, so every later pull and push preserves them.
- `mapping.json` is still the actual source of truth for the optimistic-lock `version`/
  `hash` (frontmatter is a display mirror only), so a stray edit to `page_id` in Obsidian
  can't corrupt sync state — it'll just get corrected on the next sync. Frontmatter is
  also excluded from the change hash, so reformatting it never reads as a local edit.
- `author` resolves the last editor's Confluence account id through `users.json`, same as
  mentions; if it shows a raw account id, add that person with `users <name> --add`.

## Content transforms (automatic on push/pull)

See `references/transforms.md` for details. Summary:
- Jira: ```jira-issue fences and bare keys (RD-123) ↔ Jira links (render as smart links).
- Mentions: `@alias` / `@[Full Name]` ↔ real Confluence mentions via users.json.
  Push warns on unknown aliases; offer to run `users <name> --add`.
- Diagrams: ```plantuml / ```mermaid fences → always pushed as a collapsible section
  containing the raw source (title `"<Lang> source (confsync)"`). PlantUML additionally
  renders a PNG shown above the section when java + `plantuml.jar` are available in
  `.confsync/`; Mermaid has no local renderer, so it's always text-only. On pull, either
  comes back as an inline ```plantuml / ```mermaid fence (a plain fence is what "a
  section in the text" means once it's markdown — the image, if any, is dropped locally).

## Safety rules

- Pushing publishes to the company wiki and mentions notify people: before any push,
  state the target page title and version message and get user confirmation.
- Creation is publishing too. Before `create-page`/`create-folder`/`scaffold`, state the
  target space, the parent, and the full list of titles, and get user confirmation. For
  `scaffold` that means showing the `--dry-run` output first.
- There is no `delete` command on purpose. If a scaffold went to the wrong place, tell the
  user which pages/folders to remove in Confluence rather than removing them yourself.
- Round-tripping is lossy for complex Confluence content (macros, layouts, statuses).
  Warn the user before the FIRST push to a page that was authored in Confluence:
  recommend pulling first and checking the markdown looks complete.
- Never print or log the API token.
