import json
import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from engram.llm import chat_json
from engram.query import retrieve

console = Console()

ANSWER_SYSTEM = """You answer questions using ONLY the numbered evidence given.
Never use outside knowledge. Never infer an outcome the evidence does not
state: a review saying something looks mergeable does not mean it merged.
Facts stating current status are authoritative for outcome questions, and
opinions or predictions do not contradict them. If the evidence does not
clearly answer the question, or facts of equal standing contradict each
other, abstain.
Return json: {"answer": "..." or "ABSTAIN", "cited": [evidence numbers used],
"reason": "one short sentence"}"""


def threshold():
    return float(os.environ.get("ENGRAM_ABSTAIN_THRESHOLD", "0.55"))


def answer_question(question, mode="graph", as_of=None):
    """Returns a dict either way; abstaining is a first-class result."""
    evidence = retrieve(question, mode=mode, as_of=as_of)

    if not evidence:
        return {"abstained": True, "reason": "nothing relevant in memory",
                "evidence": [], "answer": None, "cited": []}
    if evidence[0]["score"] < threshold():
        return {"abstained": True,
                "reason": f"best evidence scored {evidence[0]['score']}, "
                          f"below the {threshold()} threshold",
                "evidence": evidence, "answer": None, "cited": []}

    block = "\n".join(
        f"[{i + 1}] {e['statement']} (session {e['session_id']}, {e['date']}, "
        f"score {e['score']}, via {e['via']})"
        for i, e in enumerate(evidence)
    )
    q = question if not as_of else f"{question} (answer as of {as_of})"
    result = chat_json(ANSWER_SYSTEM, f"EVIDENCE:\n{block}\n\nQUESTION: {q}")

    if result.get("answer") in (None, "", "ABSTAIN"):
        return {"abstained": True, "reason": result.get("reason", "model abstained"),
                "evidence": evidence, "answer": None, "cited": []}

    cited = [evidence[i - 1] for i in result.get("cited", [])
             if 1 <= i <= len(evidence)]
    return {"abstained": False, "answer": result["answer"],
            "reason": result.get("reason", ""), "cited": cited, "evidence": evidence}


def run_ask(question, mode="graph", as_of=None):
    res = answer_question(question, mode=mode, as_of=as_of)

    if res["abstained"]:
        console.print(Panel(f"not in memory\n[dim]{res['reason']}[/]",
                            title="engram", border_style="yellow"))
    else:
        cites = ", ".join(
            f"{c['session_id']} ({c['date']})" for c in res["cited"]
        ) or "none"
        console.print(Panel(f"{res['answer']}\n\n[dim]sources: {cites}[/]",
                            title="engram", border_style="green"))

    if res["evidence"]:
        t = Table(title=f"evidence ({mode} mode)", show_lines=False)
        t.add_column("score", justify="right")
        t.add_column("fact")
        t.add_column("session")
        t.add_column("via")
        for e in res["evidence"]:
            t.add_row(str(e["score"]), e["statement"], f"{e['session_id']}\n{e['date']}", e["via"])
        console.print(t)
