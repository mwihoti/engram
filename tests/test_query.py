"""Needs the local hydradb node running (scripts/hydradb-local.sh).
Seeds a small graph in the 900000 id range and cleans it up."""

import json

import pytest

from engram import query
from engram.hydra_client import HydraGraph

S1, S2 = 900001, 900002          # sessions
F_OLD, F_NEW, F_DOG = 900011, 900012, 900013
E_CITY, E_DOG = 900021, 900022


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    g = HydraGraph()
    g.run(
        "CREATE (f:Fact {id: $f, statement: 'user lives in Austin', valid_from: '2026-03-05', valid_to: '2026-07-22', confidence: 0.9})"
        "-[:FROM]->(s:Session {id: $s, sid: 'old-session', date: '2026-03-05'})",
        f=F_OLD, s=S1,
    )
    g.run(
        "CREATE (f:Fact {id: $f, statement: 'user lives in Denver', valid_from: '2026-07-22', confidence: 0.9})"
        "-[:FROM]->(s:Session {id: $s, sid: 'new-session', date: '2026-07-22'})",
        f=F_NEW, s=S2,
    )
    g.run(
        "CREATE (f:Fact {id: $f, statement: 'user has a dog named Biscuit', valid_from: '2026-03-05', confidence: 0.9})"
        "-[:FROM]->(s {id: $s})",
        f=F_DOG, s=S1,
    )
    g.run("CREATE (a {id: $a})-[:SUPERSEDES]->(b {id: $b})", a=F_NEW, b=F_OLD)
    for f, e, name, typ in [
        (F_OLD, E_CITY, "Austin", "place"),
        (F_NEW, E_CITY, "Denver", "place"),
        (F_DOG, E_DOG, "Biscuit", "pet"),
    ]:
        g.run(
            "CREATE (f {id: $f})-[:ABOUT]->(e:Entity {id: $e, name: $name, type: $t})",
            f=f, e=e, name=name, t=typ,
        )

    facts_log = tmp_path_factory.mktemp("data") / "facts.jsonl"
    rows = [
        {"fact_id": F_OLD, "statement": "user lives in Austin",
         "session_id": "old-session", "date": "2026-03-05"},
        {"fact_id": F_NEW, "statement": "user lives in Denver",
         "session_id": "new-session", "date": "2026-07-22"},
        {"fact_id": F_DOG, "statement": "user has a dog named Biscuit",
         "session_id": "old-session", "date": "2026-03-05"},
    ]
    facts_log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    query.FACTS_LOG = facts_log

    yield g

    for a, rel, b in [
        (F_OLD, "FROM", S1), (F_NEW, "FROM", S2), (F_DOG, "FROM", S1),
        (F_NEW, "SUPERSEDES", F_OLD), (F_OLD, "ABOUT", E_CITY),
        (F_NEW, "ABOUT", E_CITY), (F_DOG, "ABOUT", E_DOG),
    ]:
        g.run(f"MATCH (a {{id: {a}}})-[r:{rel}]->(b {{id: {b}}}) DELETE r")
    g.close()


def test_vector_mode_returns_stale_fact(seeded, monkeypatch):
    monkeypatch.delenv("HYDRA_DB_API_KEY", raising=False)
    hits = query.retrieve("which city does the user live in", mode="vector")
    statements = [h["statement"] for h in hits]
    assert "user lives in Austin" in statements  # similarity alone keeps the stale answer


def test_graph_mode_follows_supersedes_to_current(seeded, monkeypatch):
    monkeypatch.delenv("HYDRA_DB_API_KEY", raising=False)
    hits = query.retrieve("which city does the user live in", mode="graph")
    assert hits, "expected evidence"
    top = hits[0]
    assert top["statement"] == "user lives in Denver"
    assert top["session_id"] == "new-session"
    assert all(h["statement"] != "user lives in Austin" for h in hits)


def test_as_of_returns_the_old_truth(seeded, monkeypatch):
    monkeypatch.delenv("HYDRA_DB_API_KEY", raising=False)
    hits = query.retrieve("which city does the user live in", mode="graph", as_of="2026-05-01")
    statements = [h["statement"] for h in hits]
    assert "user lives in Austin" in statements
    assert "user lives in Denver" not in statements


def test_abstention_gate_on_unknown_topic(seeded, monkeypatch):
    monkeypatch.delenv("HYDRA_DB_API_KEY", raising=False)
    from engram.answer import answer_question

    res = answer_question("what is the user's favorite programming font")
    assert res["abstained"]
