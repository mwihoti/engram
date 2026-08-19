import json
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from engram.answer import answer_question, threshold
from engram.llm import chat_json

console = Console()

SUBSET = Path("eval/longmemeval_subset.json")
RESULTS = Path("eval/results.json")
PROGRESS = Path("eval/.progress.jsonl")

JUDGE_SYSTEM = """You grade an answer against the gold answer for a memory
benchmark. Meaning matters, wording does not. Return json: {"correct": true/false}"""

SWEEP = [0.40, 0.55, 0.70]


def _grade(question, expected, res):
    if expected is None:
        return "right-abstain" if res["abstained"] else "hallucination"
    if res["abstained"]:
        return "wrong-abstain"
    verdict = chat_json(
        JUDGE_SYSTEM,
        f"QUESTION: {question}\nGOLD: {expected}\nANSWER: {res['answer']}",
    )
    return "correct" if verdict.get("correct") else "wrong"


def _counterfactual(outcome, top_score, expected, th):
    # what the outcome would have been at a different gate threshold,
    # using the recorded score instead of re-running the model
    if top_score is None or top_score < th:
        return "right-abstain" if expected is None else "wrong-abstain"
    if outcome in ("right-abstain", "wrong-abstain") and top_score >= th:
        # the model itself abstained above the gate, keep that
        return outcome
    return outcome


def run_eval():
    if not SUBSET.exists():
        raise SystemExit("run eval/build_subset.py first")
    questions = json.loads(SUBSET.read_text())

    rows = []
    if PROGRESS.exists():  # resume a crashed run
        rows = [json.loads(l) for l in PROGRESS.read_text().splitlines() if l]
        console.print(f"[dim]resuming, {len(rows)} rows already done[/]")
    done = {(r["question_id"], r["mode"]) for r in rows}

    for q in questions:
        prompt = f"Today is {q['question_date']}. {q['question']}"
        for mode in ("graph", "vector"):
            if (q["question_id"], mode) in done:
                continue
            t0 = time.time()
            res = answer_question(prompt, mode=mode)
            latency = time.time() - t0
            outcome = _grade(q["question"], q["answer"], res)
            top = res["evidence"][0]["score"] if res["evidence"] else None
            row = {
                "question_id": q["question_id"],
                "type": q["question_type"],
                "mode": mode,
                "outcome": outcome,
                "top_score": top,
                "latency_s": round(latency, 2),
                "answer": res["answer"],
                "expected": q["answer"],
            }
            rows.append(row)
            with PROGRESS.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            console.print(
                f"[dim]{q['question_id']} {mode}[/] {outcome} ({latency:.1f}s)"
            )

    summary = {"threshold": threshold(), "modes": {}, "sweep": {}}
    for mode in ("graph", "vector"):
        mrows = [r for r in rows if r["mode"] == mode]
        answerable = [r for r in mrows if r["expected"] is not None]
        unanswerable = [r for r in mrows if r["expected"] is None]
        summary["modes"][mode] = {
            "accuracy_answerable": round(
                sum(r["outcome"] == "correct" for r in answerable) / len(answerable), 3
            ),
            "right_abstain_rate": round(
                sum(r["outcome"] == "right-abstain" for r in unanswerable)
                / len(unanswerable), 3,
            ),
            "hallucinations": sum(r["outcome"] == "hallucination" for r in mrows),
            "wrong_abstains": sum(r["outcome"] == "wrong-abstain" for r in mrows),
            "avg_latency_s": round(sum(r["latency_s"] for r in mrows) / len(mrows), 2),
            "outcomes": {
                o: sum(r["outcome"] == o for r in mrows)
                for o in ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination")
            },
        }

    graph_rows = [r for r in rows if r["mode"] == "graph"]
    for th in SWEEP:
        outcomes = [
            _counterfactual(r["outcome"], r["top_score"], r["expected"], th)
            for r in graph_rows
        ]
        summary["sweep"][str(th)] = {
            o: outcomes.count(o)
            for o in ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination")
        }

    RESULTS.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))

    t = Table(title="engram eval, 20 longmemeval questions")
    t.add_column("mode")
    for col in ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination", "latency"):
        t.add_column(col, justify="right")
    for mode in ("graph", "vector"):
        m = summary["modes"][mode]
        t.add_row(mode, *[str(m["outcomes"][o]) for o in
                          ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination")],
                  f"{m['avg_latency_s']}s")
    console.print(t)

    t2 = Table(title=f"abstention gate sweep, graph mode (current {threshold()})")
    t2.add_column("threshold")
    for col in ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination"):
        t2.add_column(col, justify="right")
    for th in SWEEP:
        s = summary["sweep"][str(th)]
        t2.add_row(str(th), *[str(s[o]) for o in
                              ("correct", "wrong", "right-abstain", "wrong-abstain", "hallucination")])
    console.print(t2)
    console.print(f"saved to {RESULTS}")
