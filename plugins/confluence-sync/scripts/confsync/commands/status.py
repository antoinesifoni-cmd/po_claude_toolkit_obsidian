"""status and rebaseline - the read-only commands.

Neither writes to Confluence. status reads page versions to compare them; rebaseline
touches mapping.json only and never contacts the site at all.
"""

from pathlib import Path

from ..config import MAPPING_FILE, VAULT, api, get_config, load_json, rel, save_json
from ..hashing import HASH_ALGO, is_legacy, local_body_hash
from ..rest import get_page_meta


def cmd_status(args):
    cfg = get_config()
    s = api(cfg)
    mapping = load_json(MAPPING_FILE, {})
    # Normalize like pull/push do - mapping keys are OS-native relative paths, so a
    # forward-slash argument on Windows would otherwise never match and report "not linked".
    targets = [rel(Path(args.file))] if args.file else sorted(mapping.keys())
    if not targets:
        print("No files linked yet. Use: conf.py link <file> <pageId>")
        return
    legacy_seen = False
    for f in targets:
        entry = mapping.get(f)
        if not entry:
            print(f"{f}: not linked")
            continue
        local = VAULT / f
        local_changed = not local.exists() or local_body_hash(local) != entry["hash"]
        meta = get_page_meta(cfg, s, entry["page_id"])
        remote_v = meta["version"]["number"]
        remote_changed = remote_v != entry["version"]
        state = {
            (False, False): "in sync",
            (True, False): "local changes (push needed)",
            (False, True): f"remote moved to v{remote_v} (pull needed)",
            (True, True): f"CONFLICT: local changes AND remote moved to v{remote_v}",
        }[(local_changed, remote_changed)]
        if is_legacy(entry):
            state += "  [legacy whole-file hash, run 'conf.py rebaseline']"
            legacy_seen = True
        print(f"{f}: v{entry['version']} local | v{remote_v} remote -> {state}")

    if legacy_seen:
        print("\nSome entries still use the pre-0.4.0 whole-file hash, which counted"
              "\nfrontmatter reformatting as a local change. Review any 'push needed'"
              "\nabove, then run 'conf.py rebaseline' to switch them to body-only.")


def cmd_rebaseline(args):
    """Migrate mapping entries from the <=0.3.0 whole-file hash to the body-only hash.

    Deliberately a separate, explicit command rather than a silent migration on first
    run: a file could hold a genuine un-pushed local edit made before the upgrade, and
    silently re-baselining would bury it. --check reports without writing.
    """
    mapping = load_json(MAPPING_FILE, {})
    if not mapping:
        print("No files linked yet.")
        return

    stale, migrated, missing = [], [], []
    for f, entry in sorted(mapping.items()):
        if not is_legacy(entry):
            continue
        local = VAULT / f
        if not local.exists():
            missing.append(f)
            continue
        new_hash = local_body_hash(local)
        if args.check:
            state = "unchanged" if new_hash == entry["hash"] else "hash will change"
            stale.append(f"  {f}  ({state})")
            continue
        entry["hash"] = new_hash
        entry["hash_algo"] = HASH_ALGO
        migrated.append(f)

    if args.check:
        print("\n".join(stale) if stale else "Nothing to migrate.")
        for f in missing:
            print(f"  {f}  (local file missing, skipped)")
        print(f"\n{len(stale)} entr{'y' if len(stale) == 1 else 'ies'} would be migrated."
              "\nRe-run without --check to apply.")
        return

    for f in missing:
        print(f"{f}: local file missing, skipped")
    if not migrated:
        print("Nothing to migrate. All entries already use the body-only hash.")
        return
    save_json(MAPPING_FILE, mapping)
    for f in migrated:
        print(f"rebaselined: {f}")
    print(f"\n{len(migrated)} entr{'y' if len(migrated) == 1 else 'ies'} migrated to "
          f"body-only hashing. Confluence was not contacted and no note was modified.")
