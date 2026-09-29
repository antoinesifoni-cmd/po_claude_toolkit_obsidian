# Step: tags

**Goal:** add the missing project tag to each section of the note that is about one open project.

## Sources

1. **The note:** Read `note` (from `today`) from the vault root. A section is an H1 and what is under it, outside the two skill blocks and above `# Task`.
2. **Meetings:** `meetings.json` and `recaps.json` in the Run folder. A meeting the note has no section for yet counts too, since `close` adds it.
3. **Open projects:** Glob `Confluence Projects/*/CLAUDE.md`. Each folder name is `<id> - <name>`, like `PT-2311 - Scheduling`.
4. **Other names:** in the vault `CLAUDE.md`, Grep `^## ` with line numbers, then Read only the `## Project tags` section. It gives each project's other names and Jira keys.

## Do

1. Keep the sections that have no project tag at all, in the heading or under it. A section with any tag like `#PT-1234` is done.
2. For each one, look for signals in the section itself, its heading, its text and its recap. Nothing else counts, not the project files and not who attends. The signals:
   - the project id, with or without `#` or hyphen (`PT-2311`, `PT2311`)
   - the project's full name, or another name the Project tags section gives it. One common word shared with a project name, like `Mobile` or `AI`, is not a signal.
   - a `[[wikilink]]` to a note whose name starts with a project id
   - a ticket key that one project's `CLAUDE.md` lists. Grep the key in `Confluence Projects/*/CLAUDE.md` with `output_mode: "files_with_matches"`.
3. Tag a section when its signals all point to one project. A section with no signal, or with signals for several projects, gets no tag.
4. When the only signals are weak or point two ways, do not tag it. Flag it instead, see Output. An empty section is never flagged.

## Output

Write `tags.json` in the Run folder. `start` and `end` come from the section's time line, or are `null`. Made-up example:

```json
{"tags": [
  {"heading": "Consent form wording", "start": null, "end": null, "tag": "PT-2402"}
]}
```

Nothing to tag: `{"tags": []}`.

Only when a case was unsure, also write `review-tags.md`, one bullet each, naming the signal you saw. Made-up example:

```
- **Tag?** Design check-in mentions CLN-482, a PT-2311 ticket, and the PT-2402 consent form. Add the tag yourself.
```

## If it fails

Write `{"error": "<one line reason>"}` to `tags.json`. No tag is added.
