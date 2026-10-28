"""Tests for pull, resolve and the folder rename cascade.

Run from the repo root:
  python3 -m unittest discover -s plugins/confluence-sync/scripts/tests -t plugins/confluence-sync/scripts

Every test builds a throwaway vault in a temp folder and fakes Confluence, so nothing
touches the network. All note text is made up, since this repo is public.
"""

import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from confsync import base, config, frontmatter
from confsync.commands import sync
from confsync.hashing import HASH_ALGO, body_hash

CFG = {"base_url": "https://exemple.atlassian.net"}
PAGE_ID = "4410021"
NOTE = "Projets/Alertes/PRD - Alertes cliniques.md"

SYNCED = "# PRD\n\nLes alertes s'affichent dans le dossier patient.\n"
MINE = SYNCED + "\nAjout: seuil de tension artérielle à 140/90.\n"
THEIRS = SYNCED + "\nAjout de Marie-Ève: valider avec la Dre Gagnon.\n"


def page(md, version):
    return {
        "id": PAGE_ID, "title": "PRD - Alertes cliniques",
        "version": {"number": version, "createdAt": "2026-10-09T14:02:00Z"},
        "body": {"storage": {"value": md}},
        "_links": {"webui": f"/spaces/PT/pages/{PAGE_ID}/PRD"},
    }


class VaultTest(unittest.TestCase):
    """A temp vault with confsync's state paths pointed into it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name).resolve()
        state = self.vault / ".confsync"
        state.mkdir()
        self.mapping_file = state / "mapping.json"
        self.folders_file = state / "folders.json"
        stack = ExitStack()
        self.addCleanup(stack.close)
        for mod, name, value in [
            (config, "VAULT", self.vault), (config, "STATE_DIR", state),
            (config, "MAPPING_FILE", self.mapping_file),
            (config, "FOLDERS_FILE", self.folders_file),
            (config, "BASE_DIR", state / "base"), (base, "BASE_DIR", state / "base"),
            (frontmatter, "USERS_FILE", state / "users.json"),
            (sync, "VAULT", self.vault), (sync, "MAPPING_FILE", self.mapping_file),
            (sync, "FOLDERS_FILE", self.folders_file),
        ]:
            stack.enter_context(mock.patch.object(mod, name, value))
        stack.enter_context(mock.patch.object(sync, "storage_to_md", lambda html, *a: html))
        self.remote = None
        stack.enter_context(mock.patch.object(sync, "get_page_body",
                                              lambda cfg, s, pid: self.remote))

    def run_quiet(self, fn, *args, **kwargs):
        out = StringIO()
        with redirect_stdout(out):
            result = fn(*args, **kwargs)
        return result, out.getvalue()


class PullTests(VaultTest):

    def setUp(self):
        super().setUp()
        self.note = self.vault / NOTE
        self.note.parent.mkdir(parents=True)
        self.note.write_text(SYNCED, encoding="utf-8")
        self.mapping = {NOTE: {"page_id": PAGE_ID, "title": "PRD - Alertes cliniques",
                               "version": 7, "hash": body_hash(SYNCED),
                               "hash_algo": HASH_ALGO}}
        base.save_base(PAGE_ID, SYNCED)

    def pull(self, **kwargs):
        decisions = []
        ok, out = self.run_quiet(sync.pull_one, CFG, None, self.mapping, NOTE,
                                 decisions=decisions, **kwargs)
        return ok, out, decisions

    def body(self):
        return frontmatter.split_frontmatter(self.note.read_text(encoding="utf-8"))[1]

    def test_neither_side_changed_writes_nothing(self):
        self.remote = page(SYNCED, 7)
        ok, out, decisions = self.pull()
        self.assertFalse(ok)
        self.assertIn("already in sync", out)
        self.assertEqual(self.note.read_text(encoding="utf-8"), SYNCED)
        self.assertEqual(decisions, [])

    def test_local_edits_with_unchanged_page_are_kept(self):
        self.note.write_text(MINE, encoding="utf-8")
        self.remote = page(SYNCED, 7)
        ok, out, decisions = self.pull()
        self.assertFalse(ok)
        self.assertIn("push needed - skipped", out)
        self.assertEqual(self.note.read_text(encoding="utf-8"), MINE)
        self.assertEqual(self.mapping[NOTE]["version"], 7)
        self.assertEqual(len(decisions), 1)
        self.assertIn("push needed", decisions[0])
        self.assertIn("+2 -0", decisions[0])
        self.assertIn("no change since your last sync", decisions[0])

    def test_remote_change_with_clean_note_is_pulled(self):
        self.remote = page(THEIRS, 8)
        ok, _, decisions = self.pull()
        self.assertTrue(ok)
        self.assertEqual(self.body().strip(), THEIRS.strip())
        self.assertEqual(self.mapping[NOTE]["version"], 8)
        self.assertEqual(base.load_base(PAGE_ID).strip(), THEIRS.strip())
        self.assertEqual(decisions, [])

    def test_both_changed_is_a_conflict_and_keeps_the_note(self):
        self.note.write_text(MINE, encoding="utf-8")
        self.remote = page(THEIRS, 8)
        ok, out, decisions = self.pull()
        self.assertFalse(ok)
        self.assertIn("CONFLICT", out)
        self.assertEqual(self.note.read_text(encoding="utf-8"), MINE)
        side = self.note.with_suffix(".remote.md")
        self.assertIn("Marie-Ève", side.read_text(encoding="utf-8"))
        self.assertEqual(self.mapping[NOTE]["version"], 7)
        self.assertEqual(self.mapping[NOTE]["conflict_version"], 8)
        self.assertIn("CONFLICT", decisions[0])
        self.assertIn("+2 -0 since your last sync", decisions[0])

    def test_force_overwrites_local_edits(self):
        self.note.write_text(MINE, encoding="utf-8")
        self.remote = page(SYNCED, 7)
        ok, _, _ = self.pull(force=True)
        self.assertTrue(ok)
        self.assertNotIn("140/90", self.body())

    def test_missing_folder_is_not_recreated(self):
        self.note.unlink()
        self.note.parent.rmdir()
        self.remote = page(THEIRS, 8)
        ok, out, _ = self.pull()
        self.assertFalse(ok)
        self.assertIn("folder no longer exists", out)
        self.assertFalse(self.note.parent.exists())

    def test_link_may_create_the_folder(self):
        self.note.unlink()
        self.note.parent.rmdir()
        self.remote = page(THEIRS, 8)
        ok, _, _ = self.pull(create_dirs=True)
        self.assertTrue(ok)
        self.assertTrue(self.note.exists())

    def test_resolve_moves_the_sync_point_to_the_merged_version(self):
        self.note.write_text(MINE, encoding="utf-8")
        self.remote = page(THEIRS, 8)
        self.pull()
        self.mapping_file.write_text(json.dumps(self.mapping), encoding="utf-8")
        merged = MINE + "Ajout de Marie-Ève: valider avec la Dre Gagnon.\n"
        self.note.write_text(merged, encoding="utf-8")

        self.run_quiet(sync.cmd_resolve, Namespace(file=str(self.note)))

        entry = json.loads(self.mapping_file.read_text(encoding="utf-8"))[NOTE]
        self.assertEqual(entry["version"], 8)
        self.assertNotIn("conflict_version", entry)
        self.assertFalse(self.note.with_suffix(".remote.md").exists())
        self.assertNotEqual(body_hash(merged), entry["hash"])  # push needed
        self.assertIn("Marie-Ève", base.load_base(PAGE_ID))

    def test_resolve_without_a_conflict_refuses(self):
        self.mapping_file.write_text(json.dumps(self.mapping), encoding="utf-8")
        with self.assertRaises(SystemExit):
            sync.cmd_resolve(Namespace(file=str(self.note)))


class FolderRenameTests(VaultTest):
    """Keys written on Windows by <=0.10.0 use backslashes."""

    def test_old_backslash_keys_are_read_with_slashes(self):
        self.mapping_file.write_text(json.dumps({"Projets\\Alertes\\PRD.md": {}}),
                                     encoding="utf-8")
        self.assertEqual(list(config.load_json(self.mapping_file, {})),
                         ["Projets/Alertes/PRD.md"])

    def test_rel_uses_slashes(self):
        self.assertEqual(config.rel(self.vault / "Projets" / "PRD.md"), "Projets/PRD.md")

    def test_nested_rename_cascades_with_backslash_keys(self):
        (self.vault / "Projets" / "Alertes" / "Specs").mkdir(parents=True)
        (self.vault / "Projets" / "Alertes" / "Specs" / "PRD.md").write_text(
            SYNCED, encoding="utf-8")
        self.folders_file.write_text(json.dumps({
            "Projets\\Alertes": {"folder_id": "A", "title": "Alertes"},
            "Projets\\Alertes\\Specs": {"folder_id": "B", "title": "Specs"},
        }), encoding="utf-8")
        self.mapping_file.write_text(json.dumps({
            "Projets\\Alertes\\Specs\\PRD.md": {"page_id": PAGE_ID},
        }), encoding="utf-8")
        titles = {"A": "Alertes cliniques", "B": "Spécifications"}

        with mock.patch.object(sync, "get_folder_meta",
                               lambda cfg, s, fid: {"title": titles[fid]}):
            self.run_quiet(sync.sync_folders, CFG, None)

        new_dir = self.vault / "Projets" / "Alertes cliniques" / "Spécifications"
        self.assertTrue((new_dir / "PRD.md").exists())
        self.assertFalse((self.vault / "Projets" / "Alertes").exists())
        mapping = json.loads(self.mapping_file.read_text(encoding="utf-8"))
        self.assertEqual(list(mapping), ["Projets/Alertes cliniques/Spécifications/PRD.md"])
        folders = json.loads(self.folders_file.read_text(encoding="utf-8"))
        self.assertEqual(sorted(folders), ["Projets/Alertes cliniques",
                                           "Projets/Alertes cliniques/Spécifications"])


class LineChangesTests(unittest.TestCase):

    def test_counts_added_and_removed_lines(self):
        self.assertEqual(base.line_changes("a\nb\nc\n", "a\nB\nc\nd\n"), "+2 -1")

    def test_ignores_frontmatter(self):
        self.assertEqual(base.line_changes("---\nx: 1\n---\nsame\n", "same\n"), "+0 -0")


if __name__ == "__main__":
    unittest.main()
