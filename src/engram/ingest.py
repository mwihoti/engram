import json
import os
from pathlib import Path

from rich.console import Console

from engram.hydra_client import HydraGraph
from engram.llm import chat_json

console = Console()

REGISTRY = Path("data/.graph_ids.json")
FACTS_LOG = Path("data/.facts.jsonl")

EXTRACT_SYSTEM = """You extract long-term memory facts from a chat session.
Return a json array. Each item:
{"statement": "self-contained fact about the user, past tense not needed",
 "entities": [{"name": "...", "type": "person|place|org|pet|event|skill|other"}],
 "confidence": 0.0-1.0}
Rules: only facts worth remembering across sessions (life events, preferences,
relationships, work, plans). Keep concrete details: amounts, prices, durations,
dates, counts. "Spent $60 on 5 mugs" beats "bought mugs". Resolve pronouns.
Include the user as an entity only when the fact is about them specifically.
3 to 12 facts per session."""

GH_EXTRACT_SYSTEM = """You extract project memory facts from a github thread.
Return a json array. Each item:
{"statement": "self-contained fact naming the PR/issue number",
 "entities": [{"name": "...", "type": "person|pr|issue|component|other"}],
 "confidence": 0.0-1.0}
Capture: what the PR or issue is about, its outcome (merged, closed, open,
and when), who opened it, who reviewed and their verdict, decisions made,
problems reported. Keep numbers, dates and version constraints exact.
3 to 12 facts per thread."""

SUPERSEDE_SYSTEM = """You compare new facts against older ones and spot replacements.
A new fact supersedes an old fact when both describe the same attribute of the
same entity and the new one reflects a later state (moved cities, changed jobs,
changed plans). Complementary facts do not supersede.
Return a json array of pairs: [{"new": <new fact index>, "old": <old fact id>}].
Return [] if none."""


def _load_registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    return {"next": 1000, "sessions": {}, "entities": {}}


def _save_registry(reg):
    REGISTRY.write_text(json.dumps(reg, indent=1))


def _alloc(reg):
    reg["next"] += 1
    return reg["next"]


def _prior_facts():
    if not FACTS_LOG.exists():
        return []
    return [json.loads(line) for line in FACTS_LOG.read_text().splitlines() if line]


def run_ingest(directory):
    files = sorted(Path(directory).glob("*.json"))
    if not files:
        console.print(f"[red]no session files in {directory}[/]")
        return

    reg = _load_registry()
    g = HydraGraph()
    prior = _prior_facts()
    new_fact_records = []

    for path in files:
        session = json.loads(path.read_text())
        sid, date = session["id"], session["date"]
        if sid in reg["sessions"]:
            console.print(f"{sid}: already ingested, skipping")
            continue

        transcript = "\n".join(f"{t['role']}: {t['content']}" for t in session["turns"])
        system = GH_EXTRACT_SYSTEM if session.get("kind") == "github" else EXTRACT_SYSTEM
        facts = chat_json(system, f"Session date: {date}\n\n{transcript}")
        console.print(f"{sid}: extracted {len(facts)} facts")

        session_node = _alloc(reg)
        reg["sessions"][sid] = session_node
        session_props_written = False

        for fact in facts:
            fid = _alloc(reg)
            fact["fact_id"] = fid
            fact["session_id"] = sid
            fact["date"] = date

            if not session_props_written:
                g.run(
                    "CREATE (f:Fact {id: $fid, statement: $st, confidence: $conf, valid_from: $d})"
                    "-[:FROM]->(s:Session {id: $snode, sid: $sid, date: $d})",
                    fid=fid, st=fact["statement"], conf=float(fact.get("confidence", 0.8)),
                    d=date, snode=session_node, sid=sid,
                )
                session_props_written = True
            else:
                g.run(
                    "CREATE (f:Fact {id: $fid, statement: $st, confidence: $conf, valid_from: $d})"
                    "-[:FROM]->(s {id: $snode})",
                    fid=fid, st=fact["statement"], conf=float(fact.get("confidence", 0.8)),
                    d=date, snode=session_node,
                )

            for ent in fact.get("entities", []):
                key = f"{ent['name'].lower()}|{ent.get('type', 'other')}"
                if key in reg["entities"]:
                    g.run(
                        "CREATE (f {id: $fid})-[:ABOUT]->(e {id: $eid})",
                        fid=fid, eid=reg["entities"][key],
                    )
                else:
                    eid = _alloc(reg)
                    reg["entities"][key] = eid
                    g.run(
                        "CREATE (f {id: $fid})-[:ABOUT]->(e:Entity {id: $eid, name: $name, type: $type})",
                        fid=fid, eid=eid, name=ent["name"], type=ent.get("type", "other"),
                    )

        # supersede pass against everything ingested before this session
        if prior:
            old_block = "\n".join(
                f"id={p['fact_id']}: {p['statement']} (from {p['date']})" for p in prior
            )
            new_block = "\n".join(
                f"index={i}: {f['statement']} (from {date})" for i, f in enumerate(facts)
            )
            pairs = chat_json(
                SUPERSEDE_SYSTEM,
                f"OLD FACTS:\n{old_block}\n\nNEW FACTS:\n{new_block}",
            )
            for pair in pairs:
                new_fact = facts[pair["new"]]
                g.run(
                    "CREATE (a {id: $new})-[:SUPERSEDES]->(b {id: $old})",
                    new=new_fact["fact_id"], old=pair["old"],
                )
                g.run("MATCH (b {id: $old}) SET b.valid_to = $d", old=pair["old"], d=date)
                console.print(
                    f"  supersedes: fact {new_fact['fact_id']} replaces {pair['old']}"
                )

        prior.extend(facts)
        new_fact_records.extend(facts)
        _save_registry(reg)
        # append per session so a crash never desyncs the log from the graph
        with FACTS_LOG.open("a") as fh:
            for f in facts:
                fh.write(json.dumps(f) + "\n")

    if os.environ.get("HYDRA_DB_API_KEY") and new_fact_records:
        from engram.hydra_client import HydraVectors

        v = HydraVectors()
        v.ensure_database()
        ids = v.push_facts(new_fact_records)
        console.print(f"pushed {len(ids)} facts to hydradb cloud vectorstore, waiting for indexing")
        v.wait_indexed(ids)
        console.print("indexing complete")
    elif new_fact_records:
        console.print("[yellow]no HYDRA_DB_API_KEY, facts kept in local index only[/]")

    g.close()
    console.print(f"done, {len(new_fact_records)} new facts in memory")
