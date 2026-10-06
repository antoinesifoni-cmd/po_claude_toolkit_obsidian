# Creating Confluence content

`link` attaches to something that already exists. These commands make new things and link
them in the same step. All of them publish, so all of them need confirmation first.

Single pages and folders are covered by the **confluence-link** skill. This file is the
full reference, including `scaffold`, which has no skill of its own - deciding to stand up
a whole project tree is a process decision, not a sync one.

## create-page / create-folder

```
conf.py create-page   <file.md> --parent <id> [--title T] [--space <id>|personal]
conf.py create-folder <dir>     --parent <id> [--title T] [--space <id>|personal]
```

`--parent` takes a page id **or** a folder id - Confluence accepts either as a parent.
Title defaults to the filename. An empty local note is fine.

**Where it goes.** An explicit `--space` wins; otherwise the space is inherited from the
parent, so a single page id is usually all that's needed; with no parent at all, content
lands at the root of the user's personal space. Ask where it goes - do not guess a parent.
If they still don't say, use `--space personal` and tell them.

## scaffold

```
conf.py scaffold <spec.yaml> [--parent <id>] [--space ...] [--set K=V] [--dry-run]
```

Reads a YAML (or JSON) spec describing a tree, walks it parents-first, creates each node in
Confluence and mirrors it into the vault at the matching path.

**Always `--dry-run` first and show the user the whole tree.** There is no undo command; a
24-page tree in the wrong parent is tedious to unpick by hand.

**Idempotent.** A node whose local path is already in `mapping.json`/`folders.json` is
skipped and its existing id reused as the parent for its children. If a run dies halfway -
network, permissions, a duplicate title - fix the cause and re-run the identical command.
It resumes instead of duplicating.

```yaml
space: "103514172"            # optional. an id, or "personal". omit to inherit from parent
parent: "1154842646"          # optional. page id OR folder id. omit to land at space root
base: "Confluence Projects"   # optional. vault-relative dir the tree is created under
tree:
  - type: folder
    title: "PT-1947 - CNESST, Obstetrical Files"
    children:
      - type: page
        title: "PT-1947 - Read Me"
        body: |
          ## Informations
```

- Local path mirrors the Confluence tree: folders become directories, pages become
  `<title>.md` inside their parent directory. Characters Confluence allows but Windows
  forbids (`: / \ ? * " < > |`) become `-`; set `name:` to control the basename.
- **Only folders can have children.** A page with children is an error, not a silent
  reparent. If a section needs a body *and* children, make it a folder with a page inside.
- `body:` seeds the local note before creation, and is skipped if the file already exists -
  a hand-written note is never clobbered by the spec.

### Spec templating

```yaml
variables:
  key: "PT-1947"              # Jira key. prefixes every title
  name: "CNESST, Obstetrical Files"
  teams: []                   # [] = single team. ["Charting","L&D Rx"] = per-team split
frontmatter:
  tags: ["{key}"]             # merged into every note as manual properties
```

Override from the command line: `--set key=PT-1947 --set teams=Charting,"L&D Rx"`. `teams`
is comma-split; every other value is literal. `--set` beats the spec.

**Title convention.** Titles render as `"{key} - {title}"`, or `"{key} - {team} - {title}"`
inside a team subtree. The team segment isn't decoration: Confluence enforces unique page
titles per space, so two teams sharing a leaf title like `Scope definition` would fail on
creation. `raw: true` opts a node out of the prefix entirely - that's how `CLAUDE.md` keeps
its exact filename.

**`repeat_per_team`.** Goes on a folder titled `"{team}"`. That folder is emitted once per
team and everything beneath it inherits the team segment. With `teams: []` the folder
*collapses*, splicing its children into its parent, so single-team mode reads exactly like
the tree as written. Unknown `{placeholders}` are left verbatim, so a typo shows up in the
dry run instead of producing a half-empty title.

**`when`.** `single_team` or `multi_team` drops a node and its subtree in the other mode.
Needed because a collapsing wrapper splices into its *immediate* parent, so a node that
belongs at a different depth once the wrapper disappears can't be expressed by placement
alone - write it twice and gate each copy. `project.yaml` doesn't need it: everything
per-team sits inside the team folder, so collapsing puts it at project level.

**`target`.** `both` (default) creates in Confluence and the vault. `obsidian` creates a
local note only - never pushed, never linked, absent from `mapping.json`. Use it for
`CLAUDE.md` and working notes that shouldn't reach the wiki. There is deliberately no
Confluence-only target: `mapping.json` is keyed by local path, so a page with no note
behind it couldn't be tracked.

### The `up` anchor

Obsidian wikilinks can only point at notes, and in a folders-only tree a page's parent is
almost always a *folder*, which has no note. So `up` would be empty on nearly every page.
Instead one page is the anchor (`anchor: true`, defaulting to the first synced page in the
tree - the Read Me) and every other note's `up` points there.

The anchor is stored per entry in `mapping.json` as `up_note`, so it survives later pulls
and pushes. It is not derived from Confluence ancestry, because the anchor is typically a
sibling of the folders rather than an ancestor of anything.

## Creating a new project

The Medfar project tree ships as `${CLAUDE_PLUGIN_ROOT}/templates/project.yaml`. Start
there rather than hand-writing a spec.

Collect four things, asking for whatever wasn't in the prompt in **one** batch:

| Variable | Notes |
|---|---|
| `key` | Jira key, e.g. `PT-1947`. Extract from a Jira link if one was given. Required. |
| `name` | Project name without the key, e.g. `CNESST, Obstetrical Files`. |
| `parent` | Confluence page or folder id the project nests under. |
| `teams` | Omit for single-team. Otherwise the list, e.g. `Charting, L&D Rx`. |

Real projects live under a product page in the PD space (`MYLE`, `CareWay`,
`Careway Mobile`), so offering those is usually right.

```
conf.py scaffold ${CLAUDE_PLUGIN_ROOT}/templates/project.yaml \
  --set key=PT-1947 --set "name=CNESST, Obstetrical Files" \
  --set "teams=Charting,L&D Rx" --parent 1154842646 --dry-run
```

Show the printed tree, get an explicit yes, then re-run without `--dry-run`. Report the
root page URL afterwards (it's in the Read Me note's `confluence_url` frontmatter).

**Customising.** Don't edit the shipped template for a one-off - copy it into the vault,
adjust, and scaffold from the copy. Reserve template edits for changes that should apply
to every future project. Adding a team later is safe: re-run with the fuller
`--set teams=...` and only the new branch is created.
