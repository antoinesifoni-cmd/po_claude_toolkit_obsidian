"""Tests for the rename/delete repair: reconcile, relink, unlink, and pull's guard.

Run from the repo root:
  python3 -m unittest discover -s plugins/confluence-sync/scripts/tests -t plugins/confluence-sync/scripts

Every test builds a throwaway vault in a temp folder. Nothing touches the network.
All note text is made up, since this repo is public.
"""

import json
from argparse import Namespace
from unittest import mock

from confsync import config, reconcile
from confsync.commands import link, sync
from confsync.hashing import HASH_ALGO, body_hash

from tests.test_sync import CFG, VaultTest, page

FOLDER = "Projets/PT-2402 - Consentement"
OLD = f"{FOLDER}/Untitled.md"
NEW = f"{FOLDER}/PRD - Formulaire de consentement.md"
PID = "5300001"
BODY = "# PRD\n\nLe patient signe le formulaire avant la visite.\n"


def note_text(pid=PID, body=BODY):
    return f"---\ntitle: PRD\npage_id: '{pid}'\nconfluence_version: 4\n---\n\n{body}"


class RepairCase(VaultTest):
    """A note synced at v4 under a linked folder, then moved around by each test."""

    def setUp(self):
        super().setUp()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(link, "VAULT", self.vault).start()
        self.write(OLD, note_text())
        self.save_mapping({OLD: {"page_id": PID, "title": "PRD", "version": 4,
                                 "hash": body_hash(BODY), "hash_algo": HASH_ALGO}})
        self.save_folders({FOLDER: {"folder_id": "900", "title": "PT-2402 - Consentement",
                                    "parent_id": "1"}})

    def write(self, key, text):
        p = self.vault / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def save_mapping(self, m):
        self.mapping_file.write_text(json.dumps(m), encoding="utf-8")

    def save_folders(self, f):
        self.folders_file.write_text(json.dumps(f), encoding="utf-8")

    def mapping(self):
        return json.loads(self.mapping_file.read_text(encoding="utf-8"))

    def folders(self):
        return json.loads(self.folders_file.read_text(encoding="utf-8"))

    def issues(self):
        return reconcile.find_issues(self.mapping(), self.folders())

    def rename(self, old, new):
        (self.vault / new).parent.mkdir(parents=True, exist_ok=True)
        (self.vault / old).rename(self.vault / new)


class FindTests(RepairCase):

    def test_nothing_missing_scans_nothing(self):
        with mock.patch.object(reconcile, "scan_page_ids") as scan:
            self.assertFalse(self.issues())
        scan.assert_not_called()

    def test_renamed_note_is_found_by_its_page_id(self):
        self.rename(OLD, NEW)
        issues = self.issues()
        self.assertEqual(issues.renamed, [(OLD, NEW, PID)])
        line = reconcile.report_lines(issues)[0]
        self.assertTrue(line.startswith(f"RENAMED? {OLD} -> {NEW}"))
        self.assertEqual(self.mapping()[OLD]["version"], 4)   # reporting changes nothing

    def test_deleted_note_is_missing(self):
        (self.vault / OLD).unlink()
        issues = self.issues()
        self.assertEqual(issues.missing, [(OLD, PID)])
        self.assertTrue(reconcile.report_lines(issues)[0].startswith(f"MISSING: {OLD}"))

    def test_two_copies_are_ambiguous(self):
        self.rename(OLD, NEW)
        self.write(f"{FOLDER}/Copie.md", note_text())
        issues = self.issues()
        self.assertEqual(issues.renamed, [])
        self.assertEqual(issues.ambiguous[0][1], [f"{FOLDER}/Copie.md", NEW])

    def test_conflict_copies_and_hidden_folders_are_not_notes(self):
        (self.vault / OLD).unlink()
        self.write(f"{FOLDER}/PRD.remote.md", note_text())
        self.write(".trash/Untitled.md", note_text())
        self.assertEqual(self.issues().missing, [(OLD, PID)])

    def test_renamed_folder_is_one_finding(self):
        new_folder = "Projets/PT-2402 - Consentement éclairé"
        (self.vault / FOLDER).rename(self.vault / new_folder)
        issues = self.issues()
        self.assertEqual(issues.folder_renamed, [(FOLDER, new_folder, "900")])
        lines = reconcile.report_lines(issues)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FOLDER RENAMED?"))


class RelinkTests(RepairCase):

    def relink(self, old, new):
        return self.run_quiet(link.cmd_relink, Namespace(old=str(self.vault / old),
                                                         new=str(self.vault / new)))

    def test_relink_keeps_version_hash_and_backs_up(self):
        self.rename(OLD, NEW)
        _, out = self.relink(OLD, NEW)
        m = self.mapping()
        self.assertNotIn(OLD, m)
        self.assertEqual(m[NEW]["version"], 4)
        self.assertEqual(m[NEW]["hash"], body_hash(BODY))
        self.assertIn("Relinked", out)
        backups = list((self.vault / ".confsync" / "backups").glob("*_mapping.json"))
        self.assertEqual(len(backups), 1)
        self.assertIn(OLD, json.loads(backups[0].read_text(encoding="utf-8")))
        self.assertFalse(self.issues())

    def test_relink_refuses_a_note_of_another_page(self):
        self.rename(OLD, NEW)
        self.write(f"{FOLDER}/Autre.md", note_text(pid="777"))
        with self.assertRaises(SystemExit):
            self.relink(OLD, f"{FOLDER}/Autre.md")
        self.assertIn(OLD, self.mapping())

    def test_relink_folder_moves_notes_inside(self):
        new_folder = "Projets/PT-2402 - Consentement éclairé"
        (self.vault / FOLDER).rename(self.vault / new_folder)
        _, out = self.relink(FOLDER, new_folder)
        self.assertEqual(list(self.mapping()), [f"{new_folder}/Untitled.md"])
        self.assertEqual(list(self.folders()), [new_folder])
        self.assertIn("1 note inside", out)
        self.assertFalse(self.issues())


class UnlinkTests(RepairCase):

    def test_unlink_forgets_only_the_link(self):
        (self.vault / OLD).unlink()
        (self.vault / ".confsync" / "base").mkdir()
        kept = self.vault / ".confsync" / "base" / f"{PID}.md"
        kept.write_text(BODY, encoding="utf-8")
        self.run_quiet(link.cmd_unlink, Namespace(path=str(self.vault / OLD)))
        self.assertEqual(self.mapping(), {})
        self.assertTrue(kept.exists())

    def test_unlink_folder_takes_gone_notes_with_it(self):
        (self.vault / OLD).unlink()
        (self.vault / FOLDER).rmdir()
        self.run_quiet(link.cmd_unlink, Namespace(path=str(self.vault / FOLDER)))
        self.assertEqual(self.mapping(), {})
        self.assertEqual(self.folders(), {})


class StatusTests(RepairCase):

    def status(self, file=None):
        from confsync.commands import status
        with mock.patch.object(status, "get_config", lambda: CFG), \
                mock.patch.object(status, "api", lambda cfg: None), \
                mock.patch.object(status, "VAULT", self.vault), \
                mock.patch.object(status, "MAPPING_FILE", self.mapping_file), \
                mock.patch.object(status, "FOLDERS_FILE", self.folders_file), \
                mock.patch.object(status, "get_page_meta", lambda c, s, pid: page(BODY, 4)):
            arg = str(self.vault / file) if file else None
            return self.run_quiet(status.cmd_status, Namespace(file=arg))[1]

    def test_renamed_note_is_not_reported_as_push_needed(self):
        self.rename(OLD, NEW)
        out = self.status()
        self.assertIn(f"RENAMED? {OLD} -> {NEW}", out)
        self.assertNotIn("push needed", out)

    def test_asking_about_the_new_name_explains_it(self):
        self.rename(OLD, NEW)
        out = self.status(NEW)
        self.assertIn("RENAMED?", out)
        self.assertNotIn("not linked", out)


class PullGuardTests(RepairCase):

    def test_pull_does_not_recreate_a_renamed_note(self):
        self.rename(OLD, NEW)
        self.remote = page(BODY, 4)
        ok, out = self.run_quiet(sync.pull_one, CFG, None, self.mapping(), OLD)
        self.assertFalse(ok)
        self.assertIn("gone from the vault", out)
        self.assertFalse((self.vault / OLD).exists())

    def test_link_still_creates_a_new_note(self):
        m = {"Projets/Neuf.md": {"page_id": PID, "title": "PRD", "version": 0,
                                 "hash": "", "hash_algo": HASH_ALGO}}
        self.remote = page(BODY, 4)
        ok, _ = self.run_quiet(sync.pull_one, CFG, None, m, "Projets/Neuf.md",
                               create_dirs=True)
        self.assertTrue(ok)
