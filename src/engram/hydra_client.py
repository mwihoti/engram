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
        self.uri = uri or os.environ.get("HYDRA_BOLT_URI", "neo4j://127.0.0.1:7687")
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
        existing = self.client.databases.list()
        names = [d.get("database") if isinstance(d, dict) else getattr(d, "database", None)
                 for d in getattr(existing, "databases", existing) or []]
        if self.database not in names:
            self.client.databases.create(database=self.database)

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
        return self.client.context.ingest(
            type="memory",
            database=self.database,
            collection=self.collection,
            memories=json.dumps(memories),
        )

    def wait_indexed(self, timeout=120):
        start = time.time()
        while time.time() - start < timeout:
            status = self.client.context.status(database=self.database)
            state = getattr(status, "indexing_status", None) or (
                status.get("indexing_status") if isinstance(status, dict) else None
            )
            if state == "completed":
                return True
            time.sleep(3)
        raise TimeoutError("hydradb indexing did not complete in time")

    def search(self, query, top_k=8):
        res = self.client.query(
            database=self.database,
            query=query,
            type="memory",
            query_by="hybrid",
            mode="fast",
        )
        return self._normalize(res)[:top_k]

    @staticmethod
    def _normalize(res):
        raw = res if isinstance(res, (list, dict)) else res.__dict__
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        out = []
        for it in items or []:
            d = it if isinstance(it, dict) else it.__dict__
            meta = d.get("additional_metadata") or d.get("metadata") or {}
            out.append(
                {
                    "text": d.get("text") or d.get("content") or "",
                    "score": d.get("score") or d.get("relevance") or 0.0,
                    "fact_id": meta.get("fact_id"),
                    "session_id": meta.get("session_id"),
                    "date": meta.get("date"),
                }
            )
        return out
