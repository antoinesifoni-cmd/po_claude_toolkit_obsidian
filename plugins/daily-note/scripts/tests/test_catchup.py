"""Tests for closing a past day (--date), the morning reminders, and the I'm back note.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder. Names, ids and texts are made up.
"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

DOC = "1FakeDocId" + "A" * 34
SLACK = "https://example-team.slack.com/archives/C0FAKE0001/p1790000000000001"

BACK = {
    "from": "2026-11-24", "to": "2026-12-07",
    "projects": [
        {"pt": "PT-2311", "name": "Scheduling",
         "meetings": [{"date": "2026-11-24", "heading": "Scheduling sync",
                       "recap": "The pilot moved to January.", "doc": DOC, "tab": None},
                      {"date": "not a date", "heading": "Broken"}],
         "decisions": [{"text": "Load test dropped", "key": "MYLE-1234", "link": SLACK}],
         "jira": [{"key": "MYLE-1234", "text": "In QA to Done"}, {"key": "nope", "text": "x"}],
         "confluence": [{"path": "Projects/Plan.md", "text": "moved v14 to v17"},
                        {"path": "../outside.md", "text": "1 new page"}]},
        {"pt": "PT-9999", "name": "Empty"},
        {"pt": "bad", "name": "No id"},
    ],
    "other": {"meetings": [{"date": "2026-12-01", "heading": "All hands", "recap": "Q1 goals."}]},
}


class CatchUpTests(unittest.TestCase):

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

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    # ------------------------------------------------------------ --date

    def test_date_option(self):
        today = datetime.now().astimezone().date()
        self.assertEqual(daynote.parse_args(["close"]), ("close", None))
        self.assertEqual(daynote.parse_args(["today", "--date", today.isoformat()]), ("today", None))
        cmd, now = daynote.parse_args(["close", "--date", (today - timedelta(days=2)).isoformat()])
        self.assertEqual((cmd, now.date(), now.hour, now.minute),
                         ("close", today - timedelta(days=2), 23, 59))
        for bad in (["write", "--date", "2026-01-05"], ["close", "--date", "05/01/2026"],
                    ["close", "--date", (today + timedelta(days=1)).isoformat()],
                    ["close", "--when", "2026-01-05"], ["nope"], []):
            with self.assertRaises(daynote.Stop):
                daynote.parse_args(bad)

    def test_today_of_a_past_day(self):
        self.put("Day2Day notes/2026-10-30.md", TEMPLATE)
        out = daynote.today_cmd(self.root, daynote.past_now(date(2026, 11, 5)))
        self.assertEqual((out["date"], out["now"], out["past"]), ("2026-11-05", "23:59", True))
        self.assertEqual(out["mail_since"], "2026-10-30")
        self.assertEqual(out["workdays_missed"], 3)   # Nov 2, 3, 4

    def test_closing_a_past_day_needs_its_note(self):
        now = daynote.past_now(date(2026, 11, 5))
        with self.assertRaises(daynote.Stop):
            daynote.close(self.root, now, past=True)
        self.assertFalse((self.root / "Day2Day notes" / "2026-11-05.md").exists())
        self.put("Day2Day notes/2026-11-05.md", TEMPLATE)
        out = daynote.close(self.root, now, past=True)
        self.assertEqual(out["note"], "Day2Day notes/2026-11-05.md")
        self.assertIn(daynote.EOD_BEGIN, (self.root / "Day2Day notes" / "2026-11-05.md").read_text(encoding="utf-8"))

    # ------------------------------------------------------------ morning reminders

    def test_workdays_between(self):
        self.assertEqual(daynote.workdays_between(date(2026, 11, 6), date(2026, 11, 9)), 0)   # Fri to Mon
        self.assertEqual(daynote.workdays_between(date(2026, 11, 23), date(2026, 12, 8)), 10)

    def test_not_closed_and_back_alerts(self):
        self.put("Day2Day notes/2026-11/2026-11-23.md", TEMPLATE)   # never closed, in a month folder
        got = daynote.day_alerts(self.root, date(2026, 12, 8))
        self.assertEqual(len(got), 2)
        self.assertIn("**Not closed** The note of Nov 23 has no End of day. "
                      "Run /daily-note:end-my-day 2026-11-23 to close it.", got[0])
        self.assertIn("**Back from time off?** Your last note is from Nov 23, 10 workdays ago.", got[1])

    def test_no_alert_after_a_closed_weekend(self):
        self.put("Day2Day notes/2026-11-06.md", TEMPLATE + "\n" + daynote.EOD_BEGIN + "\n" + daynote.EOD_END + "\n")
        self.assertEqual(daynote.day_alerts(self.root, date(2026, 11, 9)), [])

    def test_write_shows_the_alerts(self):
        self.put("Day2Day notes/2026-11-05.md", TEMPLATE)
        daynote.write(self.root, datetime(2026, 11, 6, 8, 30).astimezone())
        text = (self.root / "Day2Day notes" / "2026-11-06.md").read_text(encoding="utf-8")
        alert = text[text.index("## Alert"):text.index(daynote.WAITING_HEADING)]
        self.assertIn("**Not closed** The note of Nov 5", alert)
        self.assertIn(daynote.NO_ALERTS, alert)   # no step wrote an alert file

    # ------------------------------------------------------------ I'm back

    def back(self, data=BACK, waiting=None):
        self.put(".daily-note/run/back.json", json.dumps(data))
        self.put(".daily-note/run/back-summary.md", "- Start with PT-2311: the pilot moved.\n- 3 asks wait on you.\n")
        if waiting is not None:
            self.put(".daily-note/run/waiting.json", json.dumps(waiting))
        return daynote.back_cmd(self.root, datetime(2026, 12, 8, 8, 30).astimezone())

    def test_back_note(self):
        self.put("Projects/Plan.md", "Plan.\n")
        out = self.back(waiting={"items": [
            {"id": "a", "source": "Slack", "who": "Julie", "what": "Pilot dates?", "when": "2026-11-25"},
            {"id": "b", "source": "Jira", "who": "Marc", "what": "too old", "when": "2026-11-20"},
            {"id": "c", "source": "Docs", "kind": "share", "who": "Sophie", "what": "shared Pilot plan",
             "when": "2026-11-26"}]})
        self.assertEqual((out["note"], out["groups"], out["waiting"]),
                         ("Day2Day notes/2026-12-08 - Back from OOO.md", 2, 2))
        text = (self.root / out["note"]).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ntags:\n  - daily-note\n  - back-from-ooo\nfrom: 2026-11-24\nto: 2026-12-07\n---\n"))
        self.assertIn("Away Nov 24 to Dec 7.", text)
        self.assertIn("# Summary\n\n- Start with PT-2311: the pilot moved.\n- 3 asks wait on you.\n", text)
        # A share shows for the whole range, not only its day and the next.
        self.assertIn("# Waiting on me\n\n- **Slack** Julie: Pilot dates? · 13d\n"
                      "- **Docs** Sophie: shared Pilot plan · 12d\n", text)
        self.assertIn("# PT-2311 Scheduling\n#PT-2311\n\n## Meetings you missed\n- **Nov 24** Scheduling sync: "
                      f"The pilot moved to January. [Transcript](https://docs.google.com/document/d/{DOC}/edit)\n", text)
        self.assertIn(f"## Decisions\n- ⚖️ **Decided (Slack):** Load test dropped MYLE-1234 [thread]({SLACK})\n", text)
        self.assertIn("## Jira\n- MYLE-1234 In QA to Done\n\n", text)
        self.assertIn("## Confluence\n- [[Projects/Plan|Plan]] moved v14 to v17\n- 1 new page\n", text)
        self.assertNotIn("Broken", text)
        self.assertNotIn("PT-9999", text)   # nothing to say
        self.assertNotIn("No id", text)
        self.assertIn("# Other\n\n## Meetings you missed\n- **Dec 1** All hands: Q1 goals.\n", text)
        self.assertIn("```tasks\nnot done\ndue after 2026-11-23\ndue before 2026-12-08\nsort by due\n```", text)

    def test_back_never_writes_over_a_note(self):
        self.back()
        with self.assertRaises(daynote.Stop):
            self.back()

    def test_back_needs_a_past_range(self):
        for bad in ({"from": "2026-12-01", "to": "2026-12-08"}, {"from": "2026-12-05", "to": "2026-12-01"},
                    {"from": "soon"}):
            with self.assertRaises(daynote.Stop):
                self.back(bad)
        self.assertFalse((self.root / "Day2Day notes" / "2026-12-08 - Back from OOO.md").exists())


if __name__ == "__main__":
    unittest.main()
