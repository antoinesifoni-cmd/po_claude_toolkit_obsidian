# Step: review-loose-ends

**Goal:** list what the day leaves hanging in the note.

## Sources

1. **The note:** Read `note` from the vault root. Skip the two skill blocks.
2. **Meetings:** `meetings.json` and `recaps.json` in the Run folder.

## Do

Flag, in this order:

1. **No due date:** each open task in the note, `- [ ]` or `- [/]`, with no `📅` date. The Today and Overdue queries never show it.
2. **Action item:** each entry of `my_actions` in `recaps.json` that no task in the note covers. Compare the meaning, not the words.
3. **No notes:** each meeting that has ended (`end` before `now` from `today`) with nothing written under its heading besides tags and its time. A meeting with an entry in `recaps.json` is not empty.

## Output

Write `review-loose-ends.md` in the Run folder, one bullet per item, each on one line. Name the section in brackets. Never copy a link or a web address. Made-up example:

```
- **No due date** Book the pilot clinic (Sprint review). It never shows in Today or Overdue.
- **Action item** Confirm the pilot dates with the clinic (Scheduling Weekly Sync). Not a task yet.
- **No notes** Design check-in has nothing written.
```

Nothing found: write the file empty. When no Review step finds anything, the note says `- Nothing to flag.` once.

## If it fails

Write `- **Loose ends not checked**: <one line reason>.`
