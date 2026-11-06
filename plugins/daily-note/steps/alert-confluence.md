# Step: alert-confluence

**Goal:** list the linked Confluence pages that someone changed on Confluence, the links that lost their note after a rename, move or delete in the vault, and the pages new on Confluence under the linked folders.

## Do

1. Run the `confluence-sync:confluence-status` skill for all linked notes, in report-only mode:
   - no pull, no push, no setup, no merge flow, no proposed next step
   - ignore its hand-off advice
2. Run its status command as it gives it, from the vault root, with no file argument. Use the Bash `timeout` 600000 and no pipe, so the exit code is kept.
3. Keep the lines that contain `remote moved` or `CONFLICT`, and the lines that start with `RENAMED?`, `FOLDER RENAMED?`, `MISSING:`, `FOLDER MISSING:` or `AMBIGUOUS:`, and the lines that start with `NEW:` or `NEW FOLDER:`. Drop the others. Never run the `relink`, `unlink`, `add` or `ignore` commands those lines name: this step only reports.

## Output

Write `alert-confluence.md` in the Run folder, one bullet per kept line.

- `<path>` is the file at the start of the line, with `/` instead of `\` and without `.md`.
- `<name>` is the last part of `<path>`.
- A `remote moved to vN` line becomes:
  `- **Moved on Confluence** [[<path>|<name>]] v<local> to v<N>. Pull it with confluence-pull when you are ready.`
- A `CONFLICT` line becomes:
  `- **Conflict** [[<path>|<name>]] has local edits and the page moved to v<N>. Run confluence-status first.`
- A `RENAMED? <old> -> <new>` line becomes, with `<path>` and `<name>` taken from `<new>`:
  `- **Link lost** [[<path>|<name>]] was renamed, its Confluence link still uses the old name. Say "fix my Confluence links".`
- A `FOLDER RENAMED? <old> -> <new>` line becomes, `<name>` being the last part of `<new>`:
  `- **Link lost** Folder <name> was renamed, with the notes inside. Say "fix my Confluence links".`
- A `MISSING: <old>` or `FOLDER MISSING: <old>` line becomes, `<name>` being the last part of `<old>` without `.md`, as plain text since the note is gone:
  `- **Link lost** <name> is gone from the vault but still linked. Say "fix my Confluence links" to unlink it.`
- An `AMBIGUOUS: <old> ...` line becomes:
  `- **Link lost** <name> is gone and two notes carry its page. Say "fix my Confluence links" to pick one.`
- A `NEW: "<title>" (page N) in <folder>, by <who>, <date>` line becomes, `<where>` being the last part of `<folder>`:
  `- **New on Confluence** "<title>" by <who>, in <where>. Say "add it to my vault".`
- A `NEW FOLDER: "<title>" ... K pages inside ...` line becomes:
  `- **New on Confluence** folder "<title>" with K pages, by <who>, in <where>. Say "add it to my vault".`
- More than 5 `NEW` lines: keep the 5 newest, then `- **New on Confluence** and <n> more. Say "show the new Confluence pages".`
- A `NEW: check failed` line becomes `- **New on Confluence not checked**: <reason>.`
- When no line is kept: `- No Confluence page moved (<count> checked).`, where `<count>` is the number of lines that contain ` local | `.

Made-up example:

```
- **Moved on Confluence** [[Confluence Projects/PT-2311 - Scheduling/PT-2311 - Handoff|PT-2311 - Handoff]] v10 to v12. Pull it with confluence-pull when you are ready.
- **Link lost** [[Confluence Projects/PT-2311 - Scheduling/PT-2311 - Pilot plan|PT-2311 - Pilot plan]] was renamed, its Confluence link still uses the old name. Say "fix my Confluence links".
```

## If it fails

- Keep the bullets for the lines already printed.
- If the command did not exit 0, add `- **Confluence check incomplete**: <last error line>. Run confluence-status by hand.`
- If the skill cannot be found, write only that last bullet, with the reason.
