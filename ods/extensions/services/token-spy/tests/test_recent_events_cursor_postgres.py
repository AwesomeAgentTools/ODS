"""Postgres backend SSE cursor tests for /token_events.

Requires a live Postgres reachable via the same DB_HOST/DB_PORT/DB_NAME/
DB_USER/DB_PASSWORD env vars db_postgres.py itself reads. No workflow
provisions Postgres for this repo's CI today, so these skip cleanly when
none is configured rather than failing the run.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

psycopg2 = pytest.importorskip("psycopg2")

TOKEN_SPY_DIR = Path(__file__).resolve().parent.parent


def _connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5434"),
        dbname=os.environ.get("DB_NAME", "tokenspy"),
        user=os.environ.get("DB_USER", "tokenspy"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


@pytest.fixture
def pg_db():
    try:
        conn = _connect()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"no live postgres reachable for db_postgres tests: {exc}")

    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT, slug TEXT UNIQUE, plan TEXT, deleted_at TIMESTAMPTZ)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID, name TEXT, slug TEXT)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID, agent_id UUID, request_id TEXT, provider TEXT,
            model TEXT, input_tokens INT, output_tokens INT,
            estimated_cost_usd NUMERIC, "timestamp" TIMESTAMPTZ)
        """
    )
    cur.execute("TRUNCATE requests, agents, tenants CASCADE")
    cur.execute("INSERT INTO tenants (name, slug, plan) VALUES ('Default', 'default', 'free')")
    conn.commit()
    cur.close()
    conn.close()

    spec = importlib.util.spec_from_file_location(
        f"token_spy_postgres_db_{uuid4().hex}", TOKEN_SPY_DIR / "db_postgres.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_db()
    try:
        yield module
    finally:
        if module._pool is not None:
            module._pool.closeall()


def _insert_row(db, tenant_id, when, counter):
    conn = _connect()
    cur = conn.cursor()
    row_id = uuid4()
    cur.execute(
        """
        INSERT INTO requests (id, tenant_id, request_id, provider, model,
            input_tokens, output_tokens, estimated_cost_usd, timestamp)
        VALUES (%s, %s, %s, 'openai', 'gpt-4o', 100, 50, 0.01, %s)
        """,
        (row_id, tenant_id, f"req-{counter}", when),
    )
    conn.commit()
    cur.close()
    conn.close()
    return row_id


def test_forward_poll_delivers_every_row_inserted_after_connect(pg_db):
    """r.id is a random uuid4(), so filtering `id > after_id` has no
    relationship to insertion order and admits or drops rows by chance.
    A client that connects, then polls forward as new rows arrive, must
    see every one of them: none silently dropped."""
    tenant_id = pg_db._tenant_id
    base = datetime(2026, 7, 27, tzinfo=timezone.utc)
    counter = 0
    for _ in range(3):
        _insert_row(pg_db, tenant_id, base + timedelta(seconds=counter), counter)
        counter += 1

    initial = pg_db.query_recent_events(limit=50, after_id=None)
    last_id = initial[-1]["id"] if initial else None

    delivered = set()
    live_inserted = set()
    for _ in range(8):
        batch = [
            _insert_row(pg_db, tenant_id, base + timedelta(seconds=counter + i), counter + i)
            for i in range(3)
        ]
        counter += 3
        live_inserted.update(str(row_id) for row_id in batch)

        events = pg_db.query_recent_events(limit=50, after_id=last_id)
        for event in events:
            delivered.add(str(event["id"]))
            last_id = event["id"]

    assert live_inserted <= delivered


def test_cursor_past_end_returns_empty_not_backlog(pg_db):
    """Once the cursor is caught up to the newest row, the next poll must
    return nothing, not silently resend part of the backlog."""
    tenant_id = pg_db._tenant_id
    base = datetime(2026, 7, 27, tzinfo=timezone.utc)
    for i in range(5):
        _insert_row(pg_db, tenant_id, base + timedelta(seconds=i), i)

    # query_recent_events serves the newest page first (DESC), so the
    # newest row is the first one, not the last.
    initial = pg_db.query_recent_events(limit=50, after_id=None)
    newest_id = initial[0]["id"]

    assert pg_db.query_recent_events(limit=50, after_id=newest_id) == []
