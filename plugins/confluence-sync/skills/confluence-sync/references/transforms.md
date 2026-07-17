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

## PlantUML

Local syntax:

    ```plantuml
    Alice -> Bob: hello
    ```

Push, when `java` is available and `plantuml.jar` is placed in `<vault>/.confsync/`
(download from https://plantuml.com/download):
1. Each fence is rendered to PNG (runs locally, no server).
2. PNG uploaded as a page attachment (create-or-update, stable filename per block index).
3. Page shows the image + an "expand" section titled `PlantUML source (confsync)`
   containing the source, so nothing is lost and pull can round-trip it.

Push without the jar: the fence becomes a code block on the page titled
"plantuml (not rendered)". Content is preserved either way.

Pull: blocks tagged `PlantUML source (confsync)` are converted back into ```plantuml
fences (the rendered image is dropped locally — Obsidian's PlantUML plugin re-renders it).

If the company Confluence has a PlantUML macro app installed, a future version can push
the source into that macro instead — check by typing /plantuml in the Confluence editor.

## Known lossy cases (round-trip warnings)

- Confluence-native macros (status lozenges, page properties, TOC, children display),
  layouts/columns, and inline comments do not survive storage → markdown conversion.
- Complex tables (merged cells, colored cells) flatten to plain markdown tables.
- Rule of thumb: pages owned by this workflow should stay "markdown-shaped". For pages
  heavily authored in Confluence, pull once, inspect, and decide whether to adopt them.
