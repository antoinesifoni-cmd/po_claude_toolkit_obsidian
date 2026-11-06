"""Tests for new pages on Confluence: newpages.find_new, and the add and ignore commands.

Run from the repo root:
  python3 -m unittest discover -s plugins/confluence-sync/scripts/tests -t plugins/confluence-sync/scripts

Every test builds a throwaway vault in a temp folder, and the Confluence search is faked:
nothing touches the network. All titles are made up, since this repo is public.
"""

import json
from argparse import Namespace
from unittest import mock

from confsync import newpages
from confsync.commands import link

from tests.test_sync import CFG, VaultTest

FOLDER = "Projets/PT-2402 - Consentement"
PRD = f"{FOLDER}/PRD.md"


def node(id_, title, type_="page", ancestors=(), by="Marc Gagnon", day="2026-11-05"):
    return {"id": id_, "type": type_, "title": title,
            "ancestors": [{"id": a, "type": t, "title": n} for a, t, n in ancestors],
            "history": {"createdBy": {"displayName": by}, "createdDate": f"{day}T14:02:00.000Z"}}


ROOT = ("1", "page", "Projets")
F900 = ("900", "folder", "PT-2402 - Consentement")
P500 = ("500", "page", "PRD")
TOOLS = ("77", "folder", "Tools: QA")
SPIKE = ("78", "folder", "Spike")
GONE = ("79", "folder", "Exports")

FOUND = [
    node("101", "Pilot checklist", ancestors=[ROOT, F900], day="2026-11-06"),
    node("78", "Spike", "folder", ancestors=[ROOT, F900], by="Julie Tremblay"),
    node("102", "Spike notes", ancestors=[ROOT, F900, SPIKE]),
    node("103", "Spike results", ancestors=[ROOT, F900, SPIKE]),
    node("104", "QA dashboard", ancestors=[ROOT, F900, TOOLS]),
    node("500", "PRD", ancestors=[ROOT, F900]),                       # linked already
    node("105", "PRD annex", ancestors=[ROOT, F900, P500], day="2026-11-04"),
    node("106", "Big export", ancestors=[ROOT, F900]),               # ignored
    node("107", "Export 2", ancestors=[ROOT, F900, GONE]),           # under an ignored folder
]


class NewPagesCase(VaultTest):

    def setUp(self):
        super().setUp()
        self.addCleanup(mock.patch.stopall)
        for name in ("VAULT",):
            mock.patch.object(link, name, self.vault).start()
        mock.patch.object(link, "MAPPING_FILE", self.mapping_file).start()
        mock.patch.object(link, "FOLDERS_FILE", self.folders_file).start()
        mock.patch.object(link, "get_config", lambda: CFG).start()
        mock.patch.object(link, "api", lambda cfg: None).start()
        (self.vault / FOLDER).mkdir(parents=True)
        (self.vault / PRD).write_text("---\npage_id: '500'\n---\n\nPRD.\n", encoding="utf-8")
        self.mapping_file.write_text(json.dumps({PRD: {"page_id": "500", "title": "PRD", "version": 3,
                                                       "hash": "x", "hash_algo": "body-v1"}}), encoding="utf-8")
        self.folders_file.write_text(json.dumps({FOLDER: {"folder_id": "900", "title": "PT-2402 - Consentement",
                                                          "parent_id": "1"}}), encoding="utf-8")
        (self.vault / ".confsync" / "ignored.json").write_text(json.dumps({"ignored": [
            {"id": "106"}, {"id": "79"}]}), encoding="utf-8")
        self.queries = []

        def fake_search(cfg, s, cql, start=0):
            self.queries.append(cql)
            if cql.startswith("id = "):
                want = cql.split("= ")[1]
                return {"results": [n for n in FOUND if n["id"] == want]}
            if "ancestor = 78" in cql:
                return {"results": [n for n in FOUND if n["id"] in ("102", "103")]}
            return {"results": FOUND}
        mock.patch.object(newpages, "search_cql", fake_search).start()

    def new(self):
        return newpages.find_new(CFG, None, json.loads(self.mapping_file.read_text(encoding="utf-8")),
                                 json.loads(self.folders_file.read_text(encoding="utf-8")))

    def test_one_search_finds_what_is_new_and_where_it_goes(self):
        items = self.new()
        self.assertEqual(len(self.queries), 1)
        self.assertIn("ancestor in (500, 900)", self.queries[0])
        self.assertIn('created >= now("-14d")', self.queries[0])
        got = {i["title"]: i for i in items}
        self.assertEqual(set(got), {"Pilot checklist", "Spike", "QA dashboard", "PRD annex"})
        self.assertEqual(got["Pilot checklist"]["dir"], FOLDER)
        self.assertEqual((got["Spike"]["type"], got["Spike"]["inside"]), ("folder", 2))   # its pages are on its line
        self.assertEqual(got["QA dashboard"]["dir"], f"{FOLDER}/Tools- QA")   # an unlinked folder on the way
        self.assertEqual(got["PRD annex"]["dir"], FOLDER)                      # under a linked page
        self.assertEqual(items[0]["title"], "Pilot checklist")                 # newest first

    def test_report_lines(self):
        lines = newpages.report_new(self.new())
        self.assertIn(f'NEW: "Pilot checklist" (page 101) in {FOLDER}, by Marc Gagnon, 2026-11-06. '
                      f'Add it: conf.py add 101 | ignore it: conf.py ignore 101', lines)
        self.assertIn(f'NEW FOLDER: "Spike" (folder 78) in {FOLDER}, 2 pages inside, by Julie Tremblay, '
                      f'2026-11-05. Add it: conf.py add 78 | ignore it: conf.py ignore 78', lines)

    def test_nothing_linked_means_no_search(self):
        self.assertEqual(newpages.find_new(CFG, None, {}, {}), [])
        self.assertEqual(self.queries, [])

    def test_add_a_page_under_an_unlinked_folder(self):
        pulled = []
        with mock.patch.object(link, "get_page_meta", lambda c, s, pid: {"title": "QA dashboard", "version": {"number": 1}}), \
                mock.patch.object(link, "get_folder_meta", lambda c, s, fid: {"title": "Tools: QA", "parentId": "900"}), \
                mock.patch.object(link, "pull_one", lambda *a, **k: pulled.append(a[3])):
            self.run_quiet(link.cmd_add, Namespace(ref="104"))
        mapping = json.loads(self.mapping_file.read_text(encoding="utf-8"))
        folders = json.loads(self.folders_file.read_text(encoding="utf-8"))
        self.assertEqual(mapping[f"{FOLDER}/Tools- QA/QA dashboard.md"]["page_id"], "104")
        self.assertEqual(folders[f"{FOLDER}/Tools- QA"]["folder_id"], "77")
        self.assertEqual(pulled, [f"{FOLDER}/Tools- QA/QA dashboard.md"])
        self.assertTrue(any((self.vault / ".confsync" / "backups").iterdir()))

    def test_add_a_folder_brings_its_pages(self):
        titles = {"102": "Spike notes", "103": "Spike results"}
        pulled = []
        with mock.patch.object(link, "get_page_meta", lambda c, s, pid: {"title": titles[pid], "version": {"number": 1}}), \
                mock.patch.object(link, "get_folder_meta", lambda c, s, fid: {"title": "Spike", "parentId": "900"}), \
                mock.patch.object(link, "pull_one", lambda *a, **k: pulled.append(a[3])):
            _, out = self.run_quiet(link.cmd_add, Namespace(ref="78"))
        self.assertTrue((self.vault / FOLDER / "Spike").is_dir())
        self.assertEqual(pulled, [f"{FOLDER}/Spike/Spike notes.md", f"{FOLDER}/Spike/Spike results.md"])
        self.assertIn("Added 3", out)
        self.assertEqual({i["title"] for i in self.new()}, {"Pilot checklist", "QA dashboard", "PRD annex"})

    def test_ignore_never_reports_it_again(self):
        self.run_quiet(link.cmd_ignore, Namespace(ref="101"))
        ignored = json.loads((self.vault / ".confsync" / "ignored.json").read_text(encoding="utf-8"))
        self.assertIn({"id": "101", "title": "Pilot checklist", "type": "page"},
                      [{k: v for k, v in i.items() if k != "on"} for i in ignored["ignored"]])
        self.assertNotIn("Pilot checklist", {i["title"] for i in self.new()})

    def test_add_refuses_a_note_that_exists(self):
        (self.vault / FOLDER / "Pilot checklist.md").write_text("Mine.\n", encoding="utf-8")
        with mock.patch.object(link, "get_page_meta", lambda c, s, pid: {"title": "x", "version": {"number": 1}}):
            with self.assertRaises(SystemExit):
                self.run_quiet(link.cmd_add, Namespace(ref="101"))
        self.assertEqual((self.vault / FOLDER / "Pilot checklist.md").read_text(encoding="utf-8"), "Mine.\n")
