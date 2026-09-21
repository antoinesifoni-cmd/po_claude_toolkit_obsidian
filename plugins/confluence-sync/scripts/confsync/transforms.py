"""Markdown <-> Confluence storage format: Jira links, diagrams and user mentions.

Both directions live here so the pairs stay in step - a change to how a diagram is
written into storage HTML has to be matched by the pattern that reads it back, and the
two are easiest to keep honest side by side.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import markdown as md_lib
from markdownify import markdownify as html_to_md

from .config import PLANTUML_JAR, USERS_FILE, load_json
from .rest import upload_attachment


JIRA_FENCE_RE = re.compile(r"```jira-issue\n(.*?)```", re.DOTALL)


DIAGRAM_FENCE_RE = re.compile(r"```(plantuml|mermaid)\n(.*?)```", re.DOTALL)


MENTION_RE = re.compile(r"@\[([^\]]+)\]|@([A-Za-z0-9_.-]+)")


# Collapsible "expand" section title per diagram language - source always goes here,
# regardless of whether an image could also be rendered (PlantUML titles matches the
# earlier confsync convention so pages already pushed still round-trip on pull).
DIAGRAM_TITLES = {
    "plantuml": "PlantUML source (confsync)",
    "mermaid": "Mermaid source (confsync)",
}


DIAGRAM_LANG_BY_TITLE = {title: lang for lang, title in DIAGRAM_TITLES.items()}


def transform_jira(md_text: str, cfg) -> str:
    """jira-issue fences and bare issue keys -> plain links (Confluence renders smart links)."""
    base = cfg["base_url"]

    def fence_repl(m):
        keys = [k.strip() for k in m.group(1).strip().splitlines() if k.strip()]
        return "\n".join(f"[{k}]({base}/browse/{k})" for k in keys)

    md_text = JIRA_FENCE_RE.sub(fence_repl, md_text)

    keys = cfg.get("jira_project_keys") or []
    if keys:
        bare = re.compile(
            r"(?<![\w/\[])((?:" + "|".join(map(re.escape, keys)) + r")-\d+)(?![\w\]])"
        )
        md_text = bare.sub(lambda m: f"[{m.group(1)}]({base}/browse/{m.group(1)})", md_text)
    return md_text


def render_diagram_blocks(md_text: str, cfg, s, page_id):
    """Extract ```plantuml/```mermaid fences, replace with placeholder tokens.

    PlantUML also renders a PNG (uploaded as an attachment) when java + plantuml.jar are
    available locally; Mermaid has no local renderer, so it's always text-only. Either
    way the raw source always goes into the returned block info - it always ends up in a
    collapsible section in storage HTML (see inject_diagram_storage), image or not.

    Returns (md_text, blocks) where blocks maps token -> {lang, source, image_filename}.
    """
    found = DIAGRAM_FENCE_RE.findall(md_text)
    if not found:
        return md_text, {}

    have_plantuml_renderer = PLANTUML_JAR.exists()
    blocks = {}
    for i, (lang, raw_src) in enumerate(found):
        token = f"CONFSYNCDIAGRAM{i}"
        src = raw_src.strip()
        image_filename = None
        if lang == "plantuml" and have_plantuml_renderer:
            with tempfile.TemporaryDirectory() as tmp:
                puml = Path(tmp) / f"diagram_{page_id}_{i}.puml"
                puml.write_text(src if "@startuml" in src else f"@startuml\n{src}\n@enduml\n",
                                encoding="utf-8")
                subprocess.run(
                    ["java", "-jar", str(PLANTUML_JAR), "-tpng", str(puml)],
                    check=True, capture_output=True,
                )
                image_filename = upload_attachment(cfg, s, page_id, puml.with_suffix(".png"))
        blocks[token] = {"lang": lang, "source": src, "image_filename": image_filename}
        md_text = md_text.replace(f"```{lang}\n{raw_src}```", f"\n{token}\n", 1)
    return md_text, blocks


def inject_diagram_storage(html: str, blocks) -> str:
    for token, info in blocks.items():
        expand = (
            f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">{DIAGRAM_TITLES[info["lang"]]}</ac:parameter>'
            f'<ac:rich-text-body><ac:structured-macro ac:name="code">'
            f'<ac:plain-text-body><![CDATA[{info["source"]}]]></ac:plain-text-body>'
            f"</ac:structured-macro></ac:rich-text-body></ac:structured-macro>"
        )
        if info["image_filename"]:
            block = (
                f'<ac:image><ri:attachment ri:filename="{info["image_filename"]}"/></ac:image>'
                + expand
            )
        else:
            block = expand
        html = re.sub(rf"<p>\s*{token}\s*</p>|{token}", block, html, count=1)
    return html


def transform_mentions(html: str) -> str:
    """@alias or @[Full Name] -> Confluence mention (needs users.json)."""
    users = load_json(USERS_FILE, {})
    unknown = []

    def repl(m):
        alias = (m.group(1) or m.group(2)).strip()
        entry = users.get(alias) or users.get(alias.lower())
        if not entry:
            unknown.append(alias)
            return m.group(0)
        return (
            f'<ac:link><ri:user ri:account-id="{entry["account_id"]}"/></ac:link>'
        )

    html = MENTION_RE.sub(repl, html)
    if unknown:
        print(f"  ! Unknown mention alias(es), left as text: {sorted(set(unknown))}"
              f"\n    Add them to {USERS_FILE} (use: conf.py users <name>)")
    return html


def md_to_storage(md_text: str, cfg, s, page_id) -> str:
    md_text = transform_jira(md_text, cfg)
    md_text, diagrams = render_diagram_blocks(md_text, cfg, s, page_id)
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    html = inject_diagram_storage(html, diagrams)
    html = transform_mentions(html)
    return html


def storage_to_md(html: str) -> str:
    users = load_json(USERS_FILE, {})
    by_id = {v["account_id"]: k for k, v in users.items()}

    # mentions -> @alias (or @account_id if unknown)
    def mention_back(m):
        acc = m.group(1)
        return f"@{by_id.get(acc, acc)}"

    html = re.sub(
        r'<ac:link><ri:user ri:account-id="([^"]+)"\s*/></ac:link>', mention_back, html
    )

    # confsync diagram expand blocks -> fences (drop the rendered image, if any - keeping
    # the source is the point; a plain fence is simply "a section in the text" once it's
    # markdown, there's no "collapsed" state outside Confluence)
    def diagram_back(m):
        lang = DIAGRAM_LANG_BY_TITLE[m.group(1)]
        return f"\n```{lang}\n{m.group(2).strip()}\n```\n"

    title_alt = "|".join(re.escape(t) for t in DIAGRAM_TITLES.values())
    html = re.sub(
        r'(?:<ac:image>.*?</ac:image>\s*)?<ac:structured-macro ac:name="expand">.*?'
        rf'<ac:parameter ac:name="title">({title_alt})</ac:parameter>.*?'
        r"<!\[CDATA\[(.*?)\]\]>.*?</ac:structured-macro>",
        diagram_back, html, flags=re.DOTALL,
    )

    text = html_to_md(html, heading_style="ATX", bullets="-")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
