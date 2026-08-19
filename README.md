# Engram

Long-term memory for AI agents, built on HydraDB.

Agents forget everything between sessions. Engram ingests past chat sessions into a HydraDB knowledge graph, answers new questions using only what it remembers, cites the session it learned each fact from, and says "not in memory" instead of guessing when the graph has no confident evidence.

Built for Hack Hydra 2026, Track 3 (Memory and Context Retrieval).

Work in progress. Setup and eval numbers land here as the build progresses.

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env   # fill in keys
bash scripts/hydradb-local.sh   # in a second terminal
engram smoke
```
