"""Retrieval: hybrid search over fact text, then graph hops in HydraDB
to pull connected entities and walk SUPERSEDES chains so the newest
version of a changed fact wins."""

import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from engram.hydra_client import HydraGraph

FACTS_LOG = Path("data/.facts.jsonl")


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _local_bm25(question, top_k):
    # dev fallback when there is no cloud key. The real path is
    # HydraDB's hybrid query (semantic + bm25 + rerank).
    facts = [json.loads(l) for l in FACTS_LOG.read_text().splitlines() if l]
    docs = [_tokens(f["statement"]) for f in facts]
    df = Counter(t for d in docs for t in set(d))
    avgdl = sum(len(d) for d in docs) / max(len(docs), 1)
    q = _tokens(question)
    scored = []
    for f, d in zip(facts, docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avgdl))
        if s > 0:
            scored.append({**f, "score": round(min(s / 4.0, 1.0), 3)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def _vector_hits(question, top_k):
    if os.environ.get("HYDRA_DB_API_KEY"):
        from engram.hydra_client import HydraVectors

        return HydraVectors().search(question, top_k=top_k)
    return _local_bm25(question, top_k)


def _fact_record(g, fid):
    rows = g.run(
        "MATCH (f {id: $fid})-[:FROM]->(s) "
        "RETURN f.statement, f.valid_from, f.valid_to, f.confidence, s.sid, s.date",
        fid=fid,
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "fact_id": fid,
        "statement": r["f.statement"],
        "valid_from": r["f.valid_from"],
        "valid_to": r["f.valid_to"],
        "confidence": r["f.confidence"],
        "session_id": r["s.sid"],
        "date": r["s.date"],
    }


def _newest_version(g, fid, seen=None):
    # follow (newer)-[:SUPERSEDES]->(this) links upward to the head
    seen = seen or set()
    if fid in seen:
        return fid
    seen.add(fid)
    rows = g.run("MATCH (n)-[:SUPERSEDES]->(f {id: $fid}) RETURN n.id", fid=fid)
    if not rows:
        return fid
    return _newest_version(g, rows[0]["n.id"], seen)


def _valid_as_of(rec, as_of):
    if rec["valid_from"] and rec["valid_from"] > as_of:
        return False
    if rec["valid_to"] and rec["valid_to"] <= as_of:
        return False
    return True


def retrieve(question, mode="graph", as_of=None, top_k=8):
    hits = _vector_hits(question, top_k)

    if mode == "vector":
        # similarity only, no graph. Kept for the ablation.
        return [
            {
                "fact_id": h["fact_id"],
                "statement": h.get("text") or h.get("statement"),
                "session_id": h["session_id"],
                "date": h["date"],
                "score": h["score"],
                "via": "similarity",
            }
            for h in hits
        ]

    g = HydraGraph()
    evidence = {}
    for h in hits:
        fid = h["fact_id"]
        base = h["score"]

        head = _newest_version(g, fid) if as_of is None else fid
        rec = _fact_record(g, head)
        if rec is None:
            continue
        if as_of and not _valid_as_of(rec, as_of):
            continue
        if as_of is None and rec["valid_to"]:
            # still superseded even at the head? then it's stale, keep but flag
            rec["stale"] = True
        via = "similarity" if head == fid else "supersedes chain"
        score = base if head == fid else min(base + 0.1, 1.0)
        if head not in evidence or evidence[head]["score"] < score:
            evidence[head] = {**rec, "score": round(score, 3), "via": via}

        # one hop out: other facts about the same entities
        ents = g.run("MATCH (f {id: $fid})-[:ABOUT]->(e) RETURN e.id, e.name", fid=fid)
        for e in ents:
            siblings = g.run(
                "MATCH (f2)-[:ABOUT]->(e {id: $eid}) RETURN f2.id", eid=e["e.id"]
            )
            for s in siblings:
                sfid = s["f2.id"]
                if sfid == fid or sfid in evidence:
                    continue
                shead = _newest_version(g, sfid) if as_of is None else sfid
                srec = _fact_record(g, shead)
                if srec is None or shead in evidence:
                    continue
                if as_of and not _valid_as_of(srec, as_of):
                    continue
                if as_of is None and srec["valid_to"]:
                    continue  # superseded siblings add noise, drop them
                evidence[shead] = {
                    **srec,
                    "score": round(base * 0.5, 3),
                    "via": f"graph hop ({e['e.name']})",
                }
    g.close()

    out = sorted(evidence.values(), key=lambda x: -x["score"])
    return out[:top_k]
