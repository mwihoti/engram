import argparse
import sys

from rich.console import Console

console = Console()


def cmd_smoke(args):
    from engram.hydra_client import HydraGraph

    g = HydraGraph()
    console.print(f"connected to {g.uri}")

    g.run(
        "MERGE (s:Session {id: $id}) SET s.date = $date, s.summary = $summary",
        id="smoke-1", date="2026-08-19", summary="smoke test session",
    )
    console.print("wrote Session node")

    g.run(
        "MERGE (f:Fact {id: $fid}) SET f.statement = $st "
        "WITH f MATCH (s:Session {id: $sid}) MERGE (f)-[:FROM]->(s)",
        fid="smoke-fact-1", st="the smoke test ran", sid="smoke-1",
    )
    console.print("wrote Fact node + FROM edge")

    rows = g.run(
        "MATCH (f:Fact)-[:FROM]->(s:Session {id: $sid}) RETURN f.statement AS st, s.date AS date",
        sid="smoke-1",
    )
    for r in rows:
        console.print(f"read back: {r['st']!r} from session dated {r['date']}")

    g.run("MATCH (f:Fact {id: 'smoke-fact-1'}) DETACH DELETE f")
    g.run("MATCH (s:Session {id: 'smoke-1'}) DETACH DELETE s")
    console.print("cleaned up, cypher round trip ok")

    import os
    if os.environ.get("HYDRA_DB_API_KEY"):
        from engram.hydra_client import HydraVectors

        v = HydraVectors()
        v.ensure_database()
        console.print(f"cloud vectorstore ok, database {v.database!r}")
    else:
        console.print("[yellow]HYDRA_DB_API_KEY not set, skipped cloud vectorstore check[/]")
    g.close()


def main():
    parser = argparse.ArgumentParser(prog="engram", description="agent memory on hydradb")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("smoke", help="prove the hydradb connection works")

    p_ingest = sub.add_parser("ingest", help="ingest chat sessions into the memory graph")
    p_ingest.add_argument("--dir", default="data/sample_sessions")

    p_ask = sub.add_parser("ask", help="answer a question from memory, or abstain")
    p_ask.add_argument("question")
    p_ask.add_argument("--mode", choices=["graph", "vector"], default="graph")
    p_ask.add_argument("--as-of", dest="as_of", default=None)

    sub.add_parser("eval", help="run the longmemeval subset")

    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.command == "smoke":
        cmd_smoke(args)
    elif args.command == "ingest":
        from engram.ingest import run_ingest
        run_ingest(args.dir)
    elif args.command == "ask":
        from engram.answer import run_ask
        run_ask(args.question, mode=args.mode, as_of=args.as_of)
    elif args.command == "eval":
        from engram.evaluate import run_eval
        run_eval()
    return 0


if __name__ == "__main__":
    sys.exit(main())
