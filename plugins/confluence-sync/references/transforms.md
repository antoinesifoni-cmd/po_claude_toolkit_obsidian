# Content transforms reference

The sync converts between Obsidian Markdown and Confluence storage format. Every pair
below round-trips: push a note, pull it back, and the Markdown is identical. Each pair was
checked against what Confluence Cloud actually stores (2026-10-28) and is covered by
`scripts/tests/test_transforms.py`.

The code is `scripts/confsync/transforms.py`, both directions side by side.

## At a glance

| Obsidian | Confluence |
|---|---|
| `> [!info]` `> [!note]` `> [!warning]` `> [!success]` `> [!error]` | Info (blue), Note (purple), Warning (yellow), Success (green), Error (red) panel |
| `> [!panel\|#EAE6FF\|:note:\|atlassian-note]` | Custom panel (colour, icon) |
| `> [!decision]` + one `- item` per decision | Decision list |
| `> [!expand]- Title` | Expand (collapsible) section |
| `- [ ] task` / `- [x] task` | Task list, open / done |
| `📅 2026-11-03` | Date pill |
| `` `🟢 In scope` `` | Status lozenge (⚪ grey, 🔵 blue, 🟢 green, 🟡 yellow, 🔴 red, 🟣 purple) |
| `![[image.png\|409]]` | Image attachment, 409 px wide |
| `*Caption: text*` on the line under an image | Image caption |
| `![](https://...)` | Image from a URL |
| `[[Note]]` / `[[Note\|text]]` / `[[Note#Heading]]` | Link to the note's linked page |
| `@alias` / `@[Full Name]` | User mention (notifies) |
| `PT-1794`, ` ```jira-issue ` fence | Jira smart link with live status |
| `<https://figma.com/...>` | Smart link (Jira, Confluence, Figma, Google, Lucid) |
| ` ```json ` | Code block with its language |
| ` ```mermaid ` | Diagram drawn by the Mermaid app + source section |
| ` ```plantuml ` | PNG (if java + plantuml.jar) + source section |
| `~~text~~` `==text==` `<u>text</u>` | Strikethrough, highlight, underline |
| `:shortcode:` / 😄 | Atlassian emoji / standard emoji |
| `%%confluence:toc%%` / `%%confluence:children%%` | Table of contents / Child pages macro |
| `%%confluence-keep:<id> Label%%` | Anything else, kept untouched (see Safety net) |

## Safety net: content with no Markdown is kept, not dropped

Pull turns anything it can't express in Markdown into one marker, and saves the exact XML
in `.confsync/keep/<id>.xml`:

    %%confluence-keep:b525c0db1d Table of contents%%

`%%...%%` is an Obsidian comment: hidden in reading view, one grey line while editing.
Push swaps the marker back for the saved XML, so the macro survives. You can move the
marker, or delete it to remove the macro from the page.

What ends up kept: app macros (Google Sheets, Jira roadmap cards), tasks reports, template
placeholder text, layouts, embed/block cards, links to attachments, and any panel, task
list, decision or expand **inside a table cell** (a Markdown table cell can't hold them).

A macro pull knows is still kept whole if it carries a setting pull can't express (for
example an old panel with a title). Settings Confluence picks by itself (`containerLevel`,
`wrap`, `breakoutWidth`, `breakoutMode`, `mixedCase`) are dropped.

## Panels = callouts

| Callout | Storage |
|---|---|
| `info` | `<ac:structured-macro ac:name="info">` |
| `success` (also `tip`, `hint`, `important`, `check`, `done`) | `ac:name="tip"` |
| `warning` (also `caution`, `attention`) | `ac:name="note"` |
| `error` (also `danger`, `failure`, `fail`, `missing`, `bug`) | `ac:name="warning"` |
| `note` (purple) | `<ac:adf-extension>` panel node, `panel-type` = `note` |
| `panel\|bg\|icon\|icon-id\|icon-text` | `ac:name="panel"` with `bgColor`, `panelIcon`, `panelIconId`, `panelIconText` |

- Aliases come back as the main name (`[!tip]` comes back `[!success]`).
- Confluence panels have no title. A callout title (`> [!info] Heads up`) is pushed as a
  bold first line and comes back as `> **Heads up**`.
- Other Obsidian callout types (`quote`, `question`, `example`...) stay plain quotes.

## Decisions

    > [!decision]
    > - Use FHIR R4 for the alert engine
    > - Keep RBAC roles per clinic

Each bullet is one decision item, state DECIDED. An empty `-` keeps an empty item.
`decision` is a custom callout type. For a Confluence-like look in Obsidian, add a CSS
snippet such as:

    .callout[data-callout="decision"] { --callout-color: 54, 179, 126; --callout-icon: lucide-git-merge; }

## Tasks and dates

- `- [ ]` / `- [x]` at the start of a line, consecutive lines form one task list. Other
  statuses (`[/]`, `[-]`) are not tasks in Confluence and stay text.
- `📅 YYYY-MM-DD` is the Tasks plugin due date and maps to the Confluence date inside the
  task. It works anywhere in the text too. Plain ISO dates without 📅 stay text.
- Other Tasks plugin markers (⏳ ➕ 🔁 ✅ and block ids) stay plain text.

## Status lozenges

An inline code span that starts with one of the six dots is a status. Any other code span
stays code. Custom hex colours (set in Confluence) snap to the closest dot on pull.

## Images

- Push uploads the file as a page attachment, only when its content changed
  (`.confsync/attachments.json` keeps the content hash). The file is found the way Obsidian
  finds it: a path, the note's folder, the attachment folder, then anywhere in the vault.
- Pull downloads new or changed attachments into the vault's attachment folder
  (Obsidian Settings > Files and links). If a different file already has that name, the
  download is saved as `name (<page id>).png` and the link between the two names is kept
  in `attachments.json`.
- Width round-trips. Alignment is not kept (Confluence centres).
- Inside a table, write `![[image.png\|200]]` (escaped pipe), the way Obsidian does.
- A page that has images is created empty first, then pushed, because uploads need a page.

## Links

- `[[Note]]` becomes a page link only if `Note` is linked to a page (in `mapping.json`).
  Otherwise it is pushed as plain text, as before. The target's space comes from its
  `confluence_space` property.
- A link to a page that isn't in the vault comes back as a URL,
  `https://<site>/wiki/display/SPACE/Page+Title`, which pushes back as a page link.
- Smart links: a bare URL (`<https://...>`) to Jira, Confluence, Figma, Google Docs/Sheets/
  Drive or Lucid is pushed as an inline smart link. A link with its own text stays a normal
  link. Jira links made from issue keys are smart links too, and come back as the bare key.
- Jira keys inside URLs, link targets and code are left alone.

## Diagrams

Push puts the source in an expand section titled `PlantUML source (confsync)` or
`Mermaid source (confsync)`, always.

- **Mermaid**: the "Mermaid diagram" app (Forge, installed at Medfar) draws the diagram
  live. Push adds its macro right above the source section, pointing at that code block by
  position (the app counts every code block on the page). Set `"mermaid_app": false` in
  `.confsync/config.json` to push the source only.
- **PlantUML**: a PNG is rendered locally when `java` is available and `plantuml.jar` is in
  `.confsync/`, uploaded, and shown above the source.
- Pull turns the source section back into the fence and drops the rendered image and the
  app macro. A diagram made by hand in Confluence with the Mermaid app (code block + app
  macro) also comes back as a ` ```mermaid ` fence.
- The app runs Mermaid 11.15.0. Obsidian's renderer (Pele) follows Mermaid 12.1.0, so
  syntax newer than 11.15 draws in Obsidian but errors on Confluence.

## Emoji

Standard emoji are plain characters both ways. Atlassian-only emoji (`:flag_on:`) come back
as their shortcode, remembered in `.confsync/emoji.json`, and push turns the shortcode back
into the emoji.

## Mentions

`@alias` or `@[Full Name]`, alias in `.confsync/users.json`:

    users.json: { "antoine": { "account_id": "5f...", "display_name": "Antoine Sifoni" } }

Push makes a real mention that **notifies** the person. Unknown aliases stay text with a
warning, and an `@` inside an email address or code is never a mention. Pull writes
`@alias`, or `@<accountId>` if the person isn't in users.json. Populate the map with
`conf.py users "name" --add`.

## Lists

Push re-indents nested lists to 4 spaces per level (the converter needs it, and pulled or
hand-typed 2-space lists used to come out flat). Pull indents them the way the vault does:
a tab, unless "Indent using tabs" is off in Obsidian.

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

## What still changes on the first pull

A page written by hand in Confluence settles after one pull and push. From then on it is
stable:

- Repeated spaces collapse to one.
- A table with merged cells gets an empty cell where the merge was (merged cells, cell
  colours and column widths have no Markdown).
- Text colour is dropped (the text stays).
- Inline comments stay in Confluence. Pushing over a commented passage can detach them.

Notes pulled before 0.13.0 keep their old, flatter content until the page changes or is
pulled again with `--force` (which overwrites local edits, so push those first).
