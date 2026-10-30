"""Round-trip tests for the Markdown <-> storage converter.

Run from the repo root:
  python3 -m unittest discover -s plugins/confluence-sync/scripts/tests -t plugins/confluence-sync/scripts

Each construct is pushed (md_to_storage) and pulled back (storage_to_md), and the
Markdown must come back identical. Storage samples mirror what Confluence Cloud stored
for real pages (checked 2026-10-28). All text is made up, since this repo is public.
"""

import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from confsync import attachments, frontmatter, transforms
from confsync.transforms import md_to_storage, storage_to_md

CFG = {"base_url": "https://exemple.atlassian.net", "jira_project_keys": ["PT"]}
PAGE_ID = "4410021"


class ConverterTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name).resolve()
        state = self.vault / ".confsync"
        state.mkdir()
        (state / "users.json").write_text(json.dumps(
            {"marie": {"account_id": "acc-marie", "display_name": "Marie-Ève Tremblay"}}),
            encoding="utf-8")
        (state / "mapping.json").write_text(json.dumps(
            {"Projets/PRD - Alertes.md": {"page_id": "77", "title": "PRD - Alertes cliniques"}}),
            encoding="utf-8")
        (self.vault / "Projets").mkdir()
        (self.vault / "Projets" / "PRD - Alertes.md").write_text(
            "---\nconfluence_space: PT\n---\nTexte\n", encoding="utf-8")
        self.note = self.vault / "Projets" / "Note.md"
        stack = ExitStack()
        self.addCleanup(stack.close)
        for mod, name, value in [
            (transforms, "VAULT", self.vault), (transforms, "KEEP_DIR", state / "keep"),
            (transforms, "EMOJI_FILE", state / "emoji.json"),
            (transforms, "MAPPING_FILE", state / "mapping.json"),
            (transforms, "USERS_FILE", state / "users.json"),
            (transforms, "PLANTUML_JAR", state / "none.jar"),
            (frontmatter, "USERS_FILE", state / "users.json"),
            (attachments, "VAULT", self.vault),
            (attachments, "ATTACHMENTS_FILE", state / "attachments.json"),
        ]:
            stack.enter_context(mock.patch.object(mod, name, value))
        # Image upload: pretend every embed is a file already attached under its own name.
        stack.enter_context(mock.patch.object(attachments, "push_image",
                                              lambda cfg, s, pid, name, note: name))

    def push(self, md):
        with redirect_stdout(StringIO()):
            return md_to_storage(md, CFG, None, PAGE_ID, self.note)

    def pull(self, storage):
        with redirect_stdout(StringIO()):
            return storage_to_md(storage, CFG, None, PAGE_ID, None, "PT")

    def round_trip(self, md):
        storage = self.push(md)
        self.assertEqual(self.pull(storage), md.strip() + "\n", msg=storage)
        return storage


class PanelTests(ConverterTest):

    def test_each_panel_kind(self):
        for kind, needle in [("info", 'ac:name="info"'), ("success", 'ac:name="tip"'),
                             ("warning", 'ac:name="note"'), ("error", 'ac:name="warning"'),
                             ("note", '<ac:adf-attribute key="panel-type">note')]:
            with self.subTest(kind):
                storage = self.round_trip(f"> [!{kind}]\n> Valider le seuil avec la **Dre Gagnon**.")
                self.assertIn(needle, storage)

    def test_custom_panel_keeps_colour_and_icon(self):
        storage = self.round_trip("> [!panel|#EAE6FF|:note:|atlassian-note]\n> Rappel")
        self.assertIn('<ac:parameter ac:name="bgColor">#EAE6FF</ac:parameter>', storage)

    def test_alias_comes_back_as_its_group(self):
        self.assertEqual(self.pull(self.push("> [!tip]\n> Astuce")), "> [!success]\n> Astuce\n")

    def test_panel_with_nested_content(self):
        self.round_trip("> [!info]\n> Statut: `🟢 In scope`\n>\n> - [ ] Envoyer la spec @marie 📅 2026-11-03")

    def test_unknown_callout_type_stays_a_quote(self):
        self.assertNotIn("structured-macro", self.push("> [!quote]\n> Texte"))


class BlockTests(ConverterTest):

    def test_decisions(self):
        storage = self.round_trip("> [!decision]\n> - Utiliser FHIR R4\n> - Rôles par clinique")
        self.assertIn('<ac:adf-node type="decision-item">', storage)
        self.assertIn('key="state">DECIDED', storage)

    def test_tasks_with_mention_and_date(self):
        storage = self.round_trip("- [ ] Envoyer la spec @marie 📅 2026-11-03\n- [x] Réserver la revue")
        self.assertIn("<ac:task-status>incomplete</ac:task-status>", storage)
        self.assertIn('<ri:user ri:account-id="acc-marie"/>', storage)
        self.assertIn('<time datetime="2026-11-03" />', storage)

    def test_real_confluence_task_body_span(self):
        storage = ('<ac:task-list ac:task-list-id="tl1">\n<ac:task>\n<ac:task-id>1</ac:task-id>\n'
                   '<ac:task-uuid>t1</ac:task-uuid>\n<ac:task-status>complete</ac:task-status>\n'
                   '<ac:task-body><span class="placeholder-inline-tasks">Book review</span>'
                   '</ac:task-body>\n</ac:task>\n</ac:task-list>')
        self.assertEqual(self.pull(storage), "- [x] Book review\n")

    def test_expand(self):
        storage = self.round_trip("> [!expand]- Règles détaillées\n> Seuil à 140/90.")
        self.assertIn('<ac:parameter ac:name="title">Règles détaillées</ac:parameter>', storage)

    def test_code_block_keeps_its_language(self):
        storage = self.round_trip('```json\n{"seuil": "140/90"}\n```')
        self.assertIn('<ac:parameter ac:name="language">json</ac:parameter>', storage)
        self.assertIn('<![CDATA[{"seuil": "140/90"}]]>', storage)

    def test_mention_inside_code_is_not_converted(self):
        self.assertNotIn("ri:user", self.push("```\nping @marie\n```\n\nEt `@marie`"))


class InlineTests(ConverterTest):

    def test_status_colours(self):
        md = "`⚪ À faire` `🔵 En cours` `🟢 In scope` `🟡 Revue` `🔴 Out of scope` `🟣 Pilote`"
        storage = self.round_trip(md)
        self.assertIn('<ac:parameter ac:name="colour">Red</ac:parameter>', storage)

    def test_custom_status_colour_snaps_to_nearest(self):
        storage = ('<p><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">Go</ac:parameter>'
                   '<ac:parameter ac:name="colour">#D3F1A7</ac:parameter></ac:structured-macro></p>')
        self.assertEqual(self.pull(storage), "`🟢 Go`\n")

    def test_plain_code_span_stays_code(self):
        self.round_trip("Champ `patient_id` requis")

    def test_text_marks(self):
        storage = self.round_trip("~~ancien~~ ==important== <u>souligné</u>")
        self.assertIn("<del>ancien</del>", storage)

    def test_dates(self):
        self.round_trip("Mise en production 📅 2026-12-01")

    def test_wikilink_to_a_linked_note(self):
        storage = self.round_trip("Voir [[PRD - Alertes]] et [[PRD - Alertes|le PRD]]")
        self.assertIn('ri:content-title="PRD - Alertes cliniques" ri:space-key="PT"', storage)

    def test_wikilink_to_an_unlinked_note_stays_text(self):
        self.assertIn("[[Brouillon]]", self.push("Voir [[Brouillon]]"))

    def test_unmapped_page_link_round_trips_as_url(self):
        storage = ('<p><ac:link><ri:page ri:space-key="RD" ri:content-title="File de transcription" />'
                   '<ac:link-body>la file</ac:link-body></ac:link></p>')
        md = self.pull(storage)
        self.assertEqual(md, "[la file](https://exemple.atlassian.net/wiki/display/RD/File+de+transcription)\n")
        self.assertIn('ri:content-title="File de transcription" ri:space-key="RD"', self.push(md))

    def test_smart_links(self):
        storage = self.round_trip("Maquette <https://www.figma.com/design/abc/Alertes> et [PT-1794](https://exemple.atlassian.net/browse/PT-1794)")
        self.assertEqual(storage.count('data-card-appearance="inline"'), 2)

    def test_emoji(self):
        storage = ('<p>OK <ac:emoticon ac:name="blue-star" ac:emoji-shortname=":busts_in_silhouette:" '
                   'ac:emoji-id="1f465" ac:emoji-fallback="\\uD83D\\uDC65" /> '
                   '<ac:emoticon ac:name="question" ac:emoji-shortname=":question_mark:" '
                   'ac:emoji-id="atlassian-question_mark" ac:emoji-fallback=":question_mark:" /></p>')
        md = self.pull(storage)
        self.assertEqual(md, "OK 👥 :question_mark:\n")
        self.assertIn('ac:emoji-id="atlassian-question_mark"', self.push(md))


class ImageTests(ConverterTest):

    def test_image_with_width(self):
        storage = self.round_trip("![[maquette.png|409]]")
        self.assertIn('<ac:image ac:width="409"><ri:attachment ri:filename="maquette.png"/>', storage)

    def test_image_with_caption(self):
        storage = self.round_trip("![[maquette.png|409]]\n*Caption: Anciennes couleurs*")
        self.assertIn("<ac:caption><p>Anciennes couleurs</p></ac:caption>", storage)

    def test_real_confluence_image(self):
        storage = ('<ac:image ac:align="center" ac:layout="center" ac:original-height="676" '
                   'ac:original-width="711" ac:custom-width="true" ac:alt="image-20260818-143639.png" '
                   'ac:width="511"><ri:attachment ri:filename="image-20260818-143639.png" '
                   'ri:version-at-save="1" /></ac:image>')
        self.assertEqual(self.pull(storage), "![[image-20260818-143639.png|511]]\n")

    def test_image_and_status_in_a_table(self):
        self.round_trip("| Écran | Statut |\n| --- | --- |\n| ![[ecran.png\\|200]] | `🟢 Fait` |")

    def test_page_needs_an_id_for_images(self):
        self.assertTrue(transforms.needs_page_id("![[a.png]]"))
        self.assertFalse(transforms.needs_page_id("Texte"))


class KeepTests(ConverterTest):

    TOC = ('<ac:structured-macro ac:name="toc" ac:schema-version="1">'
           '<ac:parameter ac:name="style">none</ac:parameter></ac:structured-macro>')

    def test_unknown_macro_survives_a_round_trip(self):
        md = self.pull("<h2>Plan</h2>" + self.TOC + "<p>Texte</p>")
        self.assertRegex(md, r"## Plan\n\n%%confluence-keep:[0-9a-f]+ Table of contents%%\n\nTexte\n")
        storage = self.push(md)
        self.assertIn('ac:name="toc"', storage)
        self.assertIn('<ac:parameter ac:name="style">none</ac:parameter>', storage)

    def test_macro_with_unexpected_parameters_is_kept(self):
        storage = ('<ac:structured-macro ac:name="info"><ac:parameter ac:name="title">Titre</ac:parameter>'
                   '<ac:rich-text-body><p>x</p></ac:rich-text-body></ac:structured-macro>')
        self.assertIn("%%confluence-keep:", self.pull(storage))

    def test_toc_shorthand(self):
        self.assertIn('<ac:structured-macro ac:name="toc" />', self.push("%%confluence:toc%%"))


class MermaidTests(ConverterTest):

    def test_push_points_the_app_at_the_right_code_block(self):
        storage = self.push("```sql\nSELECT 1;\n```\n\n```mermaid\nflowchart TD\n  A --> B\n```")
        self.assertIn(transforms.MERMAID_APP_KEY, storage)
        self.assertIn('<ac:adf-parameter key="index" type="integer">1</ac:adf-parameter>', storage)
        self.assertEqual(self.pull(storage),
                         "```sql\nSELECT 1;\n```\n\n```mermaid\nflowchart TD\n  A --> B\n```\n")

    def test_app_can_be_switched_off(self):
        with redirect_stdout(StringIO()):
            storage = md_to_storage("```mermaid\ngraph TD; A-->B;\n```", {**CFG, "mermaid_app": False},
                                    None, PAGE_ID, self.note)
        self.assertNotIn(transforms.MERMAID_APP_KEY, storage)

    def test_diagram_drawn_by_hand_in_confluence(self):
        # The shape Antoine's test page had: untitled expand with a code block + app macro.
        storage = ('<ac:structured-macro ac:name="expand"><ac:parameter ac:name="breakoutWidth">760'
                   '</ac:parameter><ac:rich-text-body><ac:structured-macro ac:name="code">'
                   '<ac:parameter ac:name="wrap">true</ac:parameter><ac:plain-text-body>'
                   '<![CDATA[flowchart TD\n    A[Billet] --> B{Clair?}]]></ac:plain-text-body>'
                   '</ac:structured-macro></ac:rich-text-body></ac:structured-macro>'
                   + transforms._mermaid_app_macro().replace(transforms.MERMAID_INDEX, "0"))
        self.assertEqual(self.pull(storage), "```mermaid\nflowchart TD\n    A[Billet] --> B{Clair?}\n```\n")

    def test_plantuml_source_section_still_pulls(self):
        storage = ('<ac:image><ri:attachment ri:filename="diagram_1_0.png"/></ac:image>'
                   '<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">'
                   'PlantUML source (confsync)</ac:parameter><ac:rich-text-body>'
                   '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[Alice -> Bob]]>'
                   '</ac:plain-text-body></ac:structured-macro></ac:rich-text-body></ac:structured-macro>')
        self.assertEqual(self.pull(storage), "```plantuml\nAlice -> Bob\n```\n")


class RegressionTests(ConverterTest):

    def test_nested_lists_keep_their_nesting(self):
        # Obsidian indents with tabs by default, and pull writes the same.
        for md in ["- Signes vitaux\n\t- Tension\n\t\t- Systolique\n- Vaccins",
                   "1. Analyse\n\t1. PPR\n2. Pilote"]:
            with self.subTest(md):
                storage = self.round_trip(md)
                self.assertEqual(storage.count("<li>"), md.count("\n") + 1)
                self.assertRegex(storage, r"<li>\w+\s*<(ul|ol)>")

    def test_two_space_lists_still_nest_on_push(self):
        self.assertIn("<ul>\n<li>Tension", self.push("- Signes vitaux\n  - Tension"))

    def test_pull_follows_the_vault_indent_setting(self):
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_text('{"useTab": false}', encoding="utf-8")
        self.round_trip("- Signes vitaux\n    - Tension")

    def test_toc_shorthand_round_trips(self):
        # Confluence stores it back with a macro id and schema version, nothing else.
        self.assertEqual(self.pull('<ac:structured-macro ac:macro-id="x" ac:name="toc" '
                                   'ac:schema-version="1"></ac:structured-macro>'),
                         "%%confluence:toc%%\n")

    def test_legacy_jira_macro_comes_back_as_a_link(self):
        # What Confluence stores after it converts a pushed Jira smart link.
        def macro(key):
            return ('<ac:structured-macro ac:local-id="a1" ac:macro-id="b2" ac:name="jira" '
                    f'ac:schema-version="1"><ac:parameter ac:name="key">{key}</ac:parameter>'
                    '<ac:parameter ac:name="serverId">383d35c0</ac:parameter>'
                    '<ac:parameter ac:name="server">System Jira</ac:parameter></ac:structured-macro>')
        self.assertEqual(self.pull(f"<ul><li>Bug {macro('PT-31022')}, {macro('PT-31023')}</li></ul>"),
                         "- Bug [PT-31022](https://exemple.atlassian.net/browse/PT-31022), "
                         "[PT-31023](https://exemple.atlassian.net/browse/PT-31023)\n")
        self.assertEqual(self.pull(f"<p>{macro('MYLE-9')}</p>"),
                         "[MYLE-9](https://exemple.atlassian.net/browse/MYLE-9)\n")
        self.assertIn('href="https://exemple.atlassian.net/browse/PT-31022"', self.push("Bug PT-31022"))

    def test_typed_key_comes_back_as_a_link(self):
        storage = self.push("Voir PT-1794")
        self.assertEqual(self.pull(storage), "Voir [PT-1794](https://exemple.atlassian.net/browse/PT-1794)\n")

    def test_jira_query_macro_is_kept(self):
        storage = ('<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
                   'project = PT</ac:parameter></ac:structured-macro>')
        self.assertIn("%%confluence-keep:", self.pull(storage))

    def test_jira_key_inside_a_url_is_left_alone(self):
        md = "<https://exemple.atlassian.net/jira/board?selectedIssue=PT-1780>"
        self.assertNotIn("/browse/", self.push(md))

    def test_jira_link_with_its_own_text_stays_a_link(self):
        self.round_trip("[le ticket](https://exemple.atlassian.net/browse/PT-30857)")


class DocumentTests(ConverterTest):

    def test_a_whole_note(self):
        self.round_trip(
            "# PRD - Alertes cliniques\n\n"
            "> [!info]\n> Owner: @marie\n\n"
            "## Décisions\n\n> [!decision]\n> - Seuil de tension à 140/90\n\n"
            "## Suivi\n\n- [ ] Valider avec la Dre Gagnon 📅 2026-11-03\n- [x] Maquette ![[alerte.png|300]]\n\n"
            "| Volet | Statut |\n| --- | --- |\n| Signes vitaux | `🟢 In scope` |\n| Vaccins | `🔴 Out of scope` |\n\n"
            "Voir [[PRD - Alertes]] et [PT-1794](https://exemple.atlassian.net/browse/PT-1794).")


if __name__ == "__main__":
    unittest.main()
