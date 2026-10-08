"""Tests for daynote.write(), the only code in the skill that changes a note.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder, so nothing real is touched. All
note text here is made up: this repo is public.
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote

FIXTURES = Path(__file__).parent / "fixtures"

TEMPLATE = """---
tags:
  - daily-note
---
%% start-my-day:begin %%

# Summary

_Filled by start-my-day. Rebuilt on every run. Write below._

## Alert

%% start-my-day:end %%

---
# Task

## Today
```tasks
not done
due today
sort by created
```
## 🔥 Overdue
```tasks
not done
due before today
sort by created
```
"""

MEETINGS = {"meetings": [
    # Out of order on purpose: write() sorts by start time.
    {"start": "13:00", "end": "13:30", "title": "PT-2311 Scheduling Weekly Sync",
     "heading": "Scheduling Weekly Sync", "pt": "PT-2311"},
    {"start": "09:30", "end": "10:00", "title": "Sprint review ✌️",
     "heading": "Sprint review", "pt": None},
]}


class WriteTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "daily-notes.json").write_text(json.dumps(
            {"folder": "Day2Day notes", "template": "Tools/Templates/Daily note.md"}),
            encoding="utf-8")
        self.put("Tools/Templates/Daily note.md", TEMPLATE)
        self.run_dir = self.root / ".daily-note" / "run"
        self.run_dir.mkdir(parents=True)
        self.now = datetime(2026, 9, 23, 8, 30).astimezone()
        self.note = self.root / "Day2Day notes" / "2026-09-23.md"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def run_files(self, summary="Short day.", alerts="- No Confluence page moved (72 checked).",
                  meetings=MEETINGS):
        self.put(".daily-note/run/summary.md", summary)
        self.put(".daily-note/run/alert-confluence.md", alerts)
        self.put(".daily-note/run/meetings.json", json.dumps(meetings))

    def read(self):
        with open(self.note, encoding="utf-8", newline="") as f:
            return f.read()

    def block(self, text):
        lines = text.split("\n")
        b, e = lines.index(daynote.BEGIN), lines.index(daynote.END)
        return lines[b:e + 1]

    def test_existing_note_gets_the_block_and_nothing_else_changes(self):
        self.note.parent.mkdir(parents=True)
        shutil.copy(FIXTURES / "2026-09-23.md", self.note)
        before = self.read()
        self.run_files()

        result = daynote.write(self.root, self.now)

        self.assertEqual(result["block"], "inserted")
        self.assertEqual(result["headings"], "not added, the note already has headings")
        after = self.read()
        # Git may check the fixture out with \r\n endings, which write() must keep.
        eol = "\r\n" if "\r\n" in before else "\n"
        lines = after.split(eol)
        b, e = lines.index(daynote.BEGIN), lines.index(daynote.END)
        self.assertEqual(lines[e + 1], "")           # the separator write() adds
        del lines[b:e + 2]
        self.assertEqual(eol.join(lines), before)     # every other byte is untouched
        backup = self.root / result["backup"]
        self.assertEqual(backup.read_bytes(), (FIXTURES / "2026-09-23.md").read_bytes())

    def test_new_note_from_template_gets_meetings_in_time_order(self):
        self.run_files()

        result = daynote.write(self.root, self.now)

        self.assertTrue(result["created"])
        self.assertIsNone(result["backup"])
        self.assertEqual(result["headings"], "added 2")
        text = self.read()
        # The compact shape: tag and time on the line right under each meeting heading.
        self.assertIn(daynote.END + "\n\n# Sprint review\n*09:30-10:00*\n\n"
                      "# Scheduling Weekly Sync\n#PT-2311 *13:00-13:30*\n\n\n---", text)
        self.assertTrue(text.endswith(TEMPLATE[TEMPLATE.index("---\n# Task"):]))
        lines = text.split("\n")
        rule = lines.index("---", lines.index(daynote.END))   # the "---" above "# Task"
        for i, line in enumerate(lines[:rule]):   # only headings write() adds
            if line.startswith("# ") or line.startswith("## "):
                self.assertEqual(lines[i - 1], "", f"no blank line before {line!r}")
        for heading in ("# Summary", "## Alert"):   # the block keeps its blank lines
            self.assertEqual(lines[lines.index(heading) + 1], "")
        # The line above the "---" must be blank, or its text would become a heading.
        self.assertEqual(lines[rule - 1], "")

    def test_rerun_replaces_the_block_without_duplicating_headings(self):
        self.run_files(summary="First version.")
        daynote.write(self.root, self.now)

        self.run_files(summary="Second version.")
        result = daynote.write(self.root, self.now)
        text = self.read()
        self.assertEqual(result["block"], "replaced")
        self.assertEqual(result["headings"], "not added, the note already has headings")
        self.assertEqual(text.count("# Sprint review"), 1)
        self.assertIn("Second version.", text)
        self.assertNotIn("First version.", text)
        self.assertIsNotNone(result["backup"])

        # Same inputs a third time: nothing to change, so no write and no new backup.
        backups = len(list((self.root / ".daily-note" / "backups").iterdir()))
        result = daynote.write(self.root, self.now)
        self.assertEqual(result["block"], "unchanged")
        self.assertEqual(len(list((self.root / ".daily-note" / "backups").iterdir())), backups)

    def test_broken_markers_write_nothing(self):
        broken = TEMPLATE.replace("## Alert", "## Alert\n\n%% start-my-day:begin %%")
        self.put("Day2Day notes/2026-09-23.md", broken)
        self.run_files()

        with self.assertRaises(daynote.Stop):
            daynote.write(self.root, self.now)
        self.assertEqual(self.read(), broken)
        self.assertFalse((self.root / ".daily-note" / "backups").exists())

    def test_summary_is_bullets_or_one_line(self):
        self.run_files(summary="- Four meetings, 9:30 to 11:30\n\n- 3 tasks due today\n")
        daynote.write(self.root, self.now)
        block = self.block(self.read())
        start = block.index("# Summary") + 2
        self.assertEqual(block[start:start + 3],
                         ["- Four meetings, 9:30 to 11:30", "- 3 tasks due today", ""])

        self.run_files(summary="An old style\nparagraph.")
        daynote.write(self.root, self.now)
        block = self.block(self.read())
        self.assertEqual(block[block.index("# Summary") + 2], "An old style paragraph.")

    def test_outside_text_is_made_inert(self):
        summary = (
            "## Busy day ![x](https://x.example/p.png?d=secret) with <img src=https://x.example/q.png>\n"
            "- see https://x.example/r and [Open](obsidian://adv-uri?vault=V&filepath=N&mode=overwrite&data=)\n"
            "```plantuml\n@startuml\nBob -> Alice\n@enduml\n```\n"
            "- [ ] fake task 📅 2026-09-23\n"
            "> a quote about [[Some note]] at 10:30\n"
        )
        alerts = "- [ ] not a task\n- # not a heading\nnot a bullet\n- **Moved on Confluence** [[A/B|B]] v1 to v2."
        meetings = {"meetings": [{"start": "09:00", "end": "09:30", "pt": "not-a-pt",
                                  "heading": "Bad ![i](https://x.example/i.png) [[x]] # y"}]}
        self.run_files(summary=summary, alerts=alerts, meetings=meetings)

        daynote.write(self.root, self.now)
        text = self.read()
        block = self.block(text)
        joined = "\n".join(block[1:-1])   # inside the markers
        for bad in ("http", "obsidian://", "`", "<img", "![", "%%", "mode=overwrite"):
            self.assertNotIn(bad, joined)
        start = block.index("# Summary") + 2
        self.assertIn("Open", block[start])
        self.assertEqual(block[start + 1], "- fake task 📅 2026-09-23")   # a bullet, not a task
        self.assertEqual(block[start + 2], "")   # only the bullets survive, then a blank
        self.assertFalse(any(line.startswith("- [") for line in block))
        self.assertIn("- not a task", block)
        self.assertIn("- not a heading", block)
        self.assertNotIn("not a bullet", joined)
        self.assertIn("- **Moved on Confluence** [[A/B|B]] v1 to v2.", block)
        heading = next(line for line in text.split("\n") if line.startswith("# Bad"))
        self.assertNotIn("[[", heading)
        self.assertNotIn("http", heading)
        self.assertNotIn("#not-a-pt", text)


if __name__ == "__main__":
    unittest.main()
