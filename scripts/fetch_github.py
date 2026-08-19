"""Turns a repo's recent activity into Engram sessions: one session per
issue or PR thread, comments and reviews as turns, outcome stamped at the
end. Uses the gh cli for auth. Usage:

    python scripts/fetch_github.py hydra-db/hydradb --limit 8
"""

import argparse
import json
import subprocess
from pathlib import Path

OUT = Path("data/github_sessions")
MAX_BODY = 1200


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh api {path} failed: {r.stderr[:200]}")
    return json.loads(r.stdout)


def clip(text):
    text = (text or "").strip()
    return text[:MAX_BODY] + (" ..." if len(text) > MAX_BODY else "")


def turns_for(repo, item, kind):
    n = item["number"]
    turns = [{
        "role": "user",
        "content": f"{item['user']['login']} opened {kind} #{n}: {item['title']}\n{clip(item['body'])}",
    }]
    for c in gh(f"repos/{repo}/issues/{n}/comments?per_page=30"):
        turns.append({
            "role": "user",
            "content": f"{c['user']['login']} commented: {clip(c['body'])}",
        })
    if kind == "PR":
        for rv in gh(f"repos/{repo}/pulls/{n}/reviews?per_page=30"):
            verdict = rv.get("state", "").lower().replace("_", " ")
            turns.append({
                "role": "user",
                "content": f"{rv['user']['login']} reviewed ({verdict}): {clip(rv.get('body'))}",
            })
        if item.get("merged_at"):
            outcome = f"OUTCOME: PR #{n} was merged on {item['merged_at'][:10]}"
        elif item["state"] == "closed":
            outcome = f"OUTCOME: PR #{n} was closed without being merged on {item['closed_at'][:10]}"
        else:
            outcome = f"OUTCOME: PR #{n} is still open"
    else:
        if item["state"] == "closed":
            outcome = f"OUTCOME: issue #{n} was closed on {item['closed_at'][:10]}"
        else:
            outcome = f"OUTCOME: issue #{n} is still open"
    turns.append({"role": "user", "content": outcome})
    return turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--limit", type=int, default=8, help="threads of each kind")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    written = 0

    prs = gh(f"repos/{args.repo}/pulls?state=all&sort=updated&direction=desc&per_page={args.limit}")
    for pr in prs:
        pr = gh(f"repos/{args.repo}/pulls/{pr['number']}")  # full object has merged_at
        sid = f"gh-pr-{pr['number']}"
        (OUT / f"{sid}.json").write_text(json.dumps({
            "id": sid, "date": pr["created_at"][:10], "kind": "github",
            "turns": turns_for(args.repo, pr, "PR"),
        }, indent=1))
        written += 1

    issues = gh(f"repos/{args.repo}/issues?state=all&sort=updated&direction=desc&per_page={args.limit * 2}")
    count = 0
    for issue in issues:
        if "pull_request" in issue or count >= args.limit:
            continue
        sid = f"gh-issue-{issue['number']}"
        (OUT / f"{sid}.json").write_text(json.dumps({
            "id": sid, "date": issue["created_at"][:10], "kind": "github",
            "turns": turns_for(args.repo, issue, "issue"),
        }, indent=1))
        written += 1
        count += 1

    print(f"{written} thread sessions -> {OUT}")


if __name__ == "__main__":
    main()
