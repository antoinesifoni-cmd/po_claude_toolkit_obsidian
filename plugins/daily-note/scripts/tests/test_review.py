"""Tests for the interactive Review: the items close() keeps, review_list() and
review_apply(), the one code that acts on the answers.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder. All texts are made up.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

SLACK = "https://example-team.slack.com/archives/C0FAKE0001/p1790000000000001"
TODAY = "2026-09-23"   # the review runs that evening: created and done dates

NOTE = TEMPLATE.replace("%% start-my-day:end %%\n", """%% start-my-day:end %%

# Sprint review
*09:30-10:00*
- [ ] Book the pilot clinic
We agreed on the pilot scope

# Mobile daily
*11:00-11:15*
- release on Friday
""")

LOOSE = {"items": [
    {"kind": "action", "key": "Send Julie the clinic list",
     "text": "- **Action item** Send Julie the clinic list (Sprint review). Not a task yet.",
     "task": "Send Julie the clinic list", "heading": "Sprint review", "date": "2026-09-25", "pt": "PT-2311"},
    {"kind": "action", "key": "Ask legal about consent", "text": "- **Action item** Ask legal about consent. Not a task yet.",
     "task": "Ask legal about consent", "heading": None, "date": None},
    {"kind": "nodue", "key": "- [ ] Book the pilot clinic",
     "text": "- **No due date** Book the pilot clinic (Sprint review).", "line": "- [ ] Book the pilot clinic"},
    {"kind": "tag", "key": "Mobile daily", "text": "- **Tag?** Mobile daily has notes and no project tag.",
     "heading": "Mobile daily", "options": ["PT-2311"]},
    {"kind": "nonotes", "key": "Design check-in", "text": "- **No notes** Design check-in has nothing written."},
]}
MAP = {"items": [{"kind": "map", "key": "AI Scribe Weekly", "title": "AI Scribe Weekly", "days": 4,
                  "text": '- **Map?** "AI Scribe Weekly" came 4 times in 3 weeks, never tagged.'}]}
DECISIONS = {"decisions": [{"text": "Load test dropped", "pt": "PT-2311", "key": "MYLE-1234", "link": SLACK}]}
WAITING = {"items": [
    {"id": "slack:C1/1", "source": "Slack", "who": "Julie", "what": "Pilot dates?", "when": "2026-09-22"},
    {"id": "gmail:2", "source": "Jira", "who": "Marc", "what": "Check MYLE-1", "when": "2026-09-23"}]}


class ReviewTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "daily-notes.json").write_text(json.dumps(
            {"folder": "Day2Day notes", "template": "Tools/Templates/Daily note.md"}),
            encoding="utf-8")
        self.put("Tools/Templates/Daily note.md", TEMPLATE)
        self.put("Day2Day notes/CLAUDE.md", "# Daily notes\n\n## Meeting map\n\n| Title starts with | Kind | Project |\n"
                 "|---|---|---|\n| Mobile daily | mixed | |\n\n## Slack channels\n\n- #general\n")
        self.put("Day2Day notes/2026-09-23.md", NOTE)
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

    def read(self):
        return self.note.read_text(encoding="utf-8")

    def review_part(self):
        text = self.read()
        return text[text.index("## Review"):text.index(daynote.EOD_END)]

    def close(self):
        self.put(".daily-note/run/review-loose-ends.json", json.dumps(LOOSE))
        self.put(".daily-note/run/review-map.json", json.dumps(MAP))
        self.put(".daily-note/run/review-claude-md.md", "- **Update** PT-2311 CLAUDE.md State is old.\n")
        self.put(".daily-note/run/decisions.json", json.dumps(DECISIONS))
        self.put(".daily-note/run/waiting.json", json.dumps(WAITING))
        return daynote.close(self.root, self.now)

    def items(self):
        return {i["kind"] + ":" + i["text"][:20]: i for i in daynote.review_list(self.root, self.now)["items"]}

    def apply(self, answers):
        self.put(".daily-note/run/review-answers.json", json.dumps({"answers": answers}))
        return daynote.review_apply(self.root, self.now, clock=self.now)

    # ------------------------------------------------------------ close keeps the items

    def test_close_lists_and_keeps_the_items(self):
        out = self.close()
        self.assertEqual(out["review"], 9)
        review = self.review_part()
        self.assertIn("- **Action item** Send Julie the clinic list (Sprint review). Not a task yet.\n", review)
        self.assertIn("- **Update** PT-2311 CLAUDE.md State is old.\n", review)
        self.assertIn("- **Decision** Load test dropped: add it to the project CLAUDE.md or MYLE-1234?\n", review)
        self.assertIn("- **Waiting on me** 2 still open. The list is at the top of the note.", review)
        got = daynote.review_list(self.root, self.now)
        self.assertEqual(len(got["items"]), 9)
        kinds = [i["kind"] for i in got["items"]]
        self.assertEqual(sorted(set(kinds)), ["action", "decision", "map", "nodue", "nonotes", "note", "tag", "waiting"])
        action = got["items"][kinds.index("action")]
        self.assertEqual(action["data"]["task"], "Send Julie the clinic list")
        waiting = got["items"][kinds.index("waiting")]
        self.assertEqual([w["id"] for w in waiting["data"]["items"]], ["slack:C1/1", "gmail:2"])

    def test_nothing_to_flag_without_a_question(self):
        self.put(".daily-note/run/review-loose-ends.json", json.dumps({"items": []}))
        out = daynote.close(self.root, self.now)
        self.assertEqual(out["review"], 0)
        self.assertIn(daynote.NOTHING_TO_FLAG, self.review_part())

    # ------------------------------------------------------------ the answers

    def test_answers_change_the_note_and_the_review(self):
        self.close()
        ids = {i["kind"] + (":" + i["data"].get("task", "") if i["kind"] == "action" else ""): i["id"]
               for i in daynote.review_list(self.root, self.now)["items"]}
        out = self.apply([
            {"id": ids["action:Send Julie the clinic list"], "outcome": "done",
             "actions": [{"do": "task", "text": "Send Julie the clinic list", "heading": "Sprint review",
                          "date": "2026-09-25", "pt": "PT-2311"}]},
            {"id": ids["action:Ask legal about consent"], "outcome": "done",
             "actions": [{"do": "task", "text": "Ask legal about consent", "heading": None,
                          "date": "2026-09-24", "note": True}]},
            {"id": ids["nodue"], "outcome": "done",
             "actions": [{"do": "due", "line": "- [ ] Book the pilot clinic", "date": "2026-09-24"}]},
            {"id": ids["tag"], "outcome": "done", "actions": [{"do": "tag", "heading": "Mobile daily", "pt": "PT-2311"}]},
            {"id": ids["nonotes"], "outcome": "erased", "actions": []},
            {"id": ids["map"], "outcome": "done",
             "actions": [{"do": "map", "title": "AI Scribe Weekly", "kind": "project", "pt": "pt2402"}]},
            {"id": ids["waiting"], "outcome": "kept", "actions": [{"do": "clear", "ids": ["slack:C1/1"]}]},
            {"id": ids["decision"], "outcome": "done", "actions": []},
            {"id": "not:an-item", "outcome": "erased"},
        ])
        text = self.read()
        # Tasks: under their meeting, else under # Task, with tag, due and created dates.
        self.assertIn("- [ ] Book the pilot clinic 📅 2026-09-24\nWe agreed on the pilot scope\n\n"
                      f"- [ ] Send Julie the clinic list #PT-2311 📅 2026-09-25 ➕ {TODAY}\n", text)
        self.assertIn(f"# Task\n- [ ] Ask legal about consent #note 📅 2026-09-24 ➕ {TODAY}\n", text)
        self.assertEqual(len(out["task_note_lines"]), 1)
        self.assertEqual(text.split("\n")[out["task_note_lines"][0] - 1].strip(),
                         f"- [ ] Ask legal about consent #note 📅 2026-09-24 ➕ {TODAY}")
        self.assertIn("# Mobile daily\n#PT-2311 *11:00-11:15*", text)
        claude = (self.root / "Day2Day notes" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("| Mobile daily | mixed | |\n| AI Scribe Weekly | project | PT-2402 |\n\n## Slack channels", claude)
        cleared = json.loads((self.root / ".daily-note" / "waiting-cleared.json").read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in cleared["cleared"]], ["slack:C1/1"])
        # The Review keeps what was not settled, under a trace.
        self.assertEqual(out["trace"], "- Review done 17:30: 2 tasks, 1 date, 1 tag, 1 map row, "
                                       "1 cleared, 1 erased, 1 kept.")
        review = self.review_part()
        self.assertTrue(review.startswith("## Review\n\n- Review done 17:30:"))
        self.assertIn("**Update** PT-2311", review)
        self.assertIn("**Waiting on me**", review)
        self.assertNotIn("Action item", review)
        self.assertNotIn("No notes", review)
        self.assertEqual(out["left"], 2)
        # A second end-my-day the same day does not bring settled items back.
        out = self.close()
        review = self.review_part()
        self.assertTrue(review.startswith("## Review\n\n- Review done 17:30:"))
        self.assertNotIn("Action item", review)
        self.assertNotIn("**Decision**", review)
        self.assertIn("**Waiting on me** 1 still open", review)   # the cleared item is gone
        self.assertEqual(text.count("Send Julie the clinic list #PT-2311"), 1)

    def test_a_failed_action_keeps_the_item(self):
        self.close()
        nodue = next(i for i in daynote.review_list(self.root, self.now)["items"] if i["kind"] == "nodue")
        finish = next(i for i in daynote.review_list(self.root, self.now)["items"] if i["kind"] == "tag")
        out = self.apply([
            {"id": nodue["id"], "outcome": "done", "actions": [{"do": "due", "line": "- [ ] Not in the note", "date": "2026-09-24"}]},
            {"id": finish["id"], "outcome": "done", "actions": [{"do": "finish", "line": "- [ ] Book the pilot clinic"}]},
        ])
        self.assertEqual(out["failed"], [nodue["id"]])
        self.assertIn(f"- [x] Book the pilot clinic ✅ {TODAY}", self.read())
        self.assertIn("**No due date**", self.review_part())

    def test_apply_needs_an_end_of_day_block(self):
        self.put(".daily-note/review/2026-09-23.json", json.dumps({"items": [
            {"id": "note:x", "kind": "note", "text": "- x", "data": {}}]}))
        with self.assertRaises(daynote.Stop):
            self.apply([{"id": "note:x", "outcome": "erased"}])


if __name__ == "__main__":
    unittest.main()
