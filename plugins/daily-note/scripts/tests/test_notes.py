"""Tests for the notes of the day: daynote.notes_cmd() and the note sections close() adds.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Same rules as test_write.py: every test builds a throwaway vault in a temp folder, and all
note text is made up, since this repo is public.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

TAIL = TEMPLATE[TEMPLATE.index("---\n# Task"):]

NOTE = """---
tags:
  - daily-note
---
# Sprint review
*09:30-10:00*
- [x] Demo the new appointment filter ✅ 2026-09-23

# Scheduling sync
#PT-2311 *13:00-13:30*
Talked about [[Already linked]] with Julie.

""" + TAIL


def props(created, updated, tags=None):
    lines = ["---"]
    if tags:
        lines += ["tags:"] + [f"  - {t}" for t in tags]
    lines += [f"Created: {created}", f"Updated: {updated}", "---", "Some text.", ""]
    return "\n".join(lines)


class NotesTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian" / "plugins" / "autodater").mkdir(parents=True)
        (self.root / ".obsidian" / "daily-notes.json").write_text(json.dumps(
            {"folder": "Day2Day notes", "template": "Tools/Templates/Daily note.md"}),
            encoding="utf-8")
        (self.root / ".obsidian" / "plugins" / "autodater" / "data.json").write_text(json.dumps(
            {"createdProperty": "Created", "updatedProperty": "Updated",
             "excludedFolders": ["Tools/Templates"]}), encoding="utf-8")
        self.put("Tools/Templates/Daily note.md", TEMPLATE)
        self.run_dir = self.root / ".daily-note" / "run"
        self.run_dir.mkdir(parents=True)
        self.now = datetime(2026, 9, 23, 17, 30).astimezone()
        self.note = self.root / "Day2Day notes" / "2026-09-23.md"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path

    def scan(self):
        out = daynote.notes_cmd(self.root, self.now)
        notes = json.loads((self.run_dir / "notes.json").read_text(encoding="utf-8"))["notes"]
        return out, {n["name"]: n for n in notes}

    def test_created_wins_over_edited_and_old_notes_are_left_out(self):
        self.put("Projects/PT-2311 - Scheduling/PT-2311 - Pilot checklist.md",
                 props("2026-09-23T10:15", "2026-09-23T16:40"))
        self.put("Ideas/Waiting room screen.md", props("2026-09-01", "2026-09-23T14:05:00"))
        self.put("Ideas/Old idea.md", props("2026-09-01", "2026-09-02"))
        self.put("Ideas/No properties.md", "Just text.\n")
        out, notes = self.scan()
        self.assertEqual(out, {"notes": 2, "created": 1, "edited": 1})
        pilot = notes["PT-2311 - Pilot checklist"]
        self.assertEqual((pilot["kind"], pilot["time"], pilot["pt"], pilot["heading"]),
                         ("created", "10:15", "PT-2311", "Pilot checklist"))
        room = notes["Waiting room screen"]
        self.assertEqual((room["kind"], room["time"], room["pt"]), ("edited", "14:05", None))

    def test_utc_values_are_read_in_local_time(self):
        utc = datetime(2026, 9, 23, 15, 0).astimezone().astimezone(
            __import__("datetime").timezone.utc)
        self.put("Ideas/Utc note.md", props(utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "2026-09-23"))
        _, notes = self.scan()
        self.assertEqual(notes["Utc note"]["time"], "15:00")

    def test_a_date_with_no_time_takes_the_file_time(self):
        path = self.put("Ideas/Date only.md", props("2026-09-01", "2026-09-23"))
        stamp = datetime(2026, 9, 23, 11, 20).timestamp()
        os.utime(path, (stamp, stamp))
        _, notes = self.scan()
        self.assertEqual((notes["Date only"]["kind"], notes["Date only"]["time"]), ("edited", "11:20"))

    def test_a_file_time_from_another_day_gives_no_time(self):
        # The file was really created today, not on the 23rd, so its creation time says nothing.
        self.put("Ideas/Created long ago.md", props("2026-09-23", "2026-09-23"))
        _, notes = self.scan()
        self.assertEqual((notes["Created long ago"]["kind"], notes["Created long ago"]["time"]),
                         ("created", None))

    def test_daily_notes_templates_dot_folders_and_tags(self):
        self.put("Day2Day notes/2026-09-22.md", props("2026-09-22", "2026-09-23"))
        self.put("Tools/Templates/Task Note.md", props("2026-09-23", "2026-09-23"))
        self.put(".trash/Gone.md", props("2026-09-23", "2026-09-23"))
        self.put("Day2Day notes/00-Task Note/26-09-23 - Ask Julie for dates.md",
                 props("2026-09-23T09:00", "2026-09-23T09:00", ["TaskNote", "PT-2402"]))
        out, notes = self.scan()
        self.assertEqual(list(notes), ["26-09-23 - Ask Julie for dates"])
        task = notes["26-09-23 - Ask Julie for dates"]
        self.assertEqual((task["heading"], task["pt"]), ("Ask Julie for dates", "PT-2402"))

    def test_close_puts_each_note_in_time_order_once(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.put("Projects/PT-2311 - Scheduling/PT-2311 - Pilot checklist.md",
                 props("2026-09-23T10:15", "2026-09-23T16:40"))
        self.put("Ideas/Waiting room screen.md", props("2026-09-01", "2026-09-23T14:05"))
        self.put("Ideas/Already linked.md", props("2026-09-23T13:10", "2026-09-23T13:10"))
        self.scan()
        (self.run_dir / "note-recaps.json").write_text(json.dumps({"notes": [
            {"path": "Projects/PT-2311 - Scheduling/PT-2311 - Pilot checklist.md",
             "recap": "Six checks before go-live. See https://evil.example for more."},
        ]}), encoding="utf-8")
        result = daynote.close(self.root, self.now)
        self.assertEqual(result["notes"], "added 2, 1 already linked")
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("""# Sprint review
*09:30-10:00*
- [x] Demo the new appointment filter ✅ 2026-09-23

# Pilot checklist
#PT-2311 *created 10:15*

**Recap:** Six checks before go-live. See for more.
**Note:** [[Projects/PT-2311 - Scheduling/PT-2311 - Pilot checklist|PT-2311 - Pilot checklist]]

# Scheduling sync
#PT-2311 *13:00-13:30*
Talked about [[Already linked]] with Julie.

# Waiting room screen
*edited 14:05*

**Note:** [[Ideas/Waiting room screen|Waiting room screen]]
""", text)

        # A second run adds nothing, and the lines it wrote are never offered to text-corrector.
        again = daynote.close(self.root, self.now)
        self.assertEqual(again["notes"], "added 0, 3 already linked")
        daynote.prose(self.root, self.now)
        own = json.loads((self.run_dir / "prose.json").read_text(encoding="utf-8"))["lines"]
        self.assertFalse([line for line in own if "created" in line or "**" in line])

    def test_close_refuses_a_path_outside_the_vault(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        (self.run_dir / "notes.json").write_text(json.dumps({"notes": [
            {"path": "../outside.md", "name": "outside", "kind": "created", "time": "10:00"},
            {"path": "Ideas/Missing.md", "name": "Missing", "kind": "created", "time": "10:00"},
        ]}), encoding="utf-8")
        result = daynote.close(self.root, self.now)
        self.assertEqual(result["notes"], "added 0, 2 refused")

    def test_close_without_a_scan_leaves_notes_alone(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.assertEqual(daynote.close(self.root, self.now)["notes"], "not run")


if __name__ == "__main__":
    unittest.main()
