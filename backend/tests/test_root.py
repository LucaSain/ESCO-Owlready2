"""`/` health/info endpoint, and the read-only contract on the quadstore.

Both are fast: `/` just reports numbers already known at startup, and the
read-only check is a single rejected write, not a real mutation.
"""
import sqlite3

import pytest


def test_root_reports_store_triples_and_skill_count(client):
    resp = client.get("/")
    assert resp.status_code == 200

    body = resp.json()
    assert body["store"].endswith("esco.sqlite3")
    # Ground-truth counts for the known fixture store (7,875,060 triples,
    # 14,257 skills). If these ever change it means a different esco.sqlite3
    # is mounted, which is worth noticing rather than silently tolerating.
    assert body["triples"] == 7_875_060
    assert body["skills_indexed"] == 14_257


def test_quadstore_is_actually_read_only(store_module):
    """The API must never be able to write ESCO_STORE, only the small
    in-memory World reasoning.py builds per request.

    A no-op DELETE (impossible WHERE clause) is enough to prove this: SQLite
    refuses any write against a connection opened in read-only mode before it
    even evaluates whether a row would match.
    """
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        store_module.default_world.graph.execute(
            "DELETE FROM last_numbered_iri WHERE prefix = '__test_probe_never_matches__'"
        )
