"""Tests for Slack decisions: daynote.channels_cmd() and the decision lines close() adds.

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Every test builds a throwaway vault in a temp folder. Channels, ids and names are made up.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

LINK_A = "https://example-team.slack.com/archives/C0FAKE0001/p1790000000000001?thread_ts=1790000000.000001&cid=C0FAKE0001"
LINK_B = "https://example-team.slack.com/archives/C0FAKE0002/p1790000000000002"

NOTE = TEMPLATE.replace("%% start-my-day:end %%\n", """%% start-my-day:end %%

# Scheduling sync
#PT-2311 *13:00-13:30*
- [ ] Ask Julie for the pilot dates
We talked about the pilot clinics

# Consent form wording
- reviewed
""")

DECISIONS = {"decisions": [
    {"text": "Load test dropped, the 2 minute check is enough", "pt": "PT-2311",
     "key": "MYLE-1234", "link": LINK_A, "heading": "Scheduling sync"},
    {"text": "Consent form v2 out of scope for the pilot", "pt": "PT-2402",
     "key": None, "link": LINK_B, "heading": "Consent form wording"},
    {"text": "Serena's sheet is the source of truth", "pt": None, "key": "not a key",
     "link": "https://evil.example/archives/C1/p1790000000000001", "heading": None},
    {"text": "", "link": LINK_B},
]}


class DecisionTests(unittest.TestCase):

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

    def read(self):
        return self.note.read_text(encoding="utf-8")

    # ------------------------------------------------------------ channels

    def test_channels_from_projects_and_the_general_list(self):
        self.put("Confluence Projects/PT-2311 - Scheduling/CLAUDE.md",
                 "# PT-2311\n\nSlack: #pt2311-scheduling, `#pt-2311-po`, C0GROUP001 (Julie, Marc, Sophie)\n")
        self.put("Confluence Projects/PT-2402 - Consent/CLAUDE.md", "slack: #pt2402-consent\n")
        self.put("Confluence Projects/PT-9999 - Old/CLAUDE.md", "No channel here.\n")
        self.put("Confluence Projects/Notes/CLAUDE.md", "Slack: #not-a-project\n")
        self.put("Day2Day notes/CLAUDE.md", "## Meeting map\n\n| A | skip | |\n\n"
                 "## Slack channels\n\n- #production-emergencies · outages\n- #cs1-releases, C0OTHER01\n\n"
                 "## Later\n\n- #not-this-one\n")
        self.put("Day2Day notes/2026-09/2026-09-15.md", "# Sync\n#PT-2311 *10:00-10:30*\n")
        self.put("Day2Day notes/2026-09/2026-09-01.md", "# Old\n#PT-2402 *10:00-10:30*\n")   # too old
        out = daynote.channels_cmd(self.root, self.now)
        got = {p["pt"]: p for p in out["projects"]}
        self.assertEqual(set(got), {"PT-2311", "PT-2402", "PT-9999"})
        self.assertEqual((got["PT-2311"]["ongoing"], got["PT-2311"]["last_tagged"]), (True, "2026-09-15"))
        self.assertFalse(got["PT-2402"]["ongoing"])
        self.assertEqual([c["name"] or c["id"] for c in got["PT-2311"]["channels"]],
                         ["pt2311-scheduling", "pt-2311-po", "C0GROUP001"])
        self.assertEqual(got["PT-2311"]["channels"][2]["label"], "Julie, Marc, Sophie")
        self.assertEqual([c["name"] or c["id"] for c in out["general"]],
                         ["production-emergencies", "cs1-releases", "C0OTHER01"])
        # What to read in full: the ongoing projects' channels, then the general ones.
        self.assertEqual([(c["name"] or c["id"], c["pt"]) for c in out["track"]],
                         [("pt2311-scheduling", "PT-2311"), ("pt-2311-po", "PT-2311"),
                          ("C0GROUP001", "PT-2311"), ("production-emergencies", None),
                          ("cs1-releases", None), ("C0OTHER01", None)])

    # ------------------------------------------------------------ the note

    def close(self, data=DECISIONS):
        self.put(".daily-note/run/decisions.json", json.dumps(data))
        return daynote.close(self.root, self.now)

    def test_decisions_go_under_their_section_or_in_decisions(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        out = self.close()
        text = self.read()
        self.assertEqual(out["decisions"], "added 3, 1 refused")
        # Under a paragraph: a blank line first, so the list does not join it.
        self.assertIn("We talked about the pilot clinics\n\n- ⚖️ **Decided (Slack):** Load test dropped, "
                      f"the 2 minute check is enough #PT-2311 MYLE-1234 [thread]({LINK_A})\n", text)
        # Under a list: right after it.
        self.assertIn("- reviewed\n- ⚖️ **Decided (Slack):** Consent form v2 out of scope for the "
                      f"pilot #PT-2402 [thread]({LINK_B})\n", text)
        # No section named: a Decisions section after the others, with no outside link.
        self.assertIn("# Decisions\n- ⚖️ **Decided (Slack):** Serena's sheet is the source of truth\n", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("not a key", text)
        self.assertLess(text.index("# Consent form wording"), text.index("# Decisions"))
        self.assertLess(text.index("# Decisions"), text.index("# Task"))

    def test_rerun_adds_nothing_and_a_new_one_joins_decisions(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.close()
        first = self.read()
        out = self.close()
        self.assertEqual(out["decisions"], "added 0, 3 already in the note, 1 refused")
        self.assertEqual(self.read().count("⚖️"), first.count("⚖️"))
        more = {"decisions": DECISIONS["decisions"][:3] + [
            {"text": "Flag stays OFF in prod until the pilot", "heading": "Not a section"}]}
        self.close(more)
        text = self.read()
        self.assertEqual(text.count("# Decisions"), 1)
        self.assertIn("source of truth\n- ⚖️ **Decided (Slack):** Flag stays OFF in prod until the pilot\n", text)

    def test_no_file_leaves_the_note_alone(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        out = daynote.close(self.root, self.now)
        self.assertEqual(out["decisions"], "not run")
        self.assertNotIn("⚖️", self.read())


if __name__ == "__main__":
    unittest.main()
