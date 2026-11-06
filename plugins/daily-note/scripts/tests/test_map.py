"""Tests for the meeting map: daynote.map_cmd(), seen_cmd() and what write() and close()
do with a mapped meetings.json.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder. All titles are made up.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

MAP = """# Daily notes

Context for the daily-note skills.

## Meeting map

| Title starts with | Kind    | Project |
|-------------------|---------|---------|
| Touch point       | project | PT-2311 |
| Touch point L&D   | project | pt2402  |
| `Mobile daily`    | mixed   |         |
| equipe po         | mixed   |         |
| PO                | skip    |         |
| Pottery 5@7       | skip    |         |
| Broken row        | maybe   |         |
| No project        | project |         |

## Other context

| Not a map | skip | |
"""

MEETINGS = {"meetings": [
    {"start": "08:00", "end": "08:30", "title": "PO", "heading": "PO", "pt": None},
    {"start": "09:00", "end": "09:15", "title": "Mobile daily 🚀", "heading": "Mobile daily", "pt": None},
    {"start": "09:30", "end": "10:00", "title": "Équipe PO 🎉", "heading": "Équipe PO", "pt": None},
    {"start": "10:00", "end": "10:30", "title": "POC demo", "heading": "POC demo", "pt": None},
    {"start": "11:00", "end": "11:30", "title": "Touch point L&D Rx", "heading": "Touch point L&D Rx", "pt": None},
    {"start": "13:00", "end": "13:30", "title": "Touch point U&PM", "heading": "Touch point U&PM", "pt": None},
    {"start": "14:00", "end": "14:30", "title": "PT-2500 Touch point extra",
     "heading": "Touch point extra", "pt": "PT-2500"},
    {"start": "18:00", "end": "20:00", "title": "pottery 5@7 🍷", "heading": "pottery 5@7", "pt": None},
]}


def past_note(sections: str) -> str:
    """A closed daily note with the given meeting sections."""
    return TEMPLATE.replace("%% start-my-day:end %%\n", "%% start-my-day:end %%\n\n" + sections + "\n")


class MapTests(unittest.TestCase):

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
        self.now = datetime(2026, 9, 23, 17, 30).astimezone()
        self.note = self.root / "Day2Day notes" / "2026-09-23.md"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def meetings(self, data=MEETINGS):
        self.put(".daily-note/run/meetings.json", json.dumps(data))

    def mapped(self):
        return json.loads((self.run_dir / "meetings.json").read_text(encoding="utf-8"))

    def by_start(self):
        return {m["start"]: m for m in self.mapped()["meetings"]}

    # ------------------------------------------------------------ reading the map

    def test_reads_the_table_and_reports_bad_rows(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        rows, bad = daynote.read_map(self.root, daynote.vault_config(self.root))
        self.assertEqual([r["title"] for r in rows],
                         ["Touch point", "Touch point L&D", "Mobile daily", "equipe po", "PO", "Pottery 5@7"])
        self.assertEqual(rows[1]["pt"], "PT-2402")   # "pt2402" written loosely
        self.assertEqual(len(bad), 2)                # a wrong kind, a project with no id
        self.assertTrue(all("Not a map" not in b for b in bad))   # stops at the next heading

    # ------------------------------------------------------------ applying it

    def test_skip_project_and_mixed(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.meetings()
        out = daynote.map_cmd(self.root, self.now)
        m = self.by_start()
        # skip leaves the list, case and emoji do not matter
        self.assertNotIn("08:00", m)
        self.assertNotIn("18:00", m)
        self.assertEqual([s["start"] for s in self.mapped()["skipped"]], ["08:00", "18:00"])
        # "PO" is a whole word: it does not take "POC demo"
        self.assertNotIn("kind", m["10:00"])
        # mixed, accents ignored
        self.assertEqual(m["09:00"]["kind"], "mixed")
        self.assertEqual(m["09:30"]["kind"], "mixed")
        self.assertIsNone(m["09:00"]["pt"])
        # project, the longest row wins
        self.assertEqual((m["11:00"]["kind"], m["11:00"]["pt"]), ("project", "PT-2402"))
        self.assertEqual((m["13:00"]["kind"], m["13:00"]["pt"]), ("project", "PT-2311"))
        # the id in the title wins over the map, and the map still matches without it
        self.assertEqual((m["14:00"]["kind"], m["14:00"]["pt"]), ("project", "PT-2500"))
        self.assertEqual((out["skipped"], out["project"], out["mixed"]), (2, 3, 2))

    def test_no_map_file_changes_nothing(self):
        self.meetings()
        out = daynote.map_cmd(self.root, self.now)
        self.assertIsNone(out["map"])
        self.assertEqual(self.mapped()["meetings"], MEETINGS["meetings"])
        self.assertEqual(self.mapped()["skipped"], [])

    def test_calendar_not_checked(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.meetings({"error": "calendar down"})
        out = daynote.map_cmd(self.root, self.now)
        self.assertEqual(out["meetings"], "not checked")
        self.assertEqual(self.mapped(), {"error": "calendar down"})

    def test_write_gives_no_heading_to_skip_and_tags_project(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.meetings()
        daynote.map_cmd(self.root, self.now)
        daynote.write(self.root, self.now)
        text = self.note.read_text(encoding="utf-8")
        self.assertNotIn("# PO\n", text)
        self.assertNotIn("pottery", text)
        self.assertIn("# Touch point U&PM\n#PT-2311 *13:00-13:30*", text)
        self.assertIn("# Mobile daily\n*09:00-09:15*", text)

    def test_close_tags_an_existing_section_of_a_project_meeting(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.put("Day2Day notes/2026-09-23.md", past_note(
            "# Touch point U&PM\n*13:00-13:30*\n- talked pilots\n\n"
            "# Mobile daily\n*09:00-09:15*\n- release on Friday\n"))
        self.meetings({"meetings": [MEETINGS["meetings"][1], MEETINGS["meetings"][5]]})
        daynote.map_cmd(self.root, self.now)
        daynote.close(self.root, self.now)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("# Touch point U&PM\n#PT-2311 *13:00-13:30*", text)
        self.assertIn("# Mobile daily\n*09:00-09:15*", text)   # mixed: never tagged

    # ------------------------------------------------------------ growing the map

    def history(self, days, section):
        for d in days:
            self.put(f"Day2Day notes/2026-09/2026-09-{d:02d}.md", past_note(section))

    def test_recurring_untagged_meeting_is_asked(self):
        self.history([16, 17, 18], "# Design sync\n*10:00-10:30*\n")
        self.history([19], "# Design sync\n#PT-2311 *10:00-10:30*\n")
        self.history([1], "# Design sync\n*10:00-10:30*\n")   # older than 3 weeks
        self.meetings({"meetings": [{"start": "10:00", "end": "10:30", "title": "Design sync",
                                     "heading": "Design sync", "pt": None}]})
        out = daynote.map_cmd(self.root, self.now)
        review = (self.run_dir / "review-map.md").read_text(encoding="utf-8")
        self.assertEqual(out["ask"], 1)
        self.assertIn('**Map?** "Design sync" came 4 times in 3 weeks, untagged 3 times.', review)
        self.assertIn("Day2Day notes/CLAUDE.md", review)

    def test_not_asked_when_rare_mapped_or_tagged(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.history([16, 17], "# Design sync\n*10:00-10:30*\n")
        self.history([18, 19, 20], "# Mobile daily\n*09:00-09:15*\n\n# Scheduling sync\n*13:00-13:30*\n")
        self.meetings({"meetings": [
            {"start": "09:00", "end": "09:15", "title": "Mobile daily", "heading": "Mobile daily", "pt": None},
            {"start": "10:00", "end": "10:30", "title": "Design sync", "heading": "Design sync", "pt": None},
            {"start": "13:00", "end": "13:30", "title": "PT-2311 Scheduling sync",
             "heading": "Scheduling sync", "pt": "PT-2311"},
        ]})
        out = daynote.map_cmd(self.root, self.now)
        self.assertEqual(out["ask"], 0)
        self.assertEqual((self.run_dir / "review-map.md").read_text(encoding="utf-8"), "")

    def test_seen_lists_the_last_three_weeks(self):
        self.put("Day2Day notes/CLAUDE.md", MAP)
        self.history([16, 17, 18], "# Mobile daily 🚀\n*09:00-09:15*\n\n# My own topic\nno time here\n")
        self.history([19], "# Design sync\n#PT-2311 *10:00-10:30*\n")
        out = daynote.seen_cmd(self.root, self.now)
        got = {e["heading"]: e for e in out["meetings"]}
        self.assertEqual(set(got), {"Mobile daily 🚀", "Design sync"})   # sections with a time only
        self.assertEqual((got["Mobile daily 🚀"]["days"], got["Mobile daily 🚀"]["mapped"]), (3, "mixed"))
        self.assertEqual(got["Design sync"]["tags"], {"PT-2311": 1})

    # ------------------------------------------------------------ notes of the day

    def test_the_map_file_is_not_a_note_of_the_day(self):
        self.put("Day2Day notes/CLAUDE.md", "---\nCreated: 2026-09-23T09:00\nUpdated: 2026-09-23T10:00\n---\n" + MAP)
        self.put("Projects/Plan.md", "---\nCreated: 2026-09-23T11:00\n---\nText.\n")
        daynote.notes_cmd(self.root, self.now)
        notes = json.loads((self.run_dir / "notes.json").read_text(encoding="utf-8"))["notes"]
        self.assertEqual([n["path"] for n in notes], ["Projects/Plan.md"])


if __name__ == "__main__":
    unittest.main()
