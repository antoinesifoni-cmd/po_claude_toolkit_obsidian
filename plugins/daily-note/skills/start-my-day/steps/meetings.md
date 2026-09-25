# Step: meetings

**Goal:** list today's meetings and the heading each one gets in the note.

## Do

1. Call the Google Calendar `list_events` tool with:
   - `calendarId`: `"primary"`
   - `startTime`: `day_start` and `endTime`: `day_end`, from `today`
   - `orderBy`: `"startTime"` and `pageSize`: `50`
   - no `eventType` and no `timeZone`
2. Keep an event only when all of these are true. Skip every other event.
   - It has `start.dateTime`. An all-day event only has `start.date`.
   - Its `eventType` is `DEFAULT`.
   - Its `status` is not `cancelled`.
   - Your own entry in `attendees`, the one with `self: true`, is not `declined`. An event with no `attendees` list is your own, so keep it.
3. `heading`: take the title (`summary`), then remove emojis and extra spaces.
   - If the title starts with a project id like `PT-1778`, drop the id and the ` - `, `-` or `:` after it.
   - `pt`: the project id the title starts with, or `null`.
4. `start` and `end`: the local time of `start.dateTime` and `end.dateTime`, as `HH:MM`.

## Output

Write `meetings.json` in the Run folder, meetings in time order. Made-up example:

```json
{"meetings": [
  {"start": "09:30", "end": "10:00", "title": "Sprint review ✌️",
   "heading": "Sprint review", "pt": null},
  {"start": "13:00", "end": "13:30", "title": "PT-2311 Scheduling Weekly Sync",
   "heading": "Scheduling Weekly Sync", "pt": "PT-2311"}
]}
```

No meeting today: `{"meetings": []}`.

## If it fails

Write `{"error": "<one line reason>"}` to `meetings.json`. The note then gets no meeting headings, and the Summary says the calendar was not checked.
