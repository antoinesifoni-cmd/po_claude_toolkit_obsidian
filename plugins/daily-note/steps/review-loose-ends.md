# Step: review-loose-ends

**Goal:** list what the day leaves hanging in the note.

## Sources

1. **The note:** Read `note` from the vault root. Skip the two skill blocks.
2. **Meetings:** `meetings.json` and `recaps.json` in the Run folder.

## Do

Flag, in this order:

1. **No due date:** each open task in the note, `- [ ]` or `- [/]`, with no `📅` date. The Today and Overdue queries never show it.
2. **Action item:** each entry of `my_actions` in `recaps.json` that no task in the note covers. Compare the meaning, not the words.
3. **No notes:** each meeting that has ended (`end` before `now` from `today`) with nothing written under its heading besides tags and its time. A meeting with an entry in `recaps.json` is not empty. A meeting with `"kind": "mixed"` in `meetings.json` is never flagged here: a daily often has nothing to write.
4. **Tag?** each meeting with `"kind": "mixed"` that has lines written under its heading and no project tag anywhere in its section. Name the project a line is about when one is clearly named.

## Output

Write `review-loose-ends.json` in the Run folder. Each item is one JSON object: `kind`, `key` (what makes it the same item on a re-run), `text` (the bullet the note shows, as before) and the fields the Review needs to act on it, listed per kind. The script shows the bullets and keeps the items for the review skill. The `text` is one line, names the section in brackets, and never copies a link or a web address.

| Kind | `key` | Other fields |
|---|---|---|
| `nodue` | the task line, as it is | `line`: the task line exactly as in the note, `heading`: its section |
| `action` | the action, in a few words | `task`: the task text to create, short, in Antoine's language, `heading`: the meeting it came from, `date`: the date the meeting gave, `YYYY-MM-DD`, else `null`, `pt`: the meeting's project or `null` |
| `nonotes` | the heading | `heading`, `title`: the calendar title from `meetings.json` |
| `tag` | the heading | `heading`, `options`: the project ids the lines point to, most likely first |

Made-up example:

```json
{"items": [
  {"kind": "nodue", "key": "- [ ] Book the pilot clinic", "line": "- [ ] Book the pilot clinic",
   "heading": "Sprint review",
   "text": "- **No due date** Book the pilot clinic (Sprint review). It never shows in Today or Overdue."},
  {"kind": "action", "key": "Confirm the pilot dates", "task": "Confirm the pilot dates with the clinic",
   "heading": "Scheduling Weekly Sync", "date": "2026-09-25", "pt": "PT-2311",
   "text": "- **Action item** Confirm the pilot dates with the clinic (Scheduling Weekly Sync). Not a task yet."},
  {"kind": "nonotes", "key": "Design check-in", "heading": "Design check-in", "title": "Design check-in",
   "text": "- **No notes** Design check-in has nothing written."},
  {"kind": "tag", "key": "Mobile daily", "heading": "Mobile daily", "options": ["PT-2311"],
   "text": "- **Tag?** Mobile daily has notes and no project tag. The release line is about PT-2311."}
]}
```

Nothing found: `{"items": []}`. When no Review step finds anything, the note says `- Nothing to flag.` once.

## If it fails

Write `{"items": [{"kind": "note", "key": "loose-ends-failed", "text": "- **Loose ends not checked**: <one line reason>."}]}`.
