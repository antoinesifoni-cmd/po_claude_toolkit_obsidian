# Step: wrapup

**Goal:** a few short bullets that tell Antoine what his day achieved, readable in five seconds.

## Sources

Gather these in order. If one fails, remember it and move on.

1. **The note:** Read `note` from the vault root: what he wrote under each section. The Summary block, when there is one, is the morning plan. Use it only to compare, never as a fact of what was done.
2. **Done today:** one Grep call from the vault root, with
   - pattern `- \[[xX-]\] .*(✅|❌) <date>`, where `<date>` is `date` from `today`
   - glob `!{.*/**,**/Templates/**}`
   - `output_mode: "content"` and `head_limit: 0`

   `✅` is done, `❌` is dropped. A `#PT-xxxx` tag on the line names the project.
3. **Still open:** one Grep call, same glob, with pattern `- \[[ /]\] .*📅\s*<date>`. These tasks were due today and are not done.
4. **Meetings:** `meetings.json` and `recaps.json` in the Run folder.
5. **Notes:** `notes.json` and `note-recaps.json` in the Run folder: the notes created or edited today.

## Rules

- Language and style: `wrapup.language` and `wrapup.style` in the Settings.
- Only facts from the sources above. Name ticket keys (`MYLE-30166`) and project ids.
- Every line is a `- ` bullet. No paragraph, heading, sub-bullet, link, web address or code.
- If a source failed, add a last bullet `- Not checked: calendar`, naming each one that failed.

## Output

Write `wrapup.md` in the Run folder once it is complete. It holds the bullets and nothing else.

Made-up example:

```
- Done: 3 tasks, incl. CLN-482 answer and pilot feedback summary for Julie Tremblay; dropped the duplicate booking ticket
- PT-2311 sprint review: appointment filter demoed
- PT-2311 scheduling sync: pilot moved to week of Oct 5, consent form not signed yet
- Tomorrow: PT-2402 consent form review, confirm pilot dates with the clinic
```

## If it fails

Write nothing. The note then shows `_End of day not generated in this run._`
