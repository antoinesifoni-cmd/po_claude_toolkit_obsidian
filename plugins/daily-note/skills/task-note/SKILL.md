---
name: task-note
description: >
  Gives a task in Antoine's Obsidian vault a note to write in: creates the note from his
  Task Note template with the Obsidian CLI, then puts a 📎 link to it in the task line.
  The task stays a Tasks plugin task, with its checkbox and dates. Use when he asks for a
  note on a task, even casually: "make a note for this task", "task note", "document this
  task", "crée une note pour cette tâche", or asks to process the tasks marked #note. Not
  for other notes, and not for changing the tasks themselves.
allowed-tools: Edit(.daily-note/run/**)
---

# Task note

- Task note script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tasknote.py"`
- Steps folder: `${CLAUDE_PLUGIN_ROOT}/steps/`
- Rules: `${CLAUDE_PLUGIN_ROOT}/config.json`, key `task_note`. The Task note script reads them by itself.
- Run folder: `.daily-note/run/`, in the vault root. The session must be started in the vault root.

## Run order

1. **Pick the tasks** from the message:
   - It holds `<editor_selection path="..." lines="10-15">`: single, `scan "<path>" 10-15`.
   - It holds `<editor_cursor path="..." line="8">`: single, `scan "<path>" 8`.
   - Decode the path once: `&amp;` is `&`, `&quot;` is `"`, `&lt;` is `<`, `&gt;` is `>`.
   - He asks for the tasks marked #note, or for all the task notes: batch, `scan`.
   - He says "this task" but the message shows no selection or cursor: ask which task, and wait.
2. Run the `task-note` step with that scan. Read `<Steps folder>/task-note.md` first.

## Rules

- Asking is the permission to create the note and to change the task line, as the vault rule on new notes wants. In batch, his yes to the list is the permission.
- Only the Task note script changes notes. Never use Edit or Write on a note. Write only inside the Run folder.

## Final report

Single, one task: one line. Made-up examples:

```
Created [[Ask Julie for pilot dates]] and linked it in the task.
Linked the task to the existing note [[Prep the release plan]].
This task has a note already: [[Review the mockups]].
```

Batch: one line per result, at most 8 lines, then the backup. Made-up example:

```
- Ask Julie for pilot dates: created
- Prep the release plan: linked to the existing note
- Review the mockups: had a note, #note removed
Backup: .daily-note/backups/2026-10-05_173012_2026-10-05.md
```

- A result with `detail`: add it after the result.
- Nothing found: `No task is marked #note.`
- If the Task note script stops, show its message. It changed nothing.
