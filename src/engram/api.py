from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engram.answer import answer_question, threshold

app = FastAPI(title="engram")

STATIC = Path(__file__).parent / "static"


class Ask(BaseModel):
    question: str
    mode: str = "graph"
    as_of: str | None = None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/ask")
def ask(req: Ask):
    res = answer_question(req.question, mode=req.mode, as_of=req.as_of)
    return {
        "abstained": res["abstained"],
        "answer": res["answer"],
        "reason": res["reason"],
        "threshold": threshold(),
        "cited": [
            {"session": c["session_id"], "date": c["date"]} for c in res.get("cited", [])
        ],
        "evidence": [
            {
                "statement": e["statement"],
                "session": e["session_id"],
                "date": e["date"],
                "score": e["score"],
                "via": e.get("via", ""),
            }
            for e in res["evidence"]
        ],
    }


def serve(port=8080):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port)
