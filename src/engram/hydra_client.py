"""Both HydraDB backends live behind this file: the local OSS graph node
(Cypher over Bolt) and the cloud hybrid vectorstore. Nothing else in the
app talks to HydraDB directly."""

import json
import os
import time

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError


def _bolt_auth(token):
    import neo4j
    return neo4j.bearer_auth(token)


class HydraGraph:
    def __init__(self, uri=None, token=None):
        self.uri = uri or os.environ.get("HYDRA_BOLT_URI", "bolt://127.0.0.1:7687")
        self.token = token or os.environ.get(
            "HYDRA_BOLT_TOKEN", "local-development-token-32-bytes"
        )
        try:
            self._driver = GraphDatabase.driver(self.uri, auth=_bolt_auth(self.token))
            self._driver.verify_connectivity()
        except AuthError:
            # some builds want the token as a basic-auth password instead
            self._driver = GraphDatabase.driver(self.uri, auth=("hydra", self.token))
            self._driver.verify_connectivity()

    def run(self, cypher, **params):
        with self._driver.session() as s:
            return [r.data() for r in s.run(cypher, **params)]

    def close(self):
        self._driver.close()


class HydraVectors:
    """Fact text goes into HydraDB cloud as memories, comes back via
    hybrid (semantic + bm25) query. Metadata carries the graph fact id
    so hits can be joined back to the local graph."""

    def __init__(self, database="engram", collection="facts"):
        from hydra_db import HydraDB

        key = os.environ.get("HYDRA_DB_API_KEY")
        if not key:
            raise RuntimeError("HYDRA_DB_API_KEY not set, hybrid retrieval unavailable")
        self.client = HydraDB(token=key)
        self.database = database
        self.collection = collection

    def ensure_database(self):
        from hydra_db.errors.conflict_error import ConflictError

        try:
            self.client.databases.create(database=self.database)
        except ConflictError:
            pass  # already exists, which is what we want

    def push_facts(self, facts):
        # facts: [{fact_id, statement, session_id, date}]
        memories = [
            {
                "text": f["statement"],
                "infer": False,
                "metadata": {},
                "additional_metadata": {
                    "fact_id": f["fact_id"],
                    "session_id": f["session_id"],
                    "date": f["date"],
                },
            }
            for f in facts
        ]
        from hydra_db.errors.content_too_large_error import ContentTooLargeError

        ids, batch = [], 30  # server enforces a per-request token budget
        i = 0
        while i < len(memories):
            chunk = memories[i : i + batch]
            try:
                resp = self.client.context.ingest(
                    type="memory",
                    database=self.database,
                    collection=self.collection,
                    memories=json.dumps(chunk),
                )
            except ContentTooLargeError:
                if batch == 1:
                    raise
                batch = max(1, batch // 2)
                continue
            data = getattr(resp, "data", resp)
            items = getattr(data, "results", None) or []
            ids += [it.id for it in items
                    if getattr(it, "id", None) and not getattr(it, "error", None)]
            i += len(chunk)
        return ids

    def wait_indexed(self, source_ids, timeout=300):
        if not source_ids:
            return True
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.context.status(database=self.database, ids=source_ids)
            data = getattr(resp, "data", resp)
            statuses = [getattr(s, "status", None) for s in getattr(data, "statuses", None) or []]
            if statuses and all(s == "completed" for s in statuses):
                return True
            if any(s == "failed" for s in statuses):
                raise RuntimeError(f"hydradb indexing failed: {statuses}")
            time.sleep(5)
        raise TimeoutError("hydradb indexing did not complete in time")

    def search(self, query, top_k=8):
        res = self.client.query(
            database=self.database,
            collection=self.collection,
            query=query,
            type="memory",
            query_by="hybrid",
            mode="fast",
            max_results=top_k,
        )
        chunks = getattr(getattr(res, "data", res), "chunks", None) or []
        out = []
        for c in chunks:
            meta = getattr(c, "additional_metadata", None) or {}
            out.append(
                {
                    "text": getattr(c, "chunk_content", ""),
                    "score": round(getattr(c, "relevancy_score", 0.0) or 0.0, 3),
                    "fact_id": meta.get("fact_id"),
                    "session_id": meta.get("session_id"),
                    "date": meta.get("date"),
                }
            )
        return out[:top_k]
