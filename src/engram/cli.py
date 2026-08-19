import argparse
import sys

from rich.console import Console

console = Console()


def cmd_smoke(args):
    from engram.hydra_client import HydraGraph

    # hydradb's cypher subset: integer ids, one-hop write patterns
    g = HydraGraph()
    console.print(f"connected to {g.uri}")

    g.run(
        "CREATE (f:Fact {id: $fid, statement: $st})"
        "-[:FROM]->(s:Session {id: $sid, date: $date})",
        fid=999001, st="the smoke test ran", sid=999002, date="2026-08-19",
    )
    console.print("wrote Fact -[:FROM]-> Session")

    g.run("MATCH (f {id: $fid}) SET f.valid_to = $d", fid=999001, d="2026-08-20")
    console.print("updated fact.valid_to via SET")

    rows = g.run(
        "MATCH (f)-[:FROM]->(s {id: $sid}) RETURN f.statement, s.date, f.valid_to",
        sid=999002,
    )
    for r in rows:
        console.print(
            f"read back: {r['f.statement']!r} from session dated {r['s.date']}, "
            f"valid_to {r['f.valid_to']}"
        )

    g.run("MATCH (f {id: 999001})-[r:FROM]->(s {id: 999002}) DELETE r")
    console.print("cypher write, update, read, delete: all ok")

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

    p_serve = sub.add_parser("serve", help="web ui on localhost")
    p_serve.add_argument("--port", type=int, default=8080)

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
    elif args.command == "serve":
        from engram.api import serve
        serve(port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
