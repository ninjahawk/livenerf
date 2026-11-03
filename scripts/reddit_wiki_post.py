"""Post wiki.md to r/ClaudeAI/wiki/livenerf via Reddit's API (script app, runs as the page owner).
Env: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD. Skips if content unchanged.
  python scripts/reddit_wiki_post.py wiki.md [--dry-run]
"""
import base64, json, os, sys, urllib.parse, urllib.request

SUB, PAGE = "ClaudeAI", "livenerf"
UA = "linux:livenerf-wiki-sync:1.0 (by /u/TheOnlyVibemaster)"


def req(url, data=None, headers=None):
    h = {"User-Agent": UA, **(headers or {})}
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, body, h), timeout=30) as r:
        return json.loads(r.read() or b"{}")


def main():
    md = open(sys.argv[1], encoding="utf-8").read()
    if "--dry-run" in sys.argv:
        print(f"dry run: would post {len(md)} chars to r/{SUB}/wiki/{PAGE}"); return 0
    e = os.environ
    if not e.get("REDDIT_CLIENT_ID"):
        print("no Reddit credentials configured; skipping"); return 0
    basic = base64.b64encode(f"{e['REDDIT_CLIENT_ID']}:{e['REDDIT_CLIENT_SECRET']}".encode()).decode()
    tok = req("https://www.reddit.com/api/v1/access_token",
              {"grant_type": "password", "username": e["REDDIT_USERNAME"], "password": e["REDDIT_PASSWORD"]},
              {"Authorization": f"Basic {basic}"})["access_token"]
    auth = {"Authorization": f"bearer {tok}"}
    cur = req(f"https://oauth.reddit.com/r/{SUB}/wiki/{PAGE}?raw_json=1", headers=auth)["data"]["content_md"]
    if cur.strip() == md.strip():
        print("wiki already current"); return 0
    req(f"https://oauth.reddit.com/r/{SUB}/api/wiki/edit",
        {"page": PAGE, "content": md, "reason": "LiveNerf auto-update from GitHub"}, auth)
    print(f"posted {len(md)} chars to r/{SUB}/wiki/{PAGE}"); return 0


if __name__ == "__main__":
    sys.exit(main())
