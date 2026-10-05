"""Tests for the task-note skill's script: tasknote.scan(), check() and apply().

Run from the repo root:
  python3 -m unittest discover -s plugins/daily-note/scripts/tests -t plugins/daily-note/scripts

Same rules as the other tests: every test builds a throwaway vault in a temp folder, and
all note text is made up, since this repo is public. FakeCli stands in for the Obsidian
CLI and copies its quirks: no exit code, and "Title 1.md" when a note exists already.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import tasknote
from daynote import Stop

FOLDER = "Day2Day notes/00-Task Note"
CONFIG = {"task_note": {"rules": [{
    "keyword": "#note",
    "template": "Task Note",
    "folder": FOLDER,
    "link": "[[{title}|📎]]",
    "title_words": 8,
    "properties": {"tags": ["TaskNote", "{tags}"], "source": "[[{source}]]"},
}]}}
RULES = [tasknote.check_rule(CONFIG["task_note"]["rules"][0], 1)]

TEMPLATE = """---
tags:
  - TaskNote
---

## Notes
"""

NOTE = """---
tags:
  - daily-note
---
# Sprint review
*09:30-10:00*
- [ ] #PT-2311 Ask Julie for the pilot dates before the clinic visit #note 📅 2026-10-07 ➕ 2026-10-05
- [ ] Book the pilot clinic 📅 2026-10-08
- [x] Prep the release plan #note ✅ 2026-10-05

# Design check-in
- [ ] Review the mockups with the design team [[Review the mockups|📎]] #note 📅 2026-10-09
- [ ] Send the consent form to [legal](https://example.com/legal?a=b) #PT-2402 #note
Not a task, but it says #note

```
- [ ] An example in a code block #note
```
"""

EXPECTED = """---
tags:
  - daily-note
---
# Sprint review
*09:30-10:00*
- [ ] #PT-2311 Ask Julie for the pilot dates before the clinic visit [[Ask Julie for pilot dates|📎]] 📅 2026-10-07 ➕ 2026-10-05
- [ ] Book the pilot clinic 📅 2026-10-08
- [x] Prep the release plan [[Prep the release plan|📎]] ✅ 2026-10-05

# Design check-in
- [ ] Review the mockups with the design team [[Review the mockups|📎]] 📅 2026-10-09
- [ ] Send the consent form to [legal](https://example.com/legal?a=b) #PT-2402 [[Send the consent form to legal|📎]]
Not a task, but it says #note

```
- [ ] An example in a code block #note
```
"""

SYNCED = """---
confluence_url: https://example.atlassian.net/wiki/spaces/XX/pages/1
---
- [ ] Update the handoff page #note
"""

NOW = datetime(2026, 10, 5, 17, 30).astimezone()
TITLES = {"1": "Ask Julie for pilot dates", "4": "Send the consent form to legal"}


class FakeCli:
    """The Obsidian CLI, as far as the script uses it."""

    def __init__(self, root, templates=None, answers=True):
        self.root, self.answers, self.calls = root, answers, []
        self.templates = {"Task Note": TEMPLATE} if templates is None else templates
        self.props = {}

    def __call__(self, *args):
        self.calls.append(args)
        if not self.answers:
            return ""
        cmd, opts = args[0], dict(a.split("=", 1) for a in args[1:])
        if cmd == "version":
            return "1.13.7 (installer 1.12.7)"
        if cmd == "template:read":
            text = self.templates.get(opts["name"])
            return text if text is not None else 'Error: Template folder "Templates" not found.'
        if cmd == "create":
            if opts.get("template") not in self.templates:
                return 'Error: Template folder "Templates" not found.'
            path = base = self.root / opts["path"]
            n = 1
            while path.exists():   # what the real CLI does
                path, n = base.with_name(f"{base.stem} {n}.md"), n + 1
            path.write_text(self.templates[opts["template"]], encoding="utf-8")
            return f"Created: {path.relative_to(self.root).as_posix()}"
        if cmd == "property:set":
            self.props.setdefault(opts["path"], {})[opts["name"]] = (opts["value"], opts["type"])
            return f"Set {opts['name']}: {opts['value']}"
        return f"Error: unknown command {cmd}"

    def created(self):
        return [dict(a.split("=", 1) for a in c[1:])["path"] for c in self.calls if c[0] == "create"]


class Vault(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".obsidian").mkdir()
        self.put(".obsidian/templates.json", json.dumps({"folder": "Templates"}))
        self.put(".obsidian/daily-notes.json", json.dumps(
            {"folder": "Day2Day notes", "template": "Templates/Daily note"}))
        self.put("Templates/Task Note.md", "- [ ] An example task in the template #note\n")
        self.put("Templates/Daily note.md", "# Task\n")
        (self.root / FOLDER).mkdir(parents=True)
        self.cli = FakeCli(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def read(self, rel):
        with open(self.root / rel, encoding="utf-8", newline="") as f:
            return f.read()

    def titles(self, titles):
        self.put(".daily-note/run/task-titles.json", json.dumps({"titles": titles}))

    def scan(self, *args):
        return tasknote.scan(self.root, list(args), RULES)

    def apply(self, ids=None):
        return tasknote.apply(self.root, ids, NOW, RULES, self.cli)


class LineTests(unittest.TestCase):
    """Where the link goes, and that nothing else in the line moves."""

    def line(self, before, link="[[X|📎]]"):
        return tasknote.new_line(before, RULES[0], link)

    def test_before_the_first_field(self):
        self.assertEqual(
            self.line("- [ ] #PT-2311 Ask Julie #note 📅 2026-10-07 ➕ 2026-10-05"),
            "- [ ] #PT-2311 Ask Julie [[X|📎]] 📅 2026-10-07 ➕ 2026-10-05")

    def test_keyword_after_the_fields(self):
        self.assertEqual(self.line("- [ ] Ask Julie 📅 2026-10-07 #note"),
                         "- [ ] Ask Julie [[X|📎]] 📅 2026-10-07")

    def test_tag_after_the_fields_stays(self):
        self.assertEqual(self.line("- [ ] Ask Julie 📅 2026-10-07 #PT-2311 #note"),
                         "- [ ] Ask Julie [[X|📎]] 📅 2026-10-07 #PT-2311")

    def test_priority_comes_first(self):
        self.assertEqual(
            self.line("- [x] Validate the timeline #note ⏫ ➕ 2026-09-29 📅 2026-09-29 ✅ 2026-10-01"),
            "- [x] Validate the timeline [[X|📎]] ⏫ ➕ 2026-09-29 📅 2026-09-29 ✅ 2026-10-01")

    def test_date_glued_to_the_text_and_trailing_space_kept(self):
        self.assertEqual(self.line("- [ ] List the features #note📅 2026-10-02 ➕ 2026-09-30 "),
                         "- [ ] List the features [[X|📎]] 📅 2026-10-02 ➕ 2026-09-30 ")

    def test_no_field_goes_at_the_end(self):
        self.assertEqual(self.line("- [ ] Check the [job board](https://example.com/jobs) #note"),
                         "- [ ] Check the [job board](https://example.com/jobs) [[X|📎]]")

    def test_keyword_first(self):
        self.assertEqual(self.line("- [ ] #note Ask Julie"), "- [ ] Ask Julie [[X|📎]]")

    def test_block_link_stays_last(self):
        self.assertEqual(self.line("- [ ] Ask Julie #note ^a1b2c3"), "- [ ] Ask Julie [[X|📎]] ^a1b2c3")
        self.assertEqual(self.line("- [ ] Ask Julie 📅 2026-10-07 ^a1b2c3"),
                         "- [ ] Ask Julie [[X|📎]] 📅 2026-10-07 ^a1b2c3")

    def test_recurrence_and_ids(self):
        self.assertEqual(self.line("- [ ] Weekly report #note 🔁 every week 🆔 abc123 📅 2026-10-09"),
                         "- [ ] Weekly report [[X|📎]] 🔁 every week 🆔 abc123 📅 2026-10-09")

    def test_indent_and_callout_kept(self):
        self.assertEqual(self.line("\t- [ ] Sub task #note 📅 2026-10-07"),
                         "\t- [ ] Sub task [[X|📎]] 📅 2026-10-07")
        self.assertEqual(self.line("> - [/] In a callout #note"), "> - [/] In a callout [[X|📎]]")

    def test_keyword_is_a_whole_tag_any_case(self):
        self.assertEqual(self.line("- [ ] Ask Julie #Note"), "- [ ] Ask Julie [[X|📎]]")
        self.assertEqual(self.line("- [ ] Ask Julie #notes"), "- [ ] Ask Julie #notes [[X|📎]]")

    def test_link_added_once(self):
        once = self.line("- [ ] Ask Julie #note 📅 2026-10-07")
        self.assertEqual(self.line(once), once)

    def test_only_the_keyword_goes_when_no_link(self):
        self.assertEqual(self.line("- [ ] Ask Julie [[X|📎]] #note 📅 2026-10-07", None),
                         "- [ ] Ask Julie [[X|📎]] 📅 2026-10-07")


class TitleTests(unittest.TestCase):

    def test_task_text(self):
        self.assertEqual(
            tasknote.task_text("#PT-2311 follow up on the [comments](https://example.com/a?b=c) "
                               "in [[PT-2311 - Handoff|the handoff]] **today** ✌️"),
            "follow up on the comments in the handoff today")

    def test_safe_title(self):
        self.assertEqual(tasknote.safe_title('fix: the "A/B" test?'), "Fix the A B test")
        self.assertEqual(tasknote.safe_title("iPhone build notes"), "iPhone build notes")
        self.assertEqual(tasknote.safe_title(".hidden name."), "Hidden name")
        self.assertEqual(tasknote.safe_title("2026-10-06"), "")
        self.assertEqual(tasknote.safe_title("con"), "")
        self.assertEqual(tasknote.safe_title(" [] "), "")
        long = tasknote.safe_title("word " * 30)
        self.assertLessEqual(len(long), tasknote.MAX_TITLE)
        self.assertFalse(long.endswith(" "))

    def test_a_tag_inside_the_text_asks_for_a_title(self):
        def title(line):
            return tasknote.make_item(1, "n.md", 0, line, "", 0, RULES[0], {})["title"]
        self.assertIsNone(title("- [ ] Prep a release plan for #PT-2003 📅 2026-10-05"))
        self.assertIsNone(title("- [ ] Prep the plan #SWAT"))
        self.assertEqual(title("- [ ] #PT-2003 #SWAT prep the plan #note 📅 2026-10-05"),
                         "Prep the plan")

    def test_rules_are_checked(self):
        rule = dict(CONFIG["task_note"]["rules"][0])
        for key, value in (("keyword", "note"), ("folder", "../outside"),
                           ("folder", ".hidden"), ("link", "{title}"), ("title_words", 0),
                           ("template", "")):
            with self.subTest(key=key, value=value):
                with self.assertRaises(Stop):
                    tasknote.check_rule(dict(rule, **{key: value}), 1)


class DayVault(Vault):
    """Today's note, one task note that exists, a synced note and a trashed one."""

    def setUp(self):
        super().setUp()
        self.put("Day2Day notes/2026-10-05.md", NOTE)
        self.put(f"{FOLDER}/Review the mockups.md", TEMPLATE)
        self.put("Confluence Projects/PT-2311 - Scheduling/Handoff.md", SYNCED)
        self.put(".trash/Old note.md", "- [ ] An old task #note\n")


class ScanTests(DayVault):

    def test_batch_finds_the_keyword_tasks(self):
        out = self.scan()
        self.assertEqual(out["mode"], "batch")
        self.assertEqual([(i["task"], i["title"], i["has_note"]) for i in out["items"]], [
            ("Ask Julie for the pilot dates before the clinic visit", None, False),
            ("Prep the release plan", "Prep the release plan", False),
            ("Review the mockups with the design team", "Review the mockups with the design team", True),
            ("Send the consent form to legal", None, False),
        ])
        self.assertEqual(out["need_titles"], [1, 4])
        self.assertEqual(out["items"][0]["where"], "2026-10-05 > Sprint review")
        reasons = sorted(r["reason"] for r in out["refused"])
        self.assertEqual(len(reasons), 2)
        self.assertTrue(reasons[0].startswith("#note on a line that is not a task"))
        self.assertTrue(reasons[1].startswith("Confluence-synced note"))
        saved = json.loads(self.read(".daily-note/run/task-note.json"))
        self.assertEqual(saved["items"][0]["tags"], ["PT-2311"])

    def test_a_new_scan_drops_old_titles(self):
        self.titles({"1": "Old title"})
        self.scan()
        self.assertFalse((self.root / ".daily-note/run/task-titles.json").exists())

    def test_single_line_with_no_keyword(self):
        out = self.scan("Day2Day notes/2026-10-05.md", "8")
        self.assertEqual(out["mode"], "single")
        self.assertEqual([i["title"] for i in out["items"]], ["Book the pilot clinic"])

    def test_single_selection(self):
        out = self.scan("Day2Day notes/2026-10-05.md", "6-9")
        self.assertEqual(len(out["items"]), 3)

    def test_single_refuses(self):
        for note, line in (("Day2Day notes/2026-10-05.md", "6"),
                           ("Day2Day notes/2026-10-05.md", "99"),
                           ("Day2Day notes/2026-10-05.md", "17"),
                           ("Confluence Projects/PT-2311 - Scheduling/Handoff.md", "4"),
                           ("Day2Day notes/nope.md", "1"),
                           ("../outside.md", "1")):
            with self.subTest(note=note, line=line):
                with self.assertRaises(Stop):
                    self.scan(note, line)


class ApplyTests(DayVault):

    def test_check_says_what_happens(self):
        self.put(f"{FOLDER}/Prep the release plan.md", TEMPLATE)
        self.scan()
        self.titles(TITLES)
        states = [(i["id"], i["state"]) for i in tasknote.check(self.root, RULES)["items"]]
        self.assertEqual(states, [(1, "new"), (2, "exists"), (3, "has a note"), (4, "new")])

    def test_batch(self):
        self.scan()
        self.titles(TITLES)
        out = self.apply()
        self.assertEqual(self.read("Day2Day notes/2026-10-05.md"), EXPECTED)
        self.assertEqual([r["result"] for r in out["results"]],
                         ["created", "created", "has a note", "created"])
        self.assertEqual(self.cli.created(), [f"{FOLDER}/Ask Julie for pilot dates.md",
                                              f"{FOLDER}/Prep the release plan.md",
                                              f"{FOLDER}/Send the consent form to legal.md"])
        props = self.cli.props[f"{FOLDER}/Ask Julie for pilot dates.md"]
        self.assertEqual(props["tags"], ('["TaskNote", "PT-2311"]', "list"))
        self.assertEqual(props["source"], ("[[2026-10-05]]", "text"))
        self.assertEqual(self.cli.props[f"{FOLDER}/Prep the release plan.md"]["tags"],
                         ('["TaskNote"]', "list"))
        self.assertEqual(len(out["backups"]), 1)
        self.assertEqual(self.read(out["backups"][0]), NOTE)

    def test_run_twice_changes_nothing(self):
        self.scan()
        self.titles(TITLES)
        self.apply()
        self.assertEqual(self.scan()["items"], [])
        line = self.scan("Day2Day notes/2026-10-05.md", "7")["items"][0]
        self.assertTrue(line["has_note"])
        out = self.apply()
        self.assertEqual(out["results"][0]["result"], "has a note")
        self.assertEqual(out["backups"], [])
        self.assertEqual(self.read("Day2Day notes/2026-10-05.md"), EXPECTED)

    def test_existing_note_is_linked_never_created_again(self):
        self.put(f"{FOLDER}/Prep the release plan.md", "my own notes\n")
        self.scan()
        out = self.apply({2})
        self.assertEqual(out["results"][0]["result"], "linked")
        self.assertEqual(self.cli.created(), [])
        self.assertEqual(self.read(f"{FOLDER}/Prep the release plan.md"), "my own notes\n")
        self.assertIn("[[Prep the release plan|📎]] ✅", self.read("Day2Day notes/2026-10-05.md"))

    def test_only_the_chosen_ids(self):
        self.scan()
        out = self.apply({2, 9})
        self.assertEqual([(r["id"], r["result"]) for r in out["results"]],
                         [(2, "created"), (9, "skipped")])
        note = self.read("Day2Day notes/2026-10-05.md")
        self.assertIn("Ask Julie for the pilot dates before the clinic visit #note", note)

    def test_no_title_is_skipped(self):
        self.scan()
        out = self.apply({1})
        self.assertEqual(out["results"][0]["result"], "skipped")
        self.assertEqual(self.cli.created(), [])

    def test_same_title_twice_makes_one_note(self):
        self.scan()
        self.titles({"1": "Prep the release plan"})
        out = self.apply({1, 2})
        self.assertEqual([r["result"] for r in out["results"]], ["created", "linked"])
        self.assertEqual(self.cli.created(), [f"{FOLDER}/Prep the release plan.md"])

    def test_a_name_used_elsewhere_gets_a_path_link(self):
        self.put("PDP/Prep the release plan.md", "another note\n")
        self.scan()
        self.apply({2})
        self.assertIn(f"[[{FOLDER}/Prep the release plan|📎]]",
                      self.read("Day2Day notes/2026-10-05.md"))

    def test_moved_line_is_found_changed_line_is_skipped(self):
        self.scan()
        self.titles(TITLES)
        note = self.read("Day2Day notes/2026-10-05.md")
        note = note.replace("# Sprint review\n", "# Sprint review\nA line added meanwhile\n")
        note = note.replace("Prep the release plan #note", "Prep the release plan, renamed #note")
        self.put("Day2Day notes/2026-10-05.md", note)
        out = self.apply({1, 2})
        self.assertEqual([(r["result"], r.get("detail")) for r in out["results"]], [
            ("created", None), ("skipped", "the task line changed since the scan")])
        self.assertEqual(self.cli.created(), [f"{FOLDER}/Ask Julie for pilot dates.md"])
        self.assertIn("[[Ask Julie for pilot dates|📎]] 📅", self.read("Day2Day notes/2026-10-05.md"))

    def test_nothing_changes_when_the_cli_does_not_answer(self):
        self.cli = FakeCli(self.root, answers=False)
        self.scan()
        with self.assertRaises(Stop) as stop:
            self.apply()
        self.assertIn("Nothing was changed", str(stop.exception))
        self.assertEqual(self.read("Day2Day notes/2026-10-05.md"), NOTE)
        self.assertFalse((self.root / ".daily-note/backups").exists())

    def test_nothing_changes_without_the_template(self):
        self.cli = FakeCli(self.root, templates={})
        self.scan()
        with self.assertRaises(Stop) as stop:
            self.apply()
        self.assertIn('Template folder "Templates" not found', str(stop.exception))
        self.assertEqual(self.read("Day2Day notes/2026-10-05.md"), NOTE)

    def test_nothing_changes_without_the_folder(self):
        (self.root / FOLDER / "Review the mockups.md").unlink()
        (self.root / FOLDER).rmdir()
        self.scan()
        with self.assertRaises(Stop):
            self.apply()
        self.assertEqual(self.cli.created(), [])

    def test_line_endings_and_bom_kept(self):
        self.put("Day2Day notes/2026-10-05.md", "﻿" + NOTE.replace("\n", "\r\n"))
        self.scan()
        self.titles(TITLES)
        self.apply()
        self.assertEqual(self.read("Day2Day notes/2026-10-05.md"),
                         "﻿" + EXPECTED.replace("\n", "\r\n"))


if __name__ == "__main__":
    unittest.main()
