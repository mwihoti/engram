"""Builds the eval subset from LongMemEval (oracle variant, cleaned mirror).
Downloads the 15MB source once, picks 20 questions across types, writes
eval/longmemeval_subset.json plus per-session files the ingest command
understands. Re-runnable, deterministic."""

import json
import re
import urllib.request
from pathlib import Path

SRC_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
    "resolve/main/longmemeval_oracle.json"
)
CACHE = Path("/tmp/longmemeval_oracle.json")
OUT = Path("eval/longmemeval_subset.json")
SESS_DIR = Path("data/longmemeval_sessions")

# how many of each question type. Knowledge-update and abstention are the
# point of the project, so they get the most seats.
PICKS = {
    "knowledge-update": 4,
    "multi-session": 4,
    "single-session-user": 4,
    "temporal-reasoning": 3,
    "abstention": 5,
}


def iso(date_str):
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_str)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else date_str[:10]


def main():
    if not CACHE.exists():
        print("downloading longmemeval oracle ...")
        urllib.request.urlretrieve(SRC_URL, CACHE)
    data = json.load(CACHE.open())

    chosen = []
    for qtype, n in PICKS.items():
        if qtype == "abstention":
            pool = [d for d in data if d["question_id"].endswith("_abs")]
        else:
            pool = [
                d for d in data
                if d["question_type"] == qtype and not d["question_id"].endswith("_abs")
            ]
        # fewest sessions first keeps ingestion small, then id for determinism
        pool.sort(key=lambda d: (len(d["haystack_sessions"]), d["question_id"]))
        chosen.extend(pool[:n])

    SESS_DIR.mkdir(parents=True, exist_ok=True)
    subset, written = [], set()
    for q in chosen:
        sess_ids = []
        for sid, date, turns in zip(
            q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]
        ):
            sess_ids.append(sid)
            if sid in written:
                continue
            written.add(sid)
            (SESS_DIR / f"{sid}.json").write_text(json.dumps({
                "id": sid,
                "date": iso(date),
                "turns": [{"role": t["role"], "content": t["content"]} for t in turns],
            }, indent=1))
        subset.append({
            "question_id": q["question_id"],
            "question_type": "abstention" if q["question_id"].endswith("_abs")
                             else q["question_type"],
            "question": q["question"],
            "answer": None if q["question_id"].endswith("_abs") else q["answer"],
            "question_date": iso(q["question_date"]),
            "sessions": sess_ids,
        })

    OUT.write_text(json.dumps(subset, indent=1))
    print(f"{len(subset)} questions, {len(written)} sessions -> {SESS_DIR}")


if __name__ == "__main__":
    main()
