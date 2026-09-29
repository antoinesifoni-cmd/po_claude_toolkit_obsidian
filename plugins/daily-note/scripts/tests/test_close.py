"""Tests for the end-my-day and meeting-recap writes: daynote.prose(), close() and recap().

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Same rules as test_write.py: every test builds a throwaway vault in a temp folder, and all
note text is made up, since this repo is public. The Google Doc ids are fake.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import daynote
from tests.test_write import TEMPLATE

TAIL = TEMPLATE[TEMPLATE.index("---\n# Task"):]   # the template's closing part
DOC_A = "1FakeDocId" + "A" * 34
DOC_B = "1FakeDocId" + "B" * 34
DOC_C = "1FakeDocId" + "C" * 34

# Today's note in the evening: the morning block, then what the user wrote during the day.
# He renamed "Scheduling Weekly Sync" to "Scheduling sync", and wrote a topic of his own.
NOTE = """---
tags:
  - daily-note
---
%% start-my-day:begin %%

# Summary

Busy morning with two meetings.

## Alert

- No Confluence page moved (72 checked).

%% start-my-day:end %%

# Sprint review
*09:30-10:00*
- [x] Demo the new appointment filter ✅ 2026-09-23
- [ ] Book the pilot clinic
nothing worth mentionning

# Scheduling sync
#PT-2311 *13:00-13:30*
- [ ] Ask Julie for the pilot dates 📅 2026-09-24

# Consent form wording
Reviewed the wording with [[PT-2402 - Consent form]].


""" + TAIL

MEETINGS = {"meetings": [
    {"start": "09:30", "end": "10:00", "title": "Sprint review ✌️",
     "heading": "Sprint review", "pt": None, "doc": DOC_B},
    {"start": "11:00", "end": "11:30", "title": "Design check-in",
     "heading": "Design check-in", "pt": None, "doc": None},
    {"start": "13:00", "end": "13:30", "title": "PT-2311 Scheduling Weekly Sync",
     "heading": "Scheduling Weekly Sync", "pt": "PT-2311", "doc": DOC_A},
    {"start": "16:00", "end": "16:30", "title": "PT-2402 Pilot debrief",
     "heading": "Pilot debrief", "pt": "PT-2402", "doc": None},
]}

RECAPS = {"recaps": [
    {"heading": "Scheduling Weekly Sync", "start": "13:00", "end": "13:30", "pt": "PT-2311",
     "doc": DOC_A, "tab": "t.abc123xyz",
     "recap": "The pilot starts in October. Julie sends the clinic list.",
     "my_actions": ["Confirm the pilot dates"]},
    {"heading": "Sprint review", "start": "09:30", "end": "10:00", "pt": None,
     "doc": DOC_B, "tab": None, "recap": "The filter demo went well.", "my_actions": []},
    {"heading": "Ghost", "start": "08:00", "end": "08:30", "doc": "../../evil", "recap": "x"},
]}

TAGS = {"tags": [
    {"heading": "Consent form wording", "start": None, "end": None, "tag": "PT-2402"},
    {"heading": "Scheduling sync", "start": "13:00", "end": "13:30", "tag": "PT-2402"},
    {"heading": "Sprint review", "start": "09:30", "end": "10:00", "tag": "PT-2311"},
    {"heading": "Consent form wording", "tag": "#pt-2402; rm"},
]}

CORRECTIONS = {"corrections": [
    {"before": "nothing worth mentionning", "after": "nothing worth mentioning"},
    {"before": "- [ ] Book the pilot clinic", "after": "- [x] Book the pilot clinic"},
    {"before": "Reviewed the wording with [[PT-2402 - Consent form]].",
     "after": "Reviewed the wording with [[PT-2402 - Consent forms]]."},
    {"before": "- [ ] Ask Julie for the pilot dates 📅 2026-09-24",
     "after": "- [ ] Ask Julie for the pilot dates 📅 2026-09-25"},
    {"before": "- [x] Demo the new appointment filter ✅ 2026-09-23",
     "after": "- [x] Demo the new appointment filter; done ✅ 2026-09-23"},
    {"before": "# Sprint review", "after": "# Sprint reviews"},
    {"before": "A line that is not in the note", "after": "A line that isn't in the note"},
]}

WRAPUP = "The filter demo went well and the pilot moved to October."
REVIEW_ENDS = "- **No due date** Book the pilot clinic (Sprint review). It never shows in Today.\n"
REVIEW_CLAUDE = ("- **Update** [[Confluence Projects/PT-2311 - Scheduling/CLAUDE|PT-2311 CLAUDE.md]]"
                 " State says November. Today the pilot moved to October.\n")

# The note after close(): every line the script added or changed, and nothing else.
EXPECTED = """---
tags:
  - daily-note
---
%% start-my-day:begin %%

# Summary

Busy morning with two meetings.

## Alert

- No Confluence page moved (72 checked).

%% start-my-day:end %%

# Sprint review
#PT-2311 *09:30-10:00*
- [x] Demo the new appointment filter ✅ 2026-09-23
- [ ] Book the pilot clinic
nothing worth mentioning

**Recap:** The filter demo went well.
**Transcript:** [Google Doc](https://docs.google.com/document/d/DOC_B/edit)

# Design check-in
*11:00-11:30*

# Scheduling sync
#PT-2311 *13:00-13:30*
- [ ] Ask Julie for the pilot dates 📅 2026-09-24

**Recap:** The pilot starts in October. Julie sends the clinic list.
**Transcript:** [Google Doc](https://docs.google.com/document/d/DOC_A/edit?tab=t.abc123xyz)

# Consent form wording
#PT-2402
Reviewed the wording with [[PT-2402 - Consent form]].


# Pilot debrief
#PT-2402 *16:00-16:30*

%% end-my-day:begin %%

# End of day

The filter demo went well and the pilot moved to October.

## Review

- **Update** [[Confluence Projects/PT-2311 - Scheduling/CLAUDE|PT-2311 CLAUDE.md]] State says November. Today the pilot moved to October.
- **No due date** Book the pilot clinic (Sprint review). It never shows in Today.

%% end-my-day:end %%

""".replace("DOC_A", DOC_A).replace("DOC_B", DOC_B) + TAIL


class CloseTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "daily-notes.json").write_text(json.dumps(
            {"folder": "Day2Day notes", "template": "Tools/Templates/Daily note.md"}),
            encoding="utf-8")
        self.put("Tools/Templates/Daily note.md", TEMPLATE)
        (self.root / ".daily-note" / "run").mkdir(parents=True)
        self.now = datetime(2026, 9, 23, 17, 30).astimezone()
        self.note = self.root / "Day2Day notes" / "2026-09-23.md"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def run_file(self, name, content):
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self.put(f".daily-note/run/{name}", text)

    def evening_run(self):
        self.run_file("meetings.json", MEETINGS)
        self.run_file("recaps.json", RECAPS)
        self.run_file("tags.json", TAGS)
        self.run_file("corrections.json", CORRECTIONS)
        self.run_file("wrapup.md", WRAPUP)
        self.run_file("review-loose-ends.md", REVIEW_ENDS)
        self.run_file("review-claude-md.md", REVIEW_CLAUDE)

    def read(self):
        with open(self.note, encoding="utf-8", newline="") as f:
            return f.read()

    def backups(self):
        folder = self.root / ".daily-note" / "backups"
        return sorted(folder.iterdir()) if folder.exists() else []

    def test_close_completes_the_note_and_changes_nothing_else(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.evening_run()

        result = daynote.close(self.root, self.now)

        self.assertEqual(self.read(), EXPECTED)
        self.assertEqual(result["corrections"], "1 applied, 4 refused, 2 skipped")
        self.assertEqual(result["meetings"], "added 2")
        self.assertEqual(result["tags"], "added 2")
        self.assertEqual(result["recaps"], "added 2, 1 refused, bad doc id or no heading")
        self.assertEqual(result["block"], "inserted")
        self.assertEqual(self.backups()[0].read_text(encoding="utf-8"), NOTE)

    def test_rerun_adds_nothing_twice(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.evening_run()
        daynote.close(self.root, self.now)

        result = daynote.close(self.root, self.now)

        self.assertEqual(self.read(), EXPECTED)
        self.assertEqual(result["meetings"], "none missing")
        self.assertEqual(result["tags"], "added 0")
        self.assertTrue(result["recaps"].startswith("added 0, 2 already in the note"))
        self.assertEqual(result["block"], "unchanged")   # nothing to write, so no backup
        self.assertEqual(len(self.backups()), 1)

    def test_rerun_rebuilds_the_block_in_place(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.evening_run()
        daynote.close(self.root, self.now)
        self.run_file("wrapup.md", "Second version.")

        result = daynote.close(self.root, self.now)

        text = self.read()
        self.assertEqual(result["block"], "replaced")
        self.assertIn("Second version.", text)
        self.assertNotIn(WRAPUP, text)
        self.assertEqual(text.count(daynote.EOD_BEGIN), 1)

    def test_missing_run_files_leave_the_note_alone_and_say_so(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)

        result = daynote.close(self.root, self.now)

        self.assertEqual(result["corrections"], "not run")
        self.assertEqual(result["meetings"], "not checked")
        text = self.read()
        self.assertTrue(text.startswith(NOTE[:NOTE.index("---\n# Task")]))
        self.assertIn(daynote.NO_WRAPUP, text)
        self.assertIn(daynote.NO_REVIEW, text)

    def test_empty_review_files_say_nothing_to_flag_once(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.run_file("review-loose-ends.md", "")
        self.run_file("review-claude-md.md", "\n")

        daynote.close(self.root, self.now)

        text = self.read()
        self.assertEqual(text.count(daynote.NOTHING_TO_FLAG), 1)
        self.assertNotIn(daynote.NO_REVIEW, text)

    def test_close_without_a_note_starts_from_the_template(self):
        self.run_file("meetings.json", MEETINGS)

        result = daynote.close(self.root, self.now)

        self.assertTrue(result["created"])
        text = self.read()
        heads = [line for line in text.split("\n") if line.startswith("# ")]
        self.assertEqual(heads, ["# Summary", "# Sprint review", "# Design check-in",
                                 "# Scheduling Weekly Sync", "# Pilot debrief",
                                 "# End of day", "# Task"])
        self.assertTrue(text.endswith(daynote.EOD_END + "\n\n" + TAIL))

    def test_broken_markers_write_nothing(self):
        broken = NOTE.replace("# Consent form wording", daynote.EOD_BEGIN + "\n# Consent form wording")
        self.put("Day2Day notes/2026-09-23.md", broken)
        self.evening_run()

        with self.assertRaises(daynote.Stop):
            daynote.close(self.root, self.now)
        self.assertEqual(self.read(), broken)
        self.assertEqual(self.backups(), [])

    def test_prose_lists_only_what_the_user_wrote(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)

        result = daynote.prose(self.root, self.now)

        saved = json.loads((self.root / ".daily-note/run/prose.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["lines"], [
            "- [x] Demo the new appointment filter ✅ 2026-09-23",
            "- [ ] Book the pilot clinic",
            "nothing worth mentionning",
            "- [ ] Ask Julie for the pilot dates 📅 2026-09-24",
            "Reviewed the wording with [[PT-2402 - Consent form]].",
        ])
        self.assertEqual(result["lines"], 5)

    def test_prose_skips_what_the_skills_wrote(self):
        self.put("Day2Day notes/2026-09-23.md", EXPECTED)

        daynote.prose(self.root, self.now)

        saved = json.loads((self.root / ".daily-note/run/prose.json").read_text(encoding="utf-8"))
        self.assertIn("nothing worth mentioning", saved["lines"])
        for line in saved["lines"]:
            self.assertFalse(line.startswith(("**Recap:**", "**Transcript:**", "#")), line)
            self.assertNotIn(line, (WRAPUP, "- " + REVIEW_ENDS.strip()[2:]))

    def test_a_correction_only_ever_fixes_words(self):
        lines = ["Line one, same text", "Line one, same text", "```", "code in a fense", "```",
                 "trailing spaces kept  ", "Mettre a jour la page"]
        fixes = [
            {"before": "Line one, same text", "after": "Line one, the same text"},
            {"before": "code in a fense", "after": "code in a fence"},
            {"before": "trailing spaces kept  ", "after": "trailing spaces kept"},
            {"before": "Mettre a jour la page", "after": "Update the page right now please"},
        ]
        out, counts = daynote.apply_corrections(lines, fixes, "note.md")
        self.assertEqual(out[:2], ["Line one, the same text"] * 2)   # every copy of the line
        self.assertEqual(out[3], "code in a fense")                  # code is never touched
        self.assertEqual(out[5], "trailing spaces kept  ")           # no change left to make
        self.assertEqual(out[6], "Mettre a jour la page")            # a rewrite, refused
        self.assertEqual(counts, "1 applied, 1 refused, 1 skipped")

    def test_recap_adds_one_meeting_and_nothing_else(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.run_file("meetings.json", MEETINGS)
        self.run_file("recaps.json", {"recaps": [
            {"heading": "Design check-in", "start": "11:00", "end": "11:30", "pt": None,
             "doc": DOC_C, "tab": "t.x1", "recap": "Colours are final."}]})

        result = daynote.recap(self.root, self.now)

        self.assertEqual(result["recaps"], "added 1, with 1 new heading")
        self.assertTrue(result["written"])
        text = self.read()
        self.assertIn("# Design check-in\n*11:00-11:30*\n\n**Recap:** Colours are final.\n"
                      f"**Transcript:** [Google Doc](https://docs.google.com/document/d/{DOC_C}"
                      "/edit?tab=t.x1)\n\n# Scheduling sync", text)
        self.assertNotIn(daynote.EOD_BEGIN, text)
        self.assertEqual(text.replace(text[text.index("# Design"):text.index("# Scheduling")], ""),
                         NOTE)

        again = daynote.recap(self.root, self.now)
        self.assertEqual(again["recaps"], "added 0, 1 already in the note")
        self.assertFalse(again["written"])

    def test_outside_text_is_made_inert(self):
        self.put("Day2Day notes/2026-09-23.md", NOTE)
        self.run_file("recaps.json", {"recaps": [
            {"heading": "Sprint review", "start": "09:30", "end": "10:00", "doc": DOC_B,
             "tab": "t.ok&x=1", "recap": "See https://x.example/a ![i](https://x.example/i.png)"
             " `rm` and [[Some note]]\n# not a heading"}]})
        self.run_file("review-loose-ends.md",
                      "- [Open](obsidian://adv-uri?vault=V&mode=overwrite) now\nnot a bullet\n")

        daynote.close(self.root, self.now)

        text = self.read()
        recap = next(line for line in text.split("\n") if line.startswith("**Recap:**"))
        self.assertEqual(recap, "**Recap:** See rm and [[Some note]] not a heading")
        self.assertIn(f"https://docs.google.com/document/d/{DOC_B}/edit)", text)   # bad tab dropped
        self.assertNotIn("x.example", text)
        self.assertNotIn("obsidian://", text)
        self.assertIn("- Open now", text)
        self.assertNotIn("not a bullet", text)

    def test_time_lines_typed_by_hand_are_read_too(self):
        for line, when in (("*10:45-11:00*", (10, 45, 11, 0)),
                           ("#PT-2311*10:45-11:00*", (10, 45, 11, 0)),
                           ("#PT-2402 *11:15-11:30*", (11, 15, 11, 30)),
                           ("*7:30-8h30*", (7, 30, 8, 30)),
                           ("*8h-9h30*", (8, 0, 9, 30)),
                           ("#PT-2402 review of this version", None),
                           ("Call at 10:45-11:00 with Julie", None)):
            self.assertEqual(daynote.time_range(line), when, line)
        note = NOTE.replace("# Scheduling sync\n#PT-2311 *13:00-13:30*",
                            "# Scheduling sync\n#PT-2311*13h-13h30*")
        self.assertNotEqual(note, NOTE)
        self.put("Day2Day notes/2026-09-23.md", note)
        self.run_file("meetings.json", MEETINGS)

        daynote.close(self.root, self.now)

        text = self.read()
        self.assertNotIn("# Scheduling Weekly Sync", text)   # found by its time slot
        self.assertLess(text.index("# Design check-in"), text.index("# Scheduling sync"))

    def test_a_tag_joins_the_time_line_or_sits_under_the_heading(self):
        def tag(*section):
            lines = list(section) + ["# Next"]
            return daynote.insert_tag(lines, {"at": 0, "stop": len(section)}, "PT-1")[:-1]

        self.assertEqual(tag("# A", "*9h-9h30*", "notes"), ["# A", "#PT-1 *9h-9h30*", "notes"])
        self.assertEqual(tag("# A", "notes"), ["# A", "#PT-1", "notes"])
        self.assertEqual(tag("# A", "| x | y |"), ["# A", "#PT-1", "", "| x | y |"])
        self.assertEqual(tag("# A", "---"), ["# A", "#PT-1", "", "---"])   # not a heading

    def test_headings_match_the_calendar_despite_tags_and_emojis(self):
        self.assertEqual(daynote.title_key("#PT-2311 Scheduling Weekly Sync ✌️"),
                         daynote.title_key("Scheduling Weekly Sync"))
        self.assertEqual(daynote.title_key("PT2311: Intake Q&A, round 2"),
                         daynote.title_key("Intake Q&A, round 2"))
        self.assertNotEqual(daynote.title_key("Design daily"), daynote.title_key("Sprint daily"))


if __name__ == "__main__":
    unittest.main()
