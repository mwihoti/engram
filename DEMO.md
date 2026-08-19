# Demo script, 3 minutes

## 0:00 The problem (25s)

Screen: terminal, repo open.

"Every agent you talk to is amnesiac. And the usual fix, vector RAG, has a nastier bug: similarity search happily serves facts that stopped being true. I built Engram, a memory layer on HydraDB that versions facts in a knowledge graph, cites its sources, and refuses to guess."

## 0:25 Ingest (30s)

Run `engram ingest`. Narrate while it streams:

"Three months of chat sessions. An LLM extracts time-stamped facts and entities, writes them to a HydraDB graph over Cypher, and pushes the text into HydraDB's hybrid vectorstore. Watch the supersedes line: in March I said I live in Austin, in July I moved to Denver. Engram catches that and links the two facts."

## 0:55 The stale fact moment (45s)

Switch to the web ui (`engram serve`, localhost:8080) or stay in the
terminal, whichever records better. Ask "where do I live?" in vector
mode first:

"Vector mode, similarity only. It retrieves the Austin fact. Confidently wrong, this is what most RAG memory does today."

Then `engram ask "where do I live?"`:

"Graph mode. Same hybrid hit, but Engram walks the SUPERSEDES chain in HydraDB and answers Denver, citing the July session. And because facts carry validity dates:"

Run `engram ask "where do I live?" --as-of 2026-05-01`:

"...it can answer as of May, when Austin was still true."

## 1:40 Abstention (25s)

Run `engram ask "what's my favorite food?"`:

"Never told it. Below the evidence threshold Engram says not in memory instead of hallucinating. The threshold is one tunable number."

## 2:05 Eval numbers (35s)

Show the `engram eval` output table (pre-run):

"Twenty LongMemEval questions, graded across both modes. The number I care about: zero hallucinations in forty runs, and all five trick questions with no answer in memory were correctly refused. When this memory is wrong, it is wrong by staying silent, never by making things up. That is what you want from an agent's memory."

## 2:40 The graph is real (20s)

Show the HydraDB node log or a live Cypher query returning the SUPERSEDES edge.

"Everything you saw is Cypher against HydraDB's open source engine plus their hybrid vectorstore. Repo link below. Thanks."
