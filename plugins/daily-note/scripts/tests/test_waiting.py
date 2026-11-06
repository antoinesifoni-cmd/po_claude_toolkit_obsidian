"""Tests for Waiting on me: the list write() puts in the morning block, close() refreshes in
place, and the Review line close() adds.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder. Names, channels and ids are made up.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

SLACK = "https://example-team.slack.com/archives/C0FAKE0001/p1790000000000001"
JIRA = "https://example.atlassian.net/browse/MYLE-1234"
CONF = "https://example.atlassian.net/wiki/spaces/PD/pages/123456/Rules+QA?focusedCommentId=99"
DOC = "https://docs.google.com/spreadsheets/d/1FakeSheetIdMadeUpForTheTests000000/edit"

ITEMS = {"items": [
    {"id": "slack:C0FAKE0001/1790000000.000001", "source": "Slack",
     "where": "#pt2311-scheduling", "who": "Julie Tremblay",
     "what": "Can you confirm the pilot dates?", "pt": "PT-2311",
     "when": "2026-09-22T15:23", "links": [SLACK, JIRA]},
    {"id": "gmail:conf1", "source": "Confluence", "where": "Rules QA", "who": "Marc Gagnon",
     "what": "mentioned you in a comment", "pt": None, "when": "2026-09-20", "links": [CONF]},
    {"id": "gmail:share1", "source": "Docs", "kind": "share", "who": "Sophie Roy",
     "what": "shared Pilot clinics", "when": "2026-09-21", "links": [DOC]},
    {"id": "gmail:old", "source": "Jira", "who": "Luc", "what": "too old",
     "when": "2026-09-17", "links": [JIRA]},
    {"id": "gmail:cleared", "source": "Jira", "who": "Luc", "what": "already cleared",
     "when": "2026-09-23", "links": [JIRA]},
    {"id": "evil", "source": "Slack ![x](https://evil.example/a.png)", "where": "## Heading",
     "who": "[[Note]] #tag", "what": "click [here](https://evil.example) or https://evil.example",
     "when": "2026-09-23", "links": ["https://evil.example/archives/C1/p1790000000000001",
                                      "javascript:alert(1)"]},
]}


class WaitingTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "daily-notes.json").write_text(json.dumps(
            {"folder": "Day2Day notes", "template": "Tools/Templates/Daily note.md"}),
            encoding="utf-8")
        self.put("Tools/Templates/Daily note.md", TEMPLATE)
        self.put(".daily-note/waiting-cleared.json",
                 json.dumps({"cleared": [{"id": "gmail:cleared", "on": "2026-09-22"}]}))
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

    def read(self):
        return self.note.read_text(encoding="utf-8")

    def section(self, text):
        lines = text.split("\n")
        at = lines.index(daynote.WAITING_HEADING)
        end = lines.index(daynote.END)
        return [l for l in lines[at + 1:end] if l.strip()]

    def test_morning_list_oldest_first_with_checked_links(self):
        self.put(".daily-note/run/waiting.json", json.dumps(ITEMS))
        out = daynote.write(self.root, self.now)
        got = self.section(self.read())
        self.assertEqual(out["waiting"], 3)   # too old, cleared and share past its day are gone
        self.assertEqual(got[0], "- **Confluence** Rules QA · Marc Gagnon: mentioned you in a "
                                 f"comment · 3d · [Confluence]({CONF})")
        self.assertEqual(got[1], "- **Slack** pt2311-scheduling · Julie Tremblay: Can you confirm "
                                 f"the pilot dates? #PT-2311 · 1d · [Slack]({SLACK}) [Jira]({JIRA})")
        self.assertNotIn("Sophie", "\n".join(got))   # a share shows its day and the next only
        evil = got[2]
        for bad in ("evil", "javascript", "[[", "#tag", "##", "!["):
            self.assertNotIn(bad, evil)
        self.assertTrue(evil.endswith("· today"))   # no link survived

    def test_cap_counts_the_rest(self):
        many = {"items": [{"id": f"s{i}", "source": "Slack", "who": f"P{i}", "what": "ask",
                           "when": "2026-09-23"} for i in range(13)]}
        self.put(".daily-note/run/waiting.json", json.dumps(many))
        daynote.write(self.root, self.now)
        got = self.section(self.read())
        self.assertEqual(len(got), 11)
        self.assertTrue(got[-1].startswith("- +3 more"))

    def test_not_checked_and_nothing(self):
        daynote.write(self.root, self.now)
        self.assertEqual(self.section(self.read()), [daynote.NO_ALERTS])
        self.put(".daily-note/run/waiting.json", json.dumps({"items": []}))
        daynote.write(self.root, self.now)
        self.assertEqual(self.section(self.read()), [daynote.NO_WAITING])

    def test_evening_refreshes_in_place_and_adds_a_review_line(self):
        self.put(".daily-note/run/waiting.json", json.dumps(ITEMS))
        daynote.write(self.root, self.now)
        morning = self.read()
        # The day goes by: the Slack question was answered, a new one came in.
        evening = {"items": [ITEMS["items"][1],
                             {"id": "slack:new", "source": "Slack group", "where": "PCA group",
                              "who": "Anush", "what": "Run the query tonight?",
                              "when": "2026-09-23T14:00", "links": []}]}
        self.put(".daily-note/run/waiting.json", json.dumps(evening))
        out = daynote.close(self.root, datetime(2026, 9, 23, 17, 30).astimezone())
        text = self.read()
        got = self.section(text)
        self.assertEqual(out["waiting"], "refreshed 2")
        self.assertEqual(len(got), 2)
        self.assertIn("Anush: Run the query tonight? · today", got[1])
        self.assertNotIn("Julie", text)
        # Everything above the list is as it was in the morning.
        cut = morning.index(daynote.WAITING_HEADING)
        self.assertEqual(text[:cut], morning[:cut])
        self.assertIn("- **Waiting on me** 2 still open, 1 for 2 days or more.", text)

    def test_evening_adds_the_list_to_an_older_block(self):
        old_block = TEMPLATE.replace("## Alert\n", "## Alert\n\n- No Confluence page moved (3 checked).\n")
        self.put("Day2Day notes/2026-09-23.md", old_block)
        self.put(".daily-note/run/waiting.json", json.dumps({"items": [ITEMS["items"][1]]}))
        daynote.close(self.root, datetime(2026, 9, 23, 17, 30).astimezone())
        text = self.read()
        self.assertIn("- No Confluence page moved (3 checked).\n\n## Waiting on me\n\n- **Confluence**", text)
        self.assertEqual(text.count(daynote.WAITING_HEADING), 1)

    def test_evening_without_a_scan_leaves_the_list(self):
        self.put(".daily-note/run/waiting.json", json.dumps(ITEMS))
        daynote.write(self.root, self.now)
        before = self.section(self.read())
        (self.run_dir / "waiting.json").unlink()
        out = daynote.close(self.root, datetime(2026, 9, 23, 17, 30).astimezone())
        self.assertEqual(out["waiting"], "not checked")
        self.assertEqual(self.section(self.read()), before)
        self.assertNotIn("**Waiting on me**", self.read())


if __name__ == "__main__":
    unittest.main()
