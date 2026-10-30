"""Markdown <-> Confluence storage format.

Both directions live here so the pairs stay in step - a change to how a construct is
written into storage XML has to be matched by the code that reads it back, and the two
are easiest to keep honest side by side. references/transforms.md lists every pair.

Push (md_to_storage): constructs the markdown library knows nothing about (callouts,
task lists, fences, images, wikilinks, status code spans...) are cut out of the Markdown
and replaced by tokens, the rest goes through the markdown library, then each token is
swapped for its storage XML. Callout bodies and task text go through the same pipeline
recursively, so everything nests.

Pull (storage_to_md) mirrors it: each Confluence construct is replaced in the parsed tree
by a token holding its Markdown, markdownify turns the plain HTML around them into
Markdown, then the tokens are swapped back. Anything pull does not understand is saved
byte for byte under .confsync/keep/ behind a marker, so the next push puts it back
instead of deleting it.
"""

import hashlib
import html as html_lib
import itertools
import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote_plus, unquote_plus

import markdown as md_lib
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import MarkdownConverter

from .config import (EMOJI_FILE, KEEP_DIR, MAPPING_FILE, PLANTUML_JAR, USERS_FILE,
                     VAULT, load_json, save_json)
from .frontmatter import read_local_frontmatter
from .rest import upload_attachment


DIAGRAM_FENCE_RE = re.compile(r"```(plantuml|mermaid)\n(.*?)```", re.DOTALL)


IMAGE_EXTS = r"png|jpe?g|gif|svg|webp|bmp"


# ![[mockup.png|409]] - Obsidian embed with an optional width. Inside a table the pipe
# is escaped (\|), the same way Obsidian writes it.
IMAGE_EMBED_RE = re.compile(rf"!\[\[([^\]|]+?\.(?:{IMAGE_EXTS}))(?:\\?\|(\d+)(?:x\d+)?)?\]\]",
                            re.IGNORECASE)


JIRA_FENCE_RE = re.compile(r"```jira-issue\n(.*?)```", re.DOTALL)


MENTION_RE = re.compile(r"(?<![\w.])@\[([^\]]+)\]|(?<![\w.])@([A-Za-z0-9_.-]*[A-Za-z0-9_-])")


# Collapsible "expand" section title per diagram language - source always goes here,
# regardless of whether an image could also be rendered (PlantUML titles matches the
# earlier confsync convention so pages already pushed still round-trip on pull).
DIAGRAM_TITLES = {
    "plantuml": "PlantUML source (confsync)",
    "mermaid": "Mermaid source (confsync)",
}


DIAGRAM_LANG_BY_TITLE = {title: lang for lang, title in DIAGRAM_TITLES.items()}


# The "Mermaid diagram" Forge app installed on Medfar's Confluence. Its macro draws the
# Nth code block of the page (N counts every code block, in page order). Tested
# 2026-10-28: only these parameters are needed.
MERMAID_APP_KEY = ("23392b90-4271-4239-98ca-a3e96c663cbb/63d4d207-ac2f-4273-865c-0240d37f044a"
                   "/static/mermaid-diagram")


MERMAID_INDEX = "CONFSYNCMERMAIDINDEX"


# Obsidian callout type -> Confluence panel. Panels have no title, so a callout title
# becomes a bold first line. Aliases come back as the first name of their group.
PANEL_MACRO = {"info": "info", "success": "tip", "warning": "note", "error": "warning"}


PANEL_ALIASES = {
    "tip": "success", "hint": "success", "important": "success", "check": "success",
    "done": "success", "caution": "warning", "attention": "warning", "danger": "error",
    "failure": "error", "fail": "error", "missing": "error", "bug": "error",
}


CALLOUT_BY_MACRO = {macro: kind for kind, macro in PANEL_MACRO.items()}


# Status lozenge colour <-> the coloured dot that starts an inline code span.
STATUS_DOTS = {"⚪": None, "🔵": "Blue", "🟢": "Green", "🟡": "Yellow", "🔴": "Red", "🟣": "Purple"}


# Reference colours per dot, for custom hex statuses: current palette, then older ones
# seen at Medfar (lime #D3F1A7 is a green, #FFF0B3 a yellow).
STATUS_RGB = {"⚪": [(223, 225, 230)], "🔵": [(204, 224, 255), (222, 235, 255)],
              "🟢": [(186, 243, 219), (211, 241, 167), (227, 252, 239)],
              "🟡": [(248, 230, 160), (255, 240, 179)], "🔴": [(255, 213, 210), (255, 235, 230)],
              "🟣": [(223, 216, 253), (234, 230, 255)]}


STATUS_RE = re.compile(r"^(" + "|".join(STATUS_DOTS) + r") (.+)$")


# Confluence's own highlight colour (accepted as is by the editor).
HIGHLIGHT_STYLE = "background-color: rgb(254,222,200);"


# Links that Confluence draws as live smart links when given data-card-appearance.
SMART_LINK_RE = re.compile(
    r"https?://[^\"]*(?:atlassian\.net|figma\.com|docs\.google\.com|drive\.google\.com"
    r"|sheets\.google\.com|lucid\.app)[^\"]*")


DATE_RE = re.compile(r"📅 ?(\d{4}-\d{2}-\d{2})")


KEEP_RE = re.compile(r"%%confluence-keep:([0-9a-f]{8,})(?: [^%]*)?%%")


SHORTHAND_MACROS = {"toc": '<ac:structured-macro ac:name="toc" />',
                    "children": '<ac:structured-macro ac:name="children" />'}


SHORTHAND_RE = re.compile(r"%%confluence:(" + "|".join(SHORTHAND_MACROS) + r")%%")


# Macro parameters that only change looks Confluence picks by itself. Any other
# parameter on a macro means pull would lose something, so the macro is kept whole.
HARMLESS_PARAMS = {"containerLevel", "wrap", "breakoutWidth", "breakoutMode", "mixedCase"}


_ids = itertools.count()


def _esc(text: str) -> str:
    return html_lib.escape(text, quote=True)


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


# --------------------------------------------------------------------------- push --


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
            r"(?<![\w/\[`=-])((?:" + "|".join(map(re.escape, keys)) + r")-\d+)(?![\w\]`])"
        )
        # Never inside a URL, a link target or code: "?selectedIssue=PT-1780" stays as is.
        parts = re.split(r"(<https?://[^>]+>|\]\([^)]*\)|https?://[^\s)>\]]+|`[^`\n]*`)", md_text)
        md_text = "".join(p if i % 2 else bare.sub(
            lambda m: f"[{m.group(1)}]({base}/browse/{m.group(1)})", p) for i, p in enumerate(parts))
    return md_text


LIST_ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d+[.)])[ \t]")


def _normalize_list_indent(md_text: str, unit: str = "    ") -> str:
    """Nested list items -> one unit per level. Push uses 4 spaces, which the markdown
    library needs (markdownify and some editors indent by 2, which would flatten the
    list); pull uses the vault's own Obsidian indent so pulled notes look hand-written."""
    out, stack = [], []
    for line in md_text.split("\n"):
        m = LIST_ITEM_RE.match(line)
        if not m:
            if line.strip() and not line.startswith((" ", "\t")):
                stack = []
            out.append(line)
            continue
        width = len(m.group(1).expandtabs(4))
        while stack and stack[-1] > width:
            stack.pop()
        if not stack or stack[-1] < width:
            stack.append(width)
        out.append(unit * (len(stack) - 1) + line.lstrip(" \t"))
    return "\n".join(out)


def _vault_indent() -> str:
    """Obsidian's indent (Settings > Editor): a tab unless "Indent using tabs" is off."""
    try:
        app = json.loads((VAULT / ".obsidian" / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        app = {}
    return "\t" if app.get("useTab", True) else " " * app.get("tabSize", 4)


class _Push:
    """State shared by one push: tokens, counters, and what it needs to upload images."""

    def __init__(self, cfg, s, page_id, note):
        self.cfg, self.s, self.page_id, self.note = cfg, s, page_id, note
        self.tokens = {}            # token -> (inline xml, block xml or None)
        self.task_ids = itertools.count(1)
        self.diagram_ids = itertools.count()
        self.unknown_mentions = set()

    def token(self, inline, block=None):
        t = f"CONFSYNCT{next(_ids)}X"
        self.tokens[t] = (inline, block)
        return t

    def block(self, xml):
        return "\n\n" + self.token(xml, xml) + "\n\n"


def md_to_storage(md_text: str, cfg, s, page_id, note: Path = None) -> str:
    ctx = _Push(cfg, s, page_id, note or VAULT / "note.md")
    md_text = transform_jira(md_text, cfg)
    html = _convert(md_text, ctx)
    if ctx.unknown_mentions:
        print(f"  ! Unknown mention alias(es), left as text: {sorted(ctx.unknown_mentions)}"
              f"\n    Add them to {USERS_FILE} (use: conf.py users <name>)")
    return _number_mermaid_macros(html)


def needs_page_id(md_text: str) -> bool:
    """True if pushing this Markdown uploads attachments (so the page must exist first)."""
    return bool(DIAGRAM_FENCE_RE.search(md_text) or IMAGE_EMBED_RE.search(md_text))


def _convert(md_text: str, ctx: _Push) -> str:
    """Markdown -> storage XML, recursively for callout bodies."""
    md_text = _cut_fences(md_text, ctx)
    md_text = _cut_blocks(md_text, ctx)
    md_text = _cut_inline(md_text, ctx)
    md_text = _normalize_list_indent(md_text)
    md_text = re.sub(r"==(?=\S)(.+?)(?<=\S)==", rf'<span style="{HIGHLIGHT_STYLE}">\1</span>', md_text)
    md_text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", md_text)
    html = md_lib.markdown(md_text, extensions=["tables", "sane_lists"])
    html = _post_pass(html, ctx)
    return _restore_tokens(html, ctx)


def _inline(md_text: str, ctx: _Push) -> str:
    html = _convert(md_text, ctx).strip()
    m = re.fullmatch(r"<p>(.*)</p>", html, re.DOTALL)
    return m.group(1) if m else html


def _restore_tokens(html: str, ctx: _Push) -> str:
    def repl(m):
        inline, block = ctx.tokens[m.group(2) or m.group(3)]
        if m.group(2):  # alone in its paragraph
            return block if block is not None else f"<p>{inline}</p>"
        return inline
    pattern = re.compile(r"(<p>\s*(CONFSYNCT\d+X)\s*</p>)|(CONFSYNCT\d+X)")
    while True:
        new = pattern.sub(repl, html)
        if new == html:
            return new
        html = new


# Fences: ```lang ... ``` at the start of a line (inside a callout the "> " is stripped
# first, so nested fences are found by the recursive call).
FENCE_RE = re.compile(r"^```([^\n`]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _cut_fences(md_text: str, ctx: _Push) -> str:
    def repl(m):
        lang, src = m.group(1).strip(), m.group(2)
        if lang in DIAGRAM_TITLES:
            return ctx.block(_diagram_storage(lang, src.strip(), ctx))
        return ctx.block(_code_macro(src[:-1] if src.endswith("\n") else src, lang))
    return FENCE_RE.sub(repl, md_text)


def _code_macro(src: str, lang: str = "") -> str:
    param = f'<ac:parameter ac:name="language">{_esc(lang)}</ac:parameter>' if lang else ""
    return (f'<ac:structured-macro ac:name="code">{param}'
            f"<ac:plain-text-body>{_cdata(src)}</ac:plain-text-body></ac:structured-macro>")


def _expand_macro(title: str, body: str) -> str:
    return (f'<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">{_esc(title)}</ac:parameter>'
            f"<ac:rich-text-body>{body}</ac:rich-text-body></ac:structured-macro>")


def _adf_node(node_type: str, attrs: dict, body: str) -> str:
    """One ac:adf-node with its attributes; body is its content (already storage XML)."""
    return (f'<ac:adf-node type="{node_type}">'
            + "".join(f'<ac:adf-attribute key="{k}">{_esc(v)}</ac:adf-attribute>'
                      for k, v in attrs.items())
            + body + "</ac:adf-node>")


def _mermaid_app_macro() -> str:
    lid = str(uuid.uuid4())
    node = _adf_node("extension", {
        "extension-key": MERMAID_APP_KEY, "extension-type": "com.atlassian.ecosystem",
    }, "")
    params = (f'<ac:adf-attribute key="parameters">'
              f'<ac:adf-parameter key="local-id">{lid}</ac:adf-parameter>'
              f'<ac:adf-parameter key="extension-id">ari:cloud:ecosystem::extension/{MERMAID_APP_KEY}</ac:adf-parameter>'
              f'<ac:adf-parameter key="extension-title">Mermaid diagram</ac:adf-parameter>'
              f'<ac:adf-parameter key="layout">extension</ac:adf-parameter>'
              f'<ac:adf-parameter key="forge-environment">PRODUCTION</ac:adf-parameter>'
              f'<ac:adf-parameter key="guest-params"><ac:adf-parameter key="index" type="integer">'
              f"{MERMAID_INDEX}</ac:adf-parameter></ac:adf-parameter></ac:adf-attribute>"
              f'<ac:adf-attribute key="text">Mermaid diagram</ac:adf-attribute>'
              f'<ac:adf-attribute key="layout">default</ac:adf-attribute>'
              f'<ac:adf-attribute key="local-id">{lid}</ac:adf-attribute>')
    node = node.replace("</ac:adf-node>", params + "</ac:adf-node>")
    return f"<ac:adf-extension>{node}<ac:adf-fallback>{node}</ac:adf-fallback></ac:adf-extension>"


def _number_mermaid_macros(html: str) -> str:
    """Point each Mermaid app macro at the code block right after it (counted over the page)."""
    parts = html.split(MERMAID_INDEX)
    out = parts[0]
    for part in parts[1:]:
        # Every placeholder appears twice (node + fallback), both before their code block.
        out += str(len(re.findall(r'<ac:structured-macro ac:name="code"', out))) + part
    return out


def _diagram_storage(lang: str, src: str, ctx: _Push) -> str:
    """Source always goes in a collapsible section. PlantUML also renders a PNG when java
    + plantuml.jar are available; Mermaid is drawn on Confluence by the Mermaid app."""
    i = next(ctx.diagram_ids)
    expand = _expand_macro(DIAGRAM_TITLES[lang], _code_macro(src))
    if lang == "mermaid":
        if ctx.cfg.get("mermaid_app", True):
            return _mermaid_app_macro() + expand
        return expand
    if not PLANTUML_JAR.exists() or not ctx.page_id:
        return expand
    with tempfile.TemporaryDirectory() as tmp:
        puml = Path(tmp) / f"diagram_{ctx.page_id}_{i}.puml"
        puml.write_text(src if "@startuml" in src else f"@startuml\n{src}\n@enduml\n",
                        encoding="utf-8")
        subprocess.run(["java", "-jar", str(PLANTUML_JAR), "-tpng", str(puml)],
                       check=True, capture_output=True)
        name, _ = upload_attachment(ctx.cfg, ctx.s, ctx.page_id, puml.with_suffix(".png"))
    return f'<ac:image><ri:attachment ri:filename="{_esc(name)}"/></ac:image>' + expand


CALLOUT_RE = re.compile(r"^>[ \t]?\[!([\w-]+)(?:\|([^\]]*))?\]([-+]?)[ \t]*(.*)$")


TASK_RE = re.compile(r"^[-*] \[([ xX])\] (.*)$")


IMAGE_LINE_RE = re.compile(rf"^({IMAGE_EMBED_RE.pattern})[ \t]*$", re.IGNORECASE)


CAPTION_RE = re.compile(r"^\*Caption: (.+)\*[ \t]*$")


def _cut_blocks(md_text: str, ctx: _Push) -> str:
    """Callouts, task lists, captioned images and keep markers on their own line."""
    lines = md_text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = CALLOUT_RE.match(line)
        if m and _callout_kind(m.group(1)):
            body = []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                body.append(re.sub(r"^> ?", "", lines[i]))
                i += 1
            out.append(ctx.block(_callout_storage(m, "\n".join(body), ctx)))
            continue
        if TASK_RE.match(line):
            tasks = []
            while i < len(lines) and TASK_RE.match(lines[i]):
                tasks.append(TASK_RE.match(lines[i]).groups())
                i += 1
            out.append(ctx.block(_task_list(tasks, ctx)))
            continue
        m = IMAGE_LINE_RE.match(line)
        if m and i + 1 < len(lines) and CAPTION_RE.match(lines[i + 1]):
            caption = _inline(CAPTION_RE.match(lines[i + 1]).group(1), ctx)
            xml = _image_storage(m.group(2), m.group(3), ctx, caption=caption)
            out.append(ctx.block(xml) if xml else line)
            i += 2
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _callout_kind(raw: str):
    kind = raw.lower()
    kind = PANEL_ALIASES.get(kind, kind)
    return kind if kind in (*PANEL_MACRO, "note", "panel", "decision", "expand") else None


def _callout_storage(m, body_md: str, ctx: _Push) -> str:
    kind, meta, title = _callout_kind(m.group(1)), m.group(2) or "", m.group(4).strip()
    if kind == "expand":
        return _expand_macro(title, _convert(body_md, ctx))
    if kind == "decision":
        items = [re.sub(r"^[-*]\s?", "", l).strip() for l in body_md.split("\n") if l.strip()]
        nodes = "".join(_adf_node("decision-item", {"local-id": str(uuid.uuid4()), "state": "DECIDED"},
                                  f"<ac:adf-content>{_inline(item, ctx) if item else ''}</ac:adf-content>")
                        for item in items)
        fallback = "".join(f"<li>{_inline(item, ctx)}</li>" for item in items)
        return (f"<ac:adf-extension>"
                + _adf_node("decision-list", {"local-id": str(uuid.uuid4())}, nodes)
                + f'<ac:adf-fallback><ul class="decision-list">{fallback}</ul></ac:adf-fallback>'
                f"</ac:adf-extension>")

    body = _convert(body_md, ctx)
    if title:
        body = f"<p><strong>{_inline(title, ctx)}</strong></p>" + body
    if kind == "note":  # the purple panel only exists as an ADF node
        return (f"<ac:adf-extension>"
                + _adf_node("panel", {"panel-type": "note"}, f"<ac:adf-content>{body}</ac:adf-content>")
                + f'<ac:adf-fallback><div class="panel">{body}</div></ac:adf-fallback>'
                f"</ac:adf-extension>")
    if kind == "panel":
        bg, icon, icon_id, icon_text = (meta.split("|") + ["", "", "", ""])[:4]
        params = "".join(f'<ac:parameter ac:name="{k}">{_esc(v)}</ac:parameter>' for k, v in
                         [("panelIcon", icon), ("panelIconId", icon_id),
                          ("panelIconText", icon_text), ("bgColor", bg)] if v)
        return (f'<ac:structured-macro ac:name="panel">{params}'
                f"<ac:rich-text-body>{body}</ac:rich-text-body></ac:structured-macro>")
    return (f'<ac:structured-macro ac:name="{PANEL_MACRO[kind]}">'
            f"<ac:rich-text-body>{body}</ac:rich-text-body></ac:structured-macro>")


def _task_list(tasks, ctx: _Push) -> str:
    items = "".join(
        f"<ac:task><ac:task-id>{next(ctx.task_ids)}</ac:task-id>"
        f"<ac:task-status>{'incomplete' if mark == ' ' else 'complete'}</ac:task-status>"
        f"<ac:task-body>{_inline(text, ctx)}</ac:task-body></ac:task>"
        for mark, text in tasks)
    return f"<ac:task-list>{items}</ac:task-list>"


def _image_storage(name: str, width, ctx: _Push, caption=None, inline=False):
    if re.match(r"https?://", name):
        target = f'<ri:url ri:value="{_esc(name)}"/>'
    else:
        if not ctx.page_id:
            return None
        from .attachments import push_image
        remote = push_image(ctx.cfg, ctx.s, ctx.page_id, name, ctx.note)
        if remote is None:
            return None
        target = f'<ri:attachment ri:filename="{_esc(remote)}"/>'
    attrs = (f' ac:width="{width}"' if width else "") + (' ac:inline="true"' if inline else "")
    cap = f"<ac:caption><p>{caption}</p></ac:caption>" if caption else ""
    return f"<ac:image{attrs}>{target}{cap}</ac:image>"


WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\\?\|([^\]]+))?\]\]")


CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1", re.DOTALL)


URL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")


def _cut_inline(md_text: str, ctx: _Push) -> str:
    def code(m):
        status = STATUS_RE.match(m.group(2).strip())
        if status:
            return ctx.token(_status_macro(status.group(1), status.group(2)))
        return ctx.token(f"<code>{_esc(m.group(2).strip() if m.group(1) != '`' else m.group(2))}</code>")

    def keep(m):
        path = KEEP_DIR / f"{m.group(1)}.xml"
        if not path.exists():
            print(f"  ! Kept Confluence content {m.group(1)} is missing from {KEEP_DIR}, marker left as text")
            return m.group(0)
        xml = path.read_text(encoding="utf-8")
        return ctx.token(xml, xml)

    def image(m):
        xml_inline = _image_storage(m.group(1), m.group(2), ctx, inline=True)
        if xml_inline is None:
            return m.group(0)
        return ctx.token(xml_inline, xml_inline.replace(' ac:inline="true"', ""))

    def url_image(m):
        xml = _image_storage(m.group(1), None, ctx)
        return ctx.token(xml, xml)

    def wikilink(m):
        xml = _page_link(m.group(1).strip(), m.group(2), m.group(3))
        return ctx.token(xml) if xml else m.group(0)

    md_text = CODE_SPAN_RE.sub(code, md_text)
    md_text = KEEP_RE.sub(keep, md_text)
    md_text = SHORTHAND_RE.sub(lambda m: ctx.token(SHORTHAND_MACROS[m.group(1)],
                                                   SHORTHAND_MACROS[m.group(1)]), md_text)
    md_text = IMAGE_EMBED_RE.sub(image, md_text)
    md_text = URL_IMAGE_RE.sub(url_image, md_text)
    return WIKILINK_RE.sub(wikilink, md_text)


def _status_macro(dot: str, title: str) -> str:
    colour = STATUS_DOTS[dot]
    param = f'<ac:parameter ac:name="colour">{colour}</ac:parameter>' if colour else ""
    return (f'<ac:structured-macro ac:name="status">'
            f'<ac:parameter ac:name="title">{_esc(title)}</ac:parameter>{param}</ac:structured-macro>')


def _note_by_stem(stem: str):
    """(vault key, mapping entry) of the linked note an Obsidian [[stem]] points to."""
    mapping = load_json(MAPPING_FILE, {})
    for key, entry in mapping.items():
        if key == stem or key == stem + ".md" or Path(key).stem == stem:
            return key, entry
    return None, None


def _page_link(stem: str, anchor, alias) -> str:
    key, entry = _note_by_stem(stem)
    if not entry or not entry.get("title"):
        return None
    space = read_local_frontmatter(VAULT / key).get("confluence_space")
    space_attr = f' ri:space-key="{_esc(space)}"' if space else ""
    anchor_attr = f' ac:anchor="{_esc(anchor)}"' if anchor else ""
    body = f"<ac:link-body>{_esc(alias)}</ac:link-body>" if alias else ""
    return (f'<ac:link{anchor_attr}><ri:page ri:content-title="{_esc(entry["title"])}"{space_attr}/>'
            f"{body}</ac:link>")


def _post_pass(html: str, ctx: _Push) -> str:
    """Text-level transforms on plain HTML (tokens are not restored yet, so no storage
    XML or code is touched): mentions, dates, emoji shortcodes, smart links, page URLs."""
    users = load_json(USERS_FILE, {})
    emoji = load_json(EMOJI_FILE, {})

    def mention(m):
        alias = (m.group(1) or m.group(2)).strip()
        entry = users.get(alias) or users.get(alias.lower())
        if not entry:
            ctx.unknown_mentions.add(alias)
            return m.group(0)
        return f'<ac:link><ri:user ri:account-id="{entry["account_id"]}"/></ac:link>'

    def shortcode(m):
        e = emoji.get(m.group(1))
        if not e:
            return m.group(0)
        return (f'<ac:emoticon ac:name="blue-star" ac:emoji-shortname=":{m.group(1)}:" '
                f'ac:emoji-id="{_esc(e["id"])}" ac:emoji-fallback="{_esc(e.get("fallback", ""))}"/>')

    def text(t):
        t = MENTION_RE.sub(mention, t)
        t = DATE_RE.sub(r'<time datetime="\1" />', t)
        return re.sub(r":([a-z0-9_+-]+):", shortcode, t)

    parts = re.split(r"(<[^>]+>)", html)
    html = "".join(p if p.startswith("<") else text(p) for p in parts)

    base = ctx.cfg["base_url"]
    jira = re.escape(base) + r"/browse/[A-Z][A-Z0-9]+-\d+"

    def link(m):
        href, label = m.group(1), m.group(2)
        page = re.match(re.escape(base) + r"/wiki/display/([^/]+)/(.+)$", html_lib.unescape(href))
        if page:
            title = unquote_plus(page.group(2))
            space = "" if page.group(1) == "~" else f' ri:space-key="{_esc(unquote_plus(page.group(1)))}"'
            body = "" if html_lib.unescape(label) == title else f"<ac:link-body>{label}</ac:link-body>"
            return f'<ac:link><ri:page ri:content-title="{_esc(title)}"{space}/>{body}</ac:link>'
        is_jira_key = re.fullmatch(jira, href) and href.endswith("/" + label)
        if (label == href or is_jira_key) and SMART_LINK_RE.fullmatch(href):
            return f'<a href="{href}" data-card-appearance="inline">{label}</a>'
        return m.group(0)

    return re.sub(r'<a href="([^"]+)">(.*?)</a>', link, html)


# --------------------------------------------------------------------------- pull --


class _Converter(MarkdownConverter):
    """markdownify with the few inline marks Confluence has and Markdown lacks."""

    def convert_u(self, el, text, parent_tags):
        return f"<u>{text}</u>" if text.strip() else text

    def convert_span(self, el, text, parent_tags):
        if "background-color" in (el.get("style") or "") and text.strip():
            return f"=={text}=="
        return text


class _Pull:
    def __init__(self, cfg=None, s=None, page_id=None, note=None, space=None):
        self.cfg, self.s, self.page_id, self.note, self.space = cfg, s, page_id, note, space
        self.tokens = {}

    def token(self, md):
        t = f"CONFSYNCT{next(_ids)}X"
        self.tokens[t] = md
        return t


def storage_to_md(html: str, cfg=None, s=None, page_id=None, note: Path = None, space=None) -> str:
    """Storage XML -> Markdown. With cfg/s/page_id/note given, images are downloaded into
    the vault; without them (tests, previews) embeds are written but nothing is fetched."""
    text = _to_md(html, _Pull(cfg, s, page_id, note, space))
    parts = FENCE_RE.split(text)  # leave code alone: (text, lang, src, text, ...)
    for i in range(0, len(parts), 3):
        parts[i] = _normalize_list_indent(parts[i], _vault_indent())
    return "".join(p if i % 3 == 0 else (f"```{p}\n" if i % 3 == 1 else f"{p}```")
                   for i, p in enumerate(parts))


def _to_md(html: str, ctx: _Pull) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _mark_mermaid_sources(soup)
    _drop_rendered_images(soup)
    _walk(soup, ctx)
    text = _Converter(heading_style="ATX", bullets="-").convert_soup(soup)
    text = _restore_md(text, ctx)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _inline_md(html: str, ctx: _Pull, in_table=False) -> str:
    text = " ".join(_to_md(html, ctx).split("\n")).strip() if html.strip() else ""
    return text.replace("|", "\\|") if in_table else text


def _restore_md(text: str, ctx: _Pull) -> str:
    """Swap tokens for their Markdown; a multi-line value keeps the line prefix of the
    token (list indent, "> " of a blockquote) on each of its lines."""
    def repl(m):
        prefix, value = m.group(1), ctx.tokens[m.group(2)]
        if "\n" not in value:
            return prefix + value
        indent = re.sub(r"[^>\s]", " ", prefix)
        lines = value.split("\n")
        return prefix + lines[0] + "".join("\n" + (indent + l if l else indent.rstrip()) for l in lines[1:])
    pattern = re.compile(r"^(.*?)(CONFSYNCT\d+X)", re.MULTILINE)
    while True:
        new = pattern.sub(repl, text)
        if new == text:
            return new
        text = new


def _params(macro: Tag) -> dict:
    return {p.get("ac:name"): p.get_text() for p in macro.find_all("ac:parameter", recursive=False)}


def _harmless(params: dict, allowed=()) -> bool:
    return set(params) <= HARMLESS_PARAMS | set(allowed)


def _adf_attr(node: Tag, key: str):
    a = node.find("ac:adf-attribute", attrs={"key": key}, recursive=False)
    return a.get_text() if a else None


def _in_table(el: Tag) -> bool:
    return el.find_parent(["td", "th"]) is not None


def _mark_mermaid_sources(soup):
    """A Mermaid app macro draws the Nth code block of the page: tag that block (or the
    expand holding only it) so it comes back as a ```mermaid fence, and drop the macro."""
    codes = soup.find_all("ac:structured-macro", attrs={"ac:name": "code"})
    for ext in soup.find_all("ac:adf-extension"):
        node = ext.find("ac:adf-node", recursive=False)
        if not node or not (_adf_attr(node, "extension-key") or "").endswith("/static/mermaid-diagram"):
            continue
        idx = node.find("ac:adf-parameter", attrs={"key": "index"})
        try:
            code = codes[int(idx.get_text())]
        except (AttributeError, ValueError, IndexError):
            continue
        code["data-confsync-mermaid"] = "1"
        ext["data-confsync-drop"] = "1"


def _keep(el: Tag, ctx: _Pull, block: bool) -> str:
    """Save el's XML under .confsync/keep/ and return a marker (a token)."""
    xml = str(el)
    digest = hashlib.sha1(xml.encode("utf-8")).hexdigest()[:10]
    KEEP_DIR.mkdir(parents=True, exist_ok=True)
    path = KEEP_DIR / f"{digest}.xml"
    if not path.exists():
        path.write_text(xml, encoding="utf-8")
    title = el.find("ac:adf-parameter", attrs={"key": "extension-title"})
    node = el.find("ac:adf-node")
    label = (el.get("ac:name") or (title.get_text() if title else None)
             or (node.get("type") if node else None) or el.name)
    label = {"toc": "Table of contents", "children": "Child pages"}.get(label, label)
    return f"%%confluence-keep:{digest} {label}%%"


def _walk(node, ctx: _Pull):
    for child in list(node.children):
        if not isinstance(child, Tag):
            continue
        result = _handle(child, ctx)
        if result is None:
            _walk(child, ctx)
            continue
        md, block = result
        token = ctx.token(md)
        if block:
            p = BeautifulSoup("", "html.parser").new_tag("p")
            p.string = token
            child.replace_with(p)
        else:
            child.replace_with(NavigableString(token))


def _handle(el: Tag, ctx: _Pull):
    """(markdown, is_block) for a construct pull knows, None to let markdownify do it."""
    name = el.name
    if name == "ac:structured-macro":
        return _macro(el, ctx)
    if name == "ac:adf-extension":
        return _adf_extension(el, ctx)
    if name == "ac:task-list":
        if _in_table(el):
            return _keep(el, ctx, True), False
        return _tasks(el, ctx), True
    if name == "ac:image":
        return _image(el, ctx)
    if name == "ac:link":
        return _link(el, ctx)
    if name == "ac:emoticon":
        return _emoji(el), False
    if name == "time" and el.get("datetime"):
        return f"📅 {el['datetime']}", False
    if name == "a" and el.get("data-card-appearance"):
        if el["data-card-appearance"] != "inline":
            return _keep(el, ctx, True), True
        return _card(el, ctx), False
    if name == "ac:inline-comment-marker":
        return None  # keep the text, the comment itself stays in Confluence
    if name.startswith(("ac:", "ri:")):
        block = el.find_parent("p") is None and not _in_table(el)
        return _keep(el, ctx, block), block
    return None


def _fence(src: str, lang: str = "") -> str:
    ticks = "````" if "```" in src else "```"
    return f"{ticks}{lang}\n{src.rstrip(chr(10))}\n{ticks}"


def _quote(md: str) -> str:
    return "\n".join("> " + l if l else ">" for l in md.rstrip("\n").split("\n"))


def _macro(el: Tag, ctx: _Pull):
    kind, params = el.get("ac:name"), _params(el)
    body = el.find("ac:rich-text-body", recursive=False)
    inner = body.decode_contents() if body else ""
    block_ok = not _in_table(el)

    if kind == "code" and block_ok and _harmless(params, ["language"]):
        src = el.find("ac:plain-text-body").get_text() if el.find("ac:plain-text-body") else ""
        lang = "mermaid" if el.get("data-confsync-mermaid") else params.get("language", "")
        return _fence(src, lang), True

    if kind == "expand" and block_ok and _harmless(params, ["title"]):
        title = params.get("title", "")
        code = body.find("ac:structured-macro", attrs={"ac:name": "code"}) if body else None
        only_code = code is not None and not body.get_text(strip=True).replace(code.get_text(strip=True), "")
        if title in DIAGRAM_LANG_BY_TITLE and code:
            return _fence(code.find("ac:plain-text-body").get_text().strip(),
                          DIAGRAM_LANG_BY_TITLE[title]), True
        if only_code and code.get("data-confsync-mermaid"):
            return _fence(code.find("ac:plain-text-body").get_text().strip(), "mermaid"), True
        head = f"> [!expand]-" + (f" {title}" if title else "")
        return head + ("\n" + _quote(_to_md(inner, ctx)) if inner.strip() else ""), True

    if kind in CALLOUT_BY_MACRO and block_ok and _harmless(params):
        return _callout_md(CALLOUT_BY_MACRO[kind], "", inner, ctx), True

    if kind == "panel" and block_ok and _harmless(params, ["panelIcon", "panelIconId",
                                                           "panelIconText", "bgColor"]):
        meta = "|".join([params.get("bgColor", ""), params.get("panelIcon", ""),
                         params.get("panelIconId", ""), params.get("panelIconText", "")]).rstrip("|")
        return _callout_md("panel", meta, inner, ctx), True

    if kind == "status" and _harmless(params, ["title", "colour"]):
        return f"`{_status_dot(params.get('colour'))} {params.get('title', '')}`", False

    if kind in SHORTHAND_MACROS and not params and block_ok:
        return f"%%confluence:{kind}%%", True

    # Confluence turns pushed Jira smart links into the legacy one-issue macro on save.
    key = params.get("key", "")
    if (kind == "jira" and ctx.cfg and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", key)
            and _harmless(params, ["key", "server", "serverId"])):
        return _jira_key(key, ctx), False

    block = el.find_parent("p") is None and block_ok
    return _keep(el, ctx, block), block


def _drop_rendered_images(soup):
    """The PNG confsync renders above a PlantUML source section is not kept locally:
    Obsidian draws the diagram from the fence."""
    for expand in soup.find_all("ac:structured-macro", attrs={"ac:name": "expand"}):
        if _params(expand).get("title") not in DIAGRAM_LANG_BY_TITLE:
            continue
        prev = expand.find_previous_sibling()
        if prev is not None and prev.name == "ac:image":
            att = prev.find("ri:attachment")
            if att is not None and att.get("ri:filename", "").startswith("diagram_"):
                prev.decompose()


def _callout_md(kind: str, meta: str, inner_html: str, ctx: _Pull) -> str:
    head = f"> [!{kind}" + (f"|{meta}" if meta else "") + "]"
    inner = _to_md(inner_html, ctx) if inner_html.strip() else ""
    return head + ("\n" + _quote(inner) if inner.strip() else "")


def _status_dot(colour) -> str:
    if not colour:
        return "⚪"
    for dot, name in STATUS_DOTS.items():
        if name and name.lower() == colour.lower():
            return dot
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", colour)
    if not m:
        return "⚪"
    rgb = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return min(STATUS_RGB, key=lambda d: min(sum((a - b) ** 2 for a, b in zip(ref, rgb))
                                             for ref in STATUS_RGB[d]))


def _adf_extension(el: Tag, ctx: _Pull):
    if el.get("data-confsync-drop"):
        return "", False
    node = el.find("ac:adf-node", recursive=False)
    kind = node.get("type") if node else None
    block_ok = not _in_table(el)

    if kind == "decision-list" and block_ok:
        items = node.find_all("ac:adf-node", attrs={"type": "decision-item"}, recursive=False)
        if all(_adf_attr(i, "state") == "DECIDED" for i in items):
            lines = []
            for item in items:
                content = item.find("ac:adf-content", recursive=False)
                text = _inline_md(content.decode_contents(), ctx) if content else ""
                lines.append(f"- {text}" if text else "-")
            return "> [!decision]\n" + _quote("\n".join(lines)), True

    if kind == "panel" and block_ok:
        content = node.find("ac:adf-content", recursive=False)
        inner = content.decode_contents() if content else ""
        ptype = _adf_attr(node, "panel-type")
        if ptype == "note":
            return _callout_md("note", "", inner, ctx), True
        if ptype in PANEL_MACRO:
            return _callout_md(ptype, "", inner, ctx), True
        if ptype == "custom":
            meta = "|".join([_adf_attr(node, k) or "" for k in
                             ("panel-color", "panel-icon", "panel-icon-id", "panel-icon-text")]).rstrip("|")
            return _callout_md("panel", meta, inner, ctx), True

    block = el.find_parent("p") is None and block_ok
    return _keep(el, ctx, block), block


def _tasks(el: Tag, ctx: _Pull) -> str:
    lines = []
    for task in el.find_all("ac:task", recursive=False):
        status = task.find("ac:task-status")
        body = task.find("ac:task-body")
        done = status is not None and status.get_text().strip() == "complete"
        text = _inline_md(body.decode_contents(), ctx) if body else ""
        lines.append(f"- [{'x' if done else ' '}] {text}".rstrip())
    return "\n".join(lines)


def _image(el: Tag, ctx: _Pull):
    in_table = _in_table(el)
    block = el.find_parent("p") is None and not in_table and el.get("ac:inline") != "true"
    url = el.find("ri:url")
    att = el.find("ri:attachment")
    if url is not None:
        return f"![]({url.get('ri:value')})", block
    if att is None or att.find("ri:page") is not None:  # another page's attachment
        return _keep(el, ctx, block), block

    filename = att.get("ri:filename", "")
    local = filename
    if ctx.s is not None and ctx.page_id and ctx.note is not None:
        from .attachments import pull_image
        local = pull_image(ctx.cfg, ctx.s, ctx.page_id, filename, att.get("ri:version-at-save"), ctx.note)
    width = el.get("ac:width")
    pipe = "\\|" if in_table else "|"
    md = f"![[{local}{pipe + width if width else ''}]]"
    caption = el.find("ac:caption")
    if caption is not None and block:
        md += f"\n*Caption: {_inline_md(caption.decode_contents(), ctx)}*"
    return md, block


def _link(el: Tag, ctx: _Pull):
    user = el.find("ri:user")
    if user is not None:
        users = load_json(USERS_FILE, {})
        by_id = {v["account_id"]: k for k, v in users.items()}
        acc = user.get("ri:account-id", "")
        return f"@{by_id.get(acc, acc)}", False

    page = el.find("ri:page")
    in_table = _in_table(el)
    if page is not None:
        title = page.get("ri:content-title", "")
        space = page.get("ri:space-key")
        anchor = el.get("ac:anchor")
        body = el.find(["ac:link-body", "ac:plain-text-link-body"])
        label = body.get_text().strip() if body is not None else ""
        mapping = load_json(MAPPING_FILE, {})
        key = next((k for k, e in mapping.items() if e.get("title") == title), None)
        if key:
            stem = Path(key).stem
            target = stem + (f"#{anchor}" if anchor else "")
            alias = label if label and label != stem else ""
            pipe = "\\|" if in_table else "|"
            return f"[[{target}{pipe + alias if alias else ''}]]", False
        if ctx.cfg and not anchor:
            url = f"{ctx.cfg['base_url']}/wiki/display/{quote_plus(space or ctx.space or '~')}/{quote_plus(title)}"
            return f"[{label or title}]({url})", False

    return _keep(el, ctx, False), False


def _card(el: Tag, ctx: _Pull) -> str:
    href = el.get("href", "")
    m = re.search(r"/browse/([A-Z][A-Z0-9]+-\d+)$", href)
    if m and ctx.cfg and href == f"{ctx.cfg['base_url']}/browse/{m.group(1)}":
        return _jira_key(m.group(1), ctx)
    return f"<{href}>"


def _jira_key(key: str, ctx: _Pull) -> str:
    """Bare key when push will link it again, else an explicit link to the issue."""
    keys = ctx.cfg.get("jira_project_keys") or []
    if key.split("-")[0] in keys:
        return key
    return f"[{key}]({ctx.cfg['base_url']}/browse/{key})"


def _emoji(el: Tag) -> str:
    short = (el.get("ac:emoji-shortname") or "").strip(":")
    eid = el.get("ac:emoji-id") or ""
    fallback = el.get("ac:emoji-fallback") or ""
    if re.fullmatch(r"[0-9a-f]{2,6}(?:-[0-9a-f]{2,6})*", eid):
        if "\\u" in fallback:
            try:
                return json.loads(f'"{fallback}"')
            except ValueError:
                pass
        if fallback and not fallback.startswith(":"):
            return fallback
        return "".join(chr(int(h, 16)) for h in eid.split("-"))
    if short:
        emoji = load_json(EMOJI_FILE, {})
        if short not in emoji:
            emoji[short] = {"id": eid, "fallback": fallback}
            save_json(EMOJI_FILE, emoji)
        return f":{short}:"
    return fallback
