# daily-note

A morning routine for an Obsidian vault, driven by Claude Code. One command builds or
updates today's daily note, then opens it in Obsidian:

```
/daily-note:start-my-day
```

It runs only when you type it. Claude never starts it on its own, because it writes to a
vault that has no undo.

## What lands in the note

- **Summary:** one paragraph on how the day looks, built from your meetings, tasks due or
  overdue, the Gmail Jira labels, your open Jira issues and each project's `CLAUDE.md`.
- **Alert:** the linked Confluence pages that someone changed on Confluence, from
  `confluence-sync`.
- **Meetings:** one H1 per meeting from Google Calendar, with its time and `#PT-xxxx` tag.
  Added only while the note has no heading of your own yet, so a re-run never duplicates
  them and never touches what you wrote.

The skill owns only the block between the two markers. Everything else in the note stays
as it is. Before every write, the note is copied to `.daily-note/backups/`.

## Setup (once)

1. Paste this block into your daily note template, right after the properties:

   ```
   %% start-my-day:begin %%

   # Summary

   _Filled by start-my-day. Rebuilt on every run. Write below._

   ## Alert

   %% start-my-day:end %%
   ```

   A note without the block still works: the first run inserts it after the properties.
2. Install `confluence-sync` too, for the Alert section. Without it, the Alert says the
   check did not run.
3. Connect the Google Calendar, Gmail and Atlassian connectors in Claude.
4. Install the Advanced URI community plugin in Obsidian.
5. Start Claude Code in the vault root, the folder that holds `.obsidian/`.

## Steps, in order

The order lives in one list in `skills/start-my-day/SKILL.md`. Each step is one short
prompt file in `skills/start-my-day/steps/`, readable on its own.

| Step | Reads | Writes to `.daily-note/run/` |
|---|---|---|
| start (`daynote.py today`) | Obsidian's daily notes settings | nothing, it empties the folder |
| `meetings` | Google Calendar | `meetings.json` |
| `alert-confluence` | `confluence-sync:confluence-status` | `alert-confluence.md` |
| `summary` | meetings, tasks, Gmail, Jira, project `CLAUDE.md` | `summary.md` |
| end (`daynote.py write`) | the run folder | the note, then opens it |

Claude gathers, the script writes. `scripts/daynote.py` is the only code that changes the
note, and `scripts/tests/test_write.py` covers it.

## Settings

`skills/start-my-day/settings.json`:

| Key | What it does |
|---|---|
| `gmail.labels` | Gmail labels the Summary reads, by name |
| `jira.site`, `jira.jql` | the Jira site and the query for your open issues |
| `summary.language`, `summary.style` | how the paragraph is written |

The daily notes folder, template and vault name come from Obsidian's own settings, so they
are not repeated here.

The file ships with the plugin, so a change is a release: edit it here, bump the version,
merge, then `claude plugin marketplace update po-claude-toolkit` and
`claude plugin update daily-note@po-claude-toolkit`. Do not edit the installed copy, the
next update replaces it. This repo is public, and so is this file.

## Adding a step

A new alert type, for example "my Jira tickets that became Blocked":

1. Copy `steps/alert-confluence.md` to `steps/alert-jira-blocked.md` and change Goal, Do
   and Output. It writes `alert-jira-blocked.md` with bullets.
2. In `SKILL.md`, add `alert-jira-blocked` to the step list.
3. If it needs settings, add a key to `settings.json`.
4. Bump the version.

`write` picks up every `alert-*.md` file, so the template and the script do not change.

A new Summary source is one bullet in `steps/summary.md`. Python changes only for a new
kind of edit to the note, and each one comes with a test.

## Testing

```
python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts
```

Try an unmerged branch from the vault root with
`claude --plugin-dir <repo>/plugins/daily-note`.
