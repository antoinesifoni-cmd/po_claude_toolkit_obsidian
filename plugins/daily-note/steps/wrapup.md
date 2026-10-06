# Step: wrapup

**Goal:** one paragraph that tells Antoine what his day achieved.

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

## Rules

- Language and style: `wrapup.language` and `wrapup.style` in the Settings.
- Only facts from the sources above. Name ticket keys (`MYLE-30166`) and project ids.
- Plain sentences only. No list, heading, link, web address or code.
- If a source failed, end with `(Not checked: calendar.)`, naming each one that failed.

## Output

Write `wrapup.md` in the Run folder once it is complete. It holds the paragraph and nothing else.

Made-up example:

> Most of the day went to PT-2311: the sprint review demoed the appointment filter, and the scheduling sync moved the pilot to the week of October 5 because the consent form is not signed yet. You closed three tasks, including the CLN-482 answer on the appointment filter and the pilot feedback summary for Julie Tremblay, and dropped the duplicate booking ticket. The consent form review for PT-2402 is still open and carries over to tomorrow, together with confirming the pilot dates with the clinic.

## If it fails

Write nothing. The note then shows `_End of day not generated in this run._`
