# Content transforms reference

The sync pipeline converts between Obsidian-friendly Markdown and Confluence storage
format. Transforms run in both directions where possible.

## Jira issues (push only, pull keeps links)

Local syntax (compatible with the obsidian-jira-issue plugin):

    ```jira-issue
    MYLE-27787
    PT-1794
    ```

    Inline bare keys also work: "blocked by RD-100" (only for project keys listed in
    .confsync/config.json → jira_project_keys).

On push both become plain `<a href="https://<site>/browse/KEY">` links. Confluence Cloud
auto-renders links to its own Jira site as smart links with live status — visually
equivalent to the Jira macro. On pull they come back as markdown links `[KEY](url)`;
the obsidian-jira-issue plugin does not re-detect those automatically, so inline rendering
in Obsidian works best if you keep using the fence/bare-key syntax for new content.

## Mentions

Local syntax: `@alias` or `@[Full Name]` (alias must exist in `.confsync/users.json`).

    users.json: { "antoine": { "account_id": "5f...", "display_name": "Antoine Sifoni" } }

Push: converted to `<ac:link><ri:user ri:account-id="..."/></ac:link>` — a real mention
that NOTIFIES the person. Unknown aliases are left as plain text with a warning.
Pull: mentions convert back to `@alias` (or `@<accountId>` if not in users.json).

Populate the map with: `conf.py users "name" --add`.

## Diagrams: PlantUML and Mermaid

Local syntax:

    ```plantuml
    Alice -> Bob: hello
    ```

    ```mermaid
    graph TD; A-->B;
    ```

Push, always, regardless of local tooling: the fence's raw source goes into an "expand"
(collapsible) section on the page, titled `PlantUML source (confsync)` or
`Mermaid source (confsync)`. Nothing is ever silently dropped.

PlantUML additionally renders a PNG when `java` is available and `plantuml.jar` is
placed in `<vault>/.confsync/` (download from https://plantuml.com/download):
1. The fence is rendered to PNG locally (no server call).
2. PNG uploaded as a page attachment (create-or-update, stable filename per block index).
3. The image is shown directly above the collapsible source section.

Mermaid has no local renderer in this plugin, so it's always text-only (no image).

Pull: a block tagged `PlantUML source (confsync)` or `Mermaid source (confsync)` is
converted back into an inline ```plantuml / ```mermaid fence — any rendered image above
it is dropped locally (Obsidian's own PlantUML/Mermaid plugins re-render from the fence).

If the company Confluence has a PlantUML or Mermaid macro app installed, a future version
can push the source into that macro instead — check by typing /plantuml or /mermaid in
the Confluence editor.

## Frontmatter (Obsidian properties)

A YAML frontmatter block is maintained at the top of every linked note:

    ---
    title: PT-1778: RBAC - Charting PPR
    page_id: "5593530380"
    confluence_version: 7
    parent_page_id: "5534646345"
    confluence_space: PD
    confluence_url: https://medfar.atlassian.net/wiki/spaces/PD/pages/5593530380/...
    up: "[[PT-1778 - RBAC - Product Preliminary Review (PPR)]]"
    last_modified: "2026-07-15"
    author: antoine
    ---

`link`, `pull`, and `push` all rewrite these 9 keys from live Confluence metadata; the
body content below the block is untouched by this transform. Manual properties (any key
outside that set) are preserved as-is. `push` strips the frontmatter block before
converting the body to storage format, so it never gets published onto the Confluence
page itself.

## Known lossy cases (round-trip warnings)

- Confluence-native macros (status lozenges, page properties, TOC, children display),
  layouts/columns, and inline comments do not survive storage → markdown conversion.
- Complex tables (merged cells, colored cells) flatten to plain markdown tables.
- Rule of thumb: pages owned by this workflow should stay "markdown-shaped". For pages
  heavily authored in Confluence, pull once, inspect, and decide whether to adopt them.

## Not implemented: Confluence-native chrome (deferred, not rejected)

Three Confluence constructs have no markdown equivalent today, so a page using them
loses them on push. They are listed here because the project templates were originally
written around them, and because the fix is well understood if it ever becomes worth
doing.

| Construct | Storage format | Possible local syntax |
|---|---|---|
| Status lozenge | `<ac:structured-macro ac:name="status">` with a `colour` parameter | an inline code span, e.g. `` `status:green:High` `` |
| Task list | `<ac:task-list><ac:task>` with `<ac:task-status>` | GitHub-style `- [ ]` / `- [x]`, which Obsidian already renders |
| Decision list | `<ac:structured-macro ac:name="decision-list">` | a fenced `decision` block, one item per line |

Task lists are the strongest candidate: `- [ ]` already renders as a real checkbox in
Obsidian *and* has a native Confluence counterpart, so a transform would be a genuine
round-trip rather than a one-way flattening. Status lozenges are the weakest - the local
syntax is invented either way, and a plain word ("High") reads fine in Obsidian.

Current behaviour is a one-way flatten: markdown pushes as plain text, and any lozenge or
decision list authored in Confluence is dropped on pull. That is a deliberate default
given the templates are read in Obsidian far more often than in Confluence.
