# Step: alert-confluence

**Goal:** list the linked Confluence pages that someone changed on Confluence.

## Do

1. Run the `confluence-sync:confluence-status` skill for all linked notes, in report-only mode:
   - no pull, no push, no setup, no merge flow, no proposed next step
   - ignore its hand-off advice
2. Run its status command as it gives it, from the vault root, with no file argument. Use the Bash `timeout` 600000 and no pipe, so the exit code is kept.
3. Keep the lines that contain `remote moved` or `CONFLICT`. Drop the others.

## Output

Write `alert-confluence.md` in the Run folder, one bullet per kept line.

- `<path>` is the file at the start of the line, with `/` instead of `\` and without `.md`.
- `<name>` is the last part of `<path>`.
- A `remote moved to vN` line becomes:
  `- **Moved on Confluence** [[<path>|<name>]] v<local> to v<N>. Pull it with confluence-pull when you are ready.`
- A `CONFLICT` line becomes:
  `- **Conflict** [[<path>|<name>]] has local edits and the page moved to v<N>. Run confluence-status first.`
- When no line is kept: `- No Confluence page moved (<count> checked).`, where `<count>` is the number of status lines.

Made-up example:

```
- **Moved on Confluence** [[Confluence Projects/PT-2311 - Scheduling/PT-2311 - Handoff|PT-2311 - Handoff]] v10 to v12. Pull it with confluence-pull when you are ready.
```

## If it fails

- Keep the bullets for the lines already printed.
- If the command did not exit 0, add `- **Confluence check incomplete**: <last error line>. Run confluence-status by hand.`
- If the skill cannot be found, write only that last bullet, with the reason.
