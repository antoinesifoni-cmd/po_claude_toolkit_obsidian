# daily-note

A morning and an evening routine for an Obsidian vault, driven by Claude Code, plus two
skills on request: one recaps a single meeting, one gives a task a note to write in.

```
/daily-note:start-my-day
/daily-note:end-my-day
```

The two routines run only when you type them. Claude never starts them on its own,
because they write to a vault that has no undo. `meeting-recap` and `task-note` are the
exceptions: say "fetch resume of this meet" or "make a note for this task" and they run,
since asking is the whole point.

## What lands in the note

**start-my-day**, in the morning, builds or updates today's note, then opens it in a pinned tab:

- **Summary:** one paragraph on how the day looks, built from your meetings, tasks due or
  overdue, the Gmail Jira labels, your open Jira issues and each project's `CLAUDE.md`.
- **Alert:** the linked Confluence pages that someone changed on Confluence, from
  `confluence-sync`.
- **Meetings:** one H1 per meeting from Google Calendar, with its time and `#PT-xxxx` tag.
  Added only while the note has no heading of your own yet, so a re-run never duplicates
  them and never touches what you wrote.

**end-my-day**, in the evening, completes the note, then opens it and unpins its tab:

- **Task notes:** first, the tasks marked `#note` anywhere in the vault get their note,
  after your yes to the list. See task-note below.
- **Missing meetings:** a heading for each meeting of today that the note has no section
  for, in time order. A heading you renamed still counts, when its time line is the same.
- **Recaps:** under each meeting that Google recorded, a one or two sentence recap and a
  link to the transcript, from the Gemini notes attached to the calendar event.
- **Project tags:** a `#PT-xxxx` tag on each section clearly about one project that has
  none. An unsure case is flagged instead.
- **Corrections:** your `text-corrector` skill fixes the lines you wrote. The script
  refuses any fix that would touch a link, tag, date, time, emoji or list marker.
  Headings are never changed.
- **End of day:** one paragraph on what the day achieved, from the note and the tasks
  you closed today, above the Task section.
- **Review:** loose ends (open tasks with no due date, your Gemini action items that are
  not tasks yet, meetings with nothing written) and the `CLAUDE.md` files today made out
  of date. It flags them, it never edits them.

**meeting-recap** does the recap part for one meeting, any time: "fetch resume of this
meet", "get the recap of the sprint review". With no meeting named, it takes the one
that ended last.

**task-note** gives a task a note to write in, only when you want one. The task stays a
Tasks plugin task: checkbox, dates, Today and Overdue, nothing changes there.

- Select a task line, or put the cursor on it, and say "make a note for this task".
  Or put `#note` in tasks anywhere, and say "make the task notes", or let end-my-day
  pick them up. Several tasks are always listed first, and nothing happens before your yes.
- The note is created in `Day2Day notes/00-Task Note/` from your `Task Note` template,
  through the Obsidian CLI, and named after the day it is made and a title:
  `26-10-05 - Ask Julie for pilot dates`. Its properties: `tags` (`TaskNote` and the
  task's own tags) and `source` (the note the task lives in). AutoDater adds `Created`.
- The task line gets `[[26-10-05 - Ask Julie for pilot dates|📎]]` right before its Tasks
  fields, and `#note` goes away. After the fields, the Tasks plugin would stop reading the
  dates.
- The title is the task's text when it is 8 words or fewer, with no tag past its start.
  Otherwise Claude writes a short one, shown to you first. Renaming the note later keeps
  the link.
- An existing note is linked, never written over. A task that has its note already only
  loses `#note`. A note synced with Confluence is never changed.
- The note holds no status and no date: they stay in the task line, so the two never
  disagree. Your template can show the task live, see Setup.

Each skill owns only its block and the lines it adds. Everything else in the note stays as
it is. Before every write, the note is copied to `.daily-note/backups/`.

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
   The End of day block needs no template change: end-my-day adds it above the template's
   `---` and `# Task`.
2. Install `confluence-sync` too, for the Alert section. Without it, the Alert says the
   check did not run.
3. Connect the Google Calendar, Gmail, Google Drive and Atlassian connectors in Claude.
4. Have a `text-corrector` skill, for the corrections. Without it, that step is skipped.
5. Install the Advanced URI community plugin in Obsidian.
6. Start Claude Code in the vault root, the folder that holds `.obsidian/`.
7. For task-note:
   - Turn on the Obsidian CLI, and keep Obsidian open: it creates the notes.
   - Point Settings, Templates, Template folder location to your templates folder, or the
     CLI finds no template.
   - Create the `Task Note` template there. Starter:

     ````
     ---
     tags:
       - TaskNote
     ---

     ```tasks
     description includes {{query.file.filenameWithoutExtension}}|📎]]
     ```

     ## Notes
     ````

     The query shows the task whose link names this note, live, with its checkbox and
     dates. It needs no JavaScript, which Tasks now blocks in queries by default, so no
     `filter by function`. If you change the icon in the rule's `link`, change it here too.
   - With AutoDater: give the template no `Created` line, not even an empty one, and add
     the templates folder to AutoDater's Excluded folders. Otherwise every task note copies
     the template's own date.
   - Create the `Day2Day notes/00-Task Note` folder.

## Steps

Each skill's `SKILL.md` holds its run order, and nothing else does. Each step is one short
prompt file in `steps/`, readable on its own, and a step can serve more than one skill.

| Step | Used by | Reads | Writes to `.daily-note/run/` |
|---|---|---|---|
| start (`daynote.py today`) | all | Obsidian's daily notes settings | nothing, it empties the folder |
| `task-note` | end, task-note | the tasks marked `#note`, or the selected ones | `task-note.json`, `task-titles.json` |
| `meetings` | all | Google Calendar | `meetings.json` |
| `alert-confluence` | start | `confluence-sync:confluence-status` | `alert-confluence.md` |
| `summary` | start | meetings, tasks, Gmail, Jira, project `CLAUDE.md` | `summary.md` |
| `daynote.py prose` | end | the note | `prose.json` |
| `recap` | end, recap | Gemini notes in Google Drive | `recaps.json` |
| `tags` | end | the note, project folders, vault `CLAUDE.md` | `tags.json`, `review-tags.md` |
| `review-loose-ends` | end | the note, recaps | `review-loose-ends.md` |
| `review-claude-md` | end | the note, recaps, `CLAUDE.md` files | `review-claude-md.md` |
| `correct` | end | `prose.json`, `text-corrector` | `corrections.json` |
| `wrapup` | end | the note, tasks closed today, recaps | `wrapup.md` |
| end (`daynote.py write`, `close`, `recap`) | start, end, recap | the run folder | the note |

Claude gathers, the script writes. `scripts/daynote.py` is the only code that changes the
daily note, and `scripts/tasknote.py` the only code that changes a task line or creates a
task note, through the Obsidian CLI. `scripts/tests/test_write.py` covers the morning,
`scripts/tests/test_close.py` the evening and the recap, `scripts/tests/test_tasknote.py`
the task notes.

## Settings

`config.json`, next to this README. Not `settings.json`: Claude Code reserves that name at a plugin root for its own defaults.

| Key | What it does |
|---|---|
| `gmail.labels` | Gmail labels the Summary reads, by name |
| `jira.site`, `jira.jql` | the Jira site and the query for your open issues |
| `summary.language`, `summary.style` | how the morning paragraph is written |
| `recap.language`, `recap.style` | how a meeting recap is written |
| `wrapup.language`, `wrapup.style` | how the End of day paragraph is written |
| `task_note.rules` | how a task gets its note, read by `tasknote.py` itself |

The daily notes folder, template and vault name come from Obsidian's own settings, so they
are not repeated here.

A task note rule, as shipped:

- `keyword`: the tag that asks for a note, `#note`. Any case.
- `template` and `folder`: the template the note is made from, and where it goes.
- `name`: the note's name. `{title}` is the title, and `{YY}` or `{YYYY}`, `{MM}`, `{DD}`
  the day the note is made. Shipped: `{YY}-{MM}-{DD} - {title}`. A note of another day
  never matches, so the same title on a new day gets a new note.
- `link`: what goes in the task line. `{title}` becomes the note's name, or its path when
  another note has the same name.
- `title_words`: a task text this short is the title as is, unless a tag sits inside it.
  Otherwise Claude writes one.
- `properties`: set on the new note. `{tags}` stands for the task's tags, `{source}` for
  the note the task lives in, `{title}` for the title. An empty value is not set.

The first rule whose keyword is in the line wins. A task picked by selection with no
keyword uses the first rule. Another keyword can send its tasks to another template and
folder: add a rule.

The file ships with the plugin, so a change is a release: edit it here, bump the version,
merge, then `claude plugin marketplace update po-claude-toolkit` and
`claude plugin update daily-note@po-claude-toolkit`. Do not edit the installed copy, the
next update replaces it. This repo is public, and so is this file.

## Adding a step

A new alert type, for example "my Jira tickets that became Blocked":

1. Copy `steps/alert-confluence.md` to `steps/alert-jira-blocked.md` and change Goal, Do
   and Output. It writes `alert-jira-blocked.md` with bullets.
2. In `skills/start-my-day/SKILL.md`, add `alert-jira-blocked` to the step list.
3. If it needs settings, add a key to `config.json`.
4. Bump the version.

`write` picks up every `alert-*.md` file, and `close` every `review-*.md` file, so a new
Alert or Review item needs no change to the template or the script.

A new Summary source is one bullet in `steps/summary.md`. Python changes only for a new
kind of edit to the note, and each one comes with a test.

## Testing

```
python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts
```

Try an unmerged branch from the vault root with
`claude --plugin-dir <repo>/plugins/daily-note`.

To call the Obsidian CLI by hand from Git Bash, use `Obsidian.com`: plain `obsidian`
fails without a word on commands with a colon, like `property:set`. `tasknote.py` works
from any shell.
