# Step: back

**Goal:** everything that happened on Antoine's projects while he was away, from `from` to `to`, grouped by project, so the catch-up note reads in ten minutes.

Every call is read-only. Dates for the calendar are local midnights in the same shape as `day_start` from `today`: `<YYYY-MM-DD>T00:00:00` followed by the same offset.

## 1. Meetings he missed

1. Call `list_events` with `calendarId` `"primary"`, `startTime` the midnight of `from`, `endTime` the midnight of the day after `to`, `orderBy` `"startTime"`, `pageSize` `250`. A big answer may be saved to a file: read it from there.
2. Keep an event when it has `start.dateTime`, its `eventType` is `DEFAULT` and its `status` is not `cancelled`. His own answer does not matter: most were declined for him by the out of office event. Drop one that has no other attendee and no Gemini notes: a block of his own.
3. For each, as the `meetings` step does: `heading`, `pt`, `start`, `end`, `doc`. Add `date`, as `YYYY-MM-DD`.
4. Write them to `meetings.json` in the Run folder, then run the Script with `map`. It drops the personal and placeholder events, and gives the known meetings their project or marks them `mixed`. Read `meetings.json` back.
5. Recaps: for the meetings with a `doc`, the project ones first, then the others, at most 12, read the notes as the `recap` step does. A recap is 2 sentences at most: what was decided or learned, then what it means for Antoine. No `my_actions` here.
6. A meeting with no `pt`, `mixed` or not in the map, goes to the project its notes are clearly about, like a "PCA performance discussion" to the PCA project. Else to `other`.
7. A meeting that came several times is one entry: the first `date`, the heading followed by `(also Oct 29, Oct 31)`, and one recap for all of them. Its `doc` is the latest one that has notes.

## 2. Slack decisions

Do the `decisions` step over the range, with these changes:

- Only the tracked channels that have a `pt`: the project channels. The searches of where Antoine wrote or reacted are skipped.
- One search per day of the range, `on:<day>`, instead of one for the whole range, so a busy channel does not hide the first days. Follow each cursor 4 times at most.
- A decision reached any day of the range counts. Keep its `date`. No `heading`.
- No Review file: an unsure decision goes in with its `text` starting `Maybe:`.

## 3. Jira

1. `searchJiraIssuesUsingJql` with `cloudId` `jira.site`, `jql`: `(assignee = currentUser() OR reporter = currentUser() OR watcher = currentUser()) AND updated >= "<from>" AND updated < "<the day after to>" ORDER BY updated DESC`, `fields` `["summary", "status", "parent", "updated"]`, `maxResults` `100`. A big answer may be saved to a file: read it from there.
2. One entry per issue: `key`, and `text` = its status now, then its summary in 10 words at most, like `Done · Show the protected note popup on the second screen`. "Status now" because the history of each issue is not read: say "now" in the summary when it matters.
3. Its project: the project whose `CLAUDE.md` lists the key, its parent's key or its parent's parent's key. Grep the keys in `Confluence Projects/*/CLAUDE.md` with `output_mode: "files_with_matches"`. For the parents' parents, one more `searchJiraIssuesUsingJql` with `jql` `key in (<the parent keys still unmatched>)` and `fields` `["parent"]`. Still nothing: `other`.
4. In `other`, keep 10 at most: the ones assigned to him first, then the most recently updated.

## 4. Confluence

Run the status command the `alert-confluence` step names, from the vault root, and read its lines. Do not write `alert-confluence.md`. For each line that step would keep:

- `path`: the note's path, with `.md`. A folder has no `.md`: leave `path` out and name the folder in `text`.
- `text`, short:
  - `remote moved to vN`: `moved v<local> to v<N>, pull it with confluence-pull`
  - `CONFLICT`: `local edits and the page moved, run confluence-status`
  - `RENAMED?`, `FOLDER RENAMED?`, `MISSING`, `FOLDER MISSING`, `AMBIGUOUS`: `link lost, say "fix my Confluence links"`
  - `NEW:` and `NEW FOLDER:`: `new "<title>" by <who>, say "add it to my vault"`, with no `path` since it is not in the vault yet. Its project: the `PT-xxxx` that starts the folder it is in. These cover the last 14 days only.
- its project: the `PT-xxxx` that starts the path's project folder, else `other`

These lines are about today, not the range: a page that moved while he was away is still "moved" now.

## Output

Write `back.json` in the Run folder. Projects in order of how much happened, `other` for what has no project. A part with nothing in it is left out. Made-up example:

```json
{"from": "2026-11-24", "to": "2026-12-07",
 "projects": [
  {"pt": "PT-2311", "name": "Scheduling",
   "meetings": [{"date": "2026-11-24", "heading": "Scheduling sync (also Dec 1)",
                 "recap": "The pilot moved to January. You own the clinic list.",
                 "doc": "1FakeDocIdMadeUpForTheExampleOnly00000000000", "tab": null}],
   "decisions": [{"date": "2026-11-26", "text": "Load test dropped, the 2 minute check is enough",
                  "key": "MYLE-1234",
                  "link": "https://example-team.slack.com/archives/C0FAKE0001/p1790000000000001"}],
   "jira": [{"key": "MYLE-1234", "text": "Done · Filter appointments by clinic"}],
   "confluence": [{"path": "Confluence Projects/PT-2311 - Scheduling/Release plan.md",
                   "text": "moved v14 to v17, pull it with confluence-pull"}]}
 ],
 "other": {"meetings": [], "jira": []}}
```

The project `name` is the folder name after `<id> - `. Remember the counts for the final report.

## 5. What to look at first

This part runs last, after the `waiting` step, as the skill's run order says.

Write `back-summary.md` in the Run folder: 5 bullets at most, one line each, 15 words at most. What needs Antoine first, from `back.json` and the oldest asks of `waiting.json`. Name projects by id, without the #. No link, no heading.

## If it fails

One part fails: leave it out and remember why. The note is still built from the rest.
