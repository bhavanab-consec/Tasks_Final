import aiosqlite
import json
import asyncio
from typing import List, Tuple

DB_PATH = "events.db"
# 1️.  Schema – a single table with a JSON column (SQLite 3.38+ has native JSON)
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    ts          TEXT    NOT NULL,
    metadata    TEXT    NOT NULL   -- stored as JSON string
);
"""


# 2️.  Helper – open a connection (re‑used by the background worker)
async def init_db() -> aiosqlite.Connection:
    """Create the DB file (if missing) and ensure the schema exists."""
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn

# 3️.  Batched INSERT – receives a list of rows [(user_id, ts, metadata_json), …]
async def batch_insert(
    conn: aiosqlite.Connection,
    rows: List[Tuple[int, str, str]],
) -> None:
    """
    Insert many rows inside a single transaction.
    Parameterised SQL + JSON string ensures no injection risk.
    """
    async with conn.executemany(
        "INSERT INTO events (user_id, ts, metadata) VALUES (?, ?, ?)", rows
    ):
        await conn.commit()