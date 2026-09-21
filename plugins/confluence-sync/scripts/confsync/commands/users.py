"""users - look up Confluence accounts to populate users.json for @mentions."""

from ..config import USERS_FILE, api, get_config, load_json, save_json


def cmd_users(args):
    cfg = get_config()
    s = api(cfg)
    r = s.get(f"{cfg['base_url']}/wiki/rest/api/search/user",
              params={"cql": f'user.fullname ~ "{args.query}"', "limit": 10})
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        print("No users found.")
        return
    users = load_json(USERS_FILE, {})
    for res in results:
        u = res.get("user", {})
        name, acc = u.get("publicName") or u.get("displayName"), u.get("accountId")
        print(f"  {name}  ->  {acc}")
        if args.add:
            alias = name.split()[0].lower()
            users[alias] = {"account_id": acc, "display_name": name}
            print(f"    added as alias @{alias}")
    if args.add:
        save_json(USERS_FILE, users)
