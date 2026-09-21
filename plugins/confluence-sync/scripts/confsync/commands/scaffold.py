"""scaffold - build a whole folder/page tree from a YAML spec, idempotently.

Effectively a second program sharing the first one's REST layer: it has its own vocabulary
(variables, team expansion, when-gating, anchor notes) that no other command touches, and
it reaches into the rest of confsync in only a handful of places.

A node already present in mapping.json/folders.json is skipped and its id reused, so an
interrupted run is resumed by re-running it.
"""

import re
import sys
from pathlib import Path

import yaml

from ..config import FOLDERS_FILE, MAPPING_FILE, VAULT, api, get_config, load_json, rel
from ..frontmatter import render_frontmatter
from ..rest import resolve_target
from .create import create_folder_here, create_page_here


# Characters Confluence happily accepts in a title but Windows rejects in a filename.
ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(title: str) -> str:
    """Local file/dir name for a Confluence title (titles allow chars Windows does not)."""
    cleaned = ILLEGAL_NAME_CHARS.sub("-", title).rstrip(". ")
    return cleaned or "untitled"


def load_spec(path: Path) -> dict:
    """A scaffold spec is YAML or JSON - yaml.safe_load reads both."""
    if not path.exists():
        sys.exit(f"Spec file not found: {path}")
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "tree" not in spec:
        sys.exit("Spec must be a mapping with a top-level 'tree' key.")
    return spec


VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def substitute(text, variables: dict):
    """Replace {placeholders} from `variables`; an unknown placeholder is left as-is.

    Left as-is rather than blanked so a typo shows up in the dry-run output as a literal
    {typo} instead of silently producing a half-empty title.
    """
    if not isinstance(text, str):
        return text
    return VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), text)


def render_title(node, variables: dict, subst_team, prefix_team):
    """Build a node's final Confluence title.

    Convention: "{key} - {title}", or "{key} - {team} - {title}" inside a team subtree.
    `raw: true` opts out entirely (still substituted, just not prefixed) - that is how a
    node like CLAUDE.md keeps its exact name.

    The two team arguments differ for exactly one node: the repeating wrapper itself,
    whose title is typically "{team}". It needs the substitution but not the prefix
    segment, or it would render as "KEY - Charting - Charting".
    """
    title = substitute(node.get("title", ""), {**variables, "team": subst_team or ""})
    if not title:
        sys.exit(f"Every node needs a 'title' (offending node: {node!r}).")
    if node.get("raw"):
        return title
    return " - ".join(p for p in (variables.get("key"), prefix_team, title) if p)


def expand_tree(nodes, variables: dict, team=None):
    """Resolve variables and expand `repeat_per_team` into a concrete tree.

    A `repeat_per_team` node is emitted once per team, and every node beneath it picks up
    the team segment in its title - Confluence enforces unique page titles per space, so
    two teams sharing a leaf title like "Scope definition" would otherwise collide on
    creation. The repeating node's own title carries the team already (it is typically
    "{team}"), so it does not get the segment twice.

    With `teams: []` the node collapses and splices its children into its parent, which
    is what makes single-team mode read exactly like the tree as written.

    `when: single_team` / `when: multi_team` drops a node (and its whole subtree) in the
    other mode. It exists because collapsing splices into the *immediate* parent, so a
    node that needs to sit at a different depth once the team wrapper disappears cannot
    be expressed by placement alone - it has to be written twice and gated. project.yaml
    uses it for the Dev folder: per-team inside "Product Owner" for a multi-team project,
    a single project-level folder otherwise.
    """
    out = []
    for node in nodes or []:
        kind = node.get("type", "page")
        if kind not in ("page", "folder"):
            sys.exit(f"Unknown node type {kind!r} (expected 'page' or 'folder').")

        # `when` gates a node on team mode (see docstring). Checked before repeat_per_team
        # so a gated-out subtree is never expanded at all.
        when = node.get("when")
        if when not in (None, "single_team", "multi_team"):
            sys.exit(f"Unknown when {when!r} on node {node.get('title')!r} "
                     f"(expected 'single_team' or 'multi_team').")
        if when and (when == "multi_team") != bool(variables.get("teams")):
            continue

        if node.get("repeat_per_team"):
            teams = variables.get("teams") or []
            if not teams:
                out.extend(expand_tree(node.get("children"), variables, team))
                continue
            for t in teams:
                out.append(render_node(node, variables, self_team=None, child_team=t))
            continue

        out.append(render_node(node, variables, self_team=team, child_team=team))
    return out


def render_node(node, variables: dict, self_team, child_team):
    kind = node.get("type", "page")
    rendered = {
        "type": kind,
        "title": render_title(node, variables,
                              subst_team=child_team if node.get("repeat_per_team") else self_team,
                              prefix_team=None if node.get("repeat_per_team") else self_team),
        "target": node.get("target", "both"),
    }
    if rendered["target"] not in ("both", "obsidian"):
        sys.exit(f"Unknown target {rendered['target']!r} on {rendered['title']!r} "
                 f"(expected 'both' or 'obsidian').")
    if node.get("name"):
        rendered["name"] = substitute(node["name"], {**variables, "team": child_team or ""})
    if node.get("body"):
        rendered["body"] = substitute(node["body"], {**variables, "team": child_team or ""})
    if node.get("anchor"):
        rendered["anchor"] = True
    if node.get("children"):
        rendered["children"] = expand_tree(node["children"], variables, child_team)
    return rendered


def local_path_for(node, base_dir: Path) -> Path:
    """Vault path mirroring a node: folders become directories, pages become <name>.md."""
    name = node.get("name") or safe_name(node["title"])
    if node["type"] == "folder":
        return base_dir / name
    return base_dir / (name if name.endswith(".md") else f"{name}.md")


def walk_spec(nodes, base_dir: Path, depth=0):
    """Yield (node, local_path, depth) depth-first, parents before their children."""
    for node in nodes or []:
        local = local_path_for(node, base_dir)
        yield node, local, depth
        if node["type"] == "folder":
            yield from walk_spec(node.get("children"), local, depth + 1)
        elif node.get("children"):
            sys.exit(f"Page {node['title']!r} has children - only folders can nest. "
                     f"Make it a folder, or move the children up.")


def seed_note(local: Path, body: str, extra_fm: dict):
    """Write a note that does not exist yet, with the spec's frontmatter keys on top.

    Those keys (typically `tags`) sit outside CONFSYNC_FM_KEYS, so every later pull/push
    preserves them as manual properties. An existing file is never touched - a note you
    have already written beats the template.
    """
    if local.exists():
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(render_frontmatter(extra_fm) + (body or ""), encoding="utf-8")
    return True


def cmd_scaffold(args):
    """Create a whole folder/page tree in Confluence and mirror it into the vault.

    Idempotent by design: a node whose local path is already in mapping.json/folders.json
    is skipped and its existing id is reused as the parent for its children, so a run
    interrupted halfway (network, permissions, a title clash) can simply be re-run.
    """
    cfg = get_config()
    s = api(cfg)
    spec = load_spec(Path(args.spec))

    variables = dict(spec.get("variables") or {})
    for override in args.set or []:
        if "=" not in override:
            sys.exit(f"--set expects key=value, got {override!r}")
        k, v = override.split("=", 1)
        variables[k] = [p.strip() for p in v.split(",") if p.strip()] if k == "teams" else v

    parent = args.parent or substitute(spec.get("parent"), variables)
    space = args.space or substitute(spec.get("space"), variables)
    space_id, root_parent_id = resolve_target(cfg, s, parent, space)

    base = substitute(spec.get("base"), variables)
    base_dir = (VAULT / base) if base else VAULT
    extra_fm = {k: substitute(v, variables) if isinstance(v, str) else
                [substitute(i, variables) for i in v] if isinstance(v, list) else v
                for k, v in (spec.get("frontmatter") or {}).items()}

    mapping = load_json(MAPPING_FILE, {})
    folders = load_json(FOLDERS_FILE, {})

    tree = expand_tree(spec["tree"], variables)
    plan = list(walk_spec(tree, base_dir))
    if not plan:
        sys.exit("Spec has an empty tree - nothing to create.")

    # The anchor is the note every other note points at with frontmatter `up`. Obsidian
    # wikilinks can only target notes, and in a folders-only tree a page's parent is
    # almost always a folder, which has no note behind it - so `up` would otherwise be
    # empty on nearly every page. Defaults to the first synced page in the tree (the
    # project's Read Me); mark another node `anchor: true` to override.
    anchor = next((n for n, _, _ in plan
                   if n["type"] == "page" and n.get("anchor") and n["target"] == "both"), None)
    if anchor is None:
        anchor = next((n for n, _, _ in plan
                       if n["type"] == "page" and n["target"] == "both"), None)
    anchor_stem = None
    if anchor is not None:
        anchor_stem = local_path_for(anchor, base_dir).stem

    teams = variables.get("teams") or []
    where = f"space {space_id}" + (f", under {root_parent_id}" if root_parent_id else ", at space root")
    print(f"Scaffolding {len(plan)} node(s) into {where}")
    if teams:
        print(f"teams: {', '.join(teams)}")
    if anchor_stem:
        print(f"up anchor: [[{anchor_stem}]]")
    print()

    # local dir -> confluence id, so each child can find the parent created moments ago
    parent_ids = {base_dir.resolve(): root_parent_id}
    created = skipped = local_only = 0

    for node, local, depth in plan:
        kind, title, target = node["type"], node["title"], node["target"]
        f = rel(local)
        indent = "  " * depth

        if target == "obsidian":
            if args.dry_run:
                print(f"{indent}+ {local.name}  [obsidian only]")
            else:
                wrote = seed_note(local, node.get("body", ""), extra_fm) if kind == "page" \
                    else (local.mkdir(parents=True, exist_ok=True) or True)
                print(f"{indent}{'+' if wrote else '-'} {local.name}  "
                      f"[obsidian only{'' if wrote else ', exists'}]")
            local_only += 1
            continue

        store = folders if kind == "folder" else mapping
        id_key = "folder_id" if kind == "folder" else "page_id"
        existing = store.get(f)
        if existing:
            print(f"{indent}- {title}  [exists, {id_key}={existing[id_key]}]")
            parent_ids[local.resolve()] = existing[id_key]
            skipped += 1
            continue

        if args.dry_run:
            print(f"{indent}+ {title}  [{kind}]")
            parent_ids[local.resolve()] = f"<{kind}:{title}>"
            created += 1
            continue

        node_parent = parent_ids.get(local.parent.resolve(), root_parent_id)
        if kind == "folder":
            entry = create_folder_here(cfg, s, space_id, title, node_parent, local, folders)
            parent_ids[local.resolve()] = entry["folder_id"]
        else:
            seed_note(local, node.get("body", ""), extra_fm)
            up = anchor_stem if anchor_stem and local_path_for(node, base_dir) != \
                local_path_for(anchor, base_dir) else None
            entry = create_page_here(cfg, s, space_id, title, node_parent, local, mapping,
                                     args.message or "Created from project template",
                                     up_note=up)
            parent_ids[local.resolve()] = entry["page_id"]
        print(f"{indent}+ {title}  [{kind} {parent_ids[local.resolve()]}]")
        created += 1

    verb = "would create" if args.dry_run else "created"
    print(f"\n{verb} {created} in Confluence, {local_only} Obsidian-only, "
          f"skipped {skipped} already-linked.")
    if not args.dry_run and created:
        print("Run 'conf.py status' to confirm, or edit the notes and 'push' them.")
