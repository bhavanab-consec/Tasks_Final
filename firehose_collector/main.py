import asyncio
import json
import logging
import time
from typing import List, Tuple

import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, status
from fastapi.responses import JSONResponse

from models import Event
from db import init_db, batch_insert


# Configuration (tweak to match your target machine)
BATCH_MAX_SIZE = 500        # write when we have 500 events …
BATCH_MAX_SECONDS = 1.0      # … or when 2 seconds passed, whichever first
QUEUE_MAXSIZE = 5000    # back‑pressure limit (drops new events if full)

# FastAPI app
app = FastAPI()
logger = logging.getLogger("uvicorn.error")


# Global objects – created once at startup
event_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
db_conn: aiosqlite.Connection | None = None
db_outage_event = asyncio.Event()          # set → “DB is down”
shutdown_event = asyncio.Event()           # for graceful termination


# 1️.  Startup / shutdown hooks
@app.on_event("startup")
async def on_startup():
    global db_conn
    db_conn = await init_db()
    # launch the background worker (does NOT block the event loop)
    asyncio.create_task(batch_worker())
    logger.info("Firehose collector started")


@app.on_event("shutdown")
async def on_shutdown():
    shutdown_event.set()
    if db_conn:
        await db_conn.close()
    logger.info("Firehose collector stopped")


# 2️.  Public endpoint – fire‑and‑forget
@app.post("/event", status_code=status.HTTP_202_ACCEPTED)
async def ingest(event: Event, request: Request):
    """
    Accept the event, put it into the in‑memory queue and immediately
    return HTTP 202.  If the queue is full we *reject* with 429 – the client
    can retry later.
    """
    try:
        event_queue.put_nowait(event)
    except asyncio.QueueFull:
        raise HTTPException(
            status_code=429,
            detail="Ingestion buffer full – try again later",
        )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": "queued"})


# 3️.  Helper – simulate a DB outage (lock DB for 5 s)
@app.post("/simulate_outage")
async def simulate_outage():
    """
    When called, the background worker will *pause* writes for 5 seconds.
    The API continues to accept events (they stay in the queue).
    """
    logger.warning("🔒 Simulating DB outage – writes paused for 5 s")
    db_outage_event.set()          # tell the worker to stop writing
    await asyncio.sleep(5)         # hold the “outage” for 5 s
    db_outage_event.clear()        # resume normal operation
    logger.warning("🔓 DB outage cleared – writes resumed")
    return {"status": "outage simulated for 5 seconds"}


# 4️.  Background worker – pulls from the queue, batches, writes
async def batch_worker():
    """
    Continuously:
      • pull events from the queue,
      • accumulate until `BATCH_MAX_SIZE` or `BATCH_MAX_SECONDS` elapsed,
      • then write the whole batch in one DB transaction.
    If the DB is “down” (simulated by `db_outage_event`) the worker sleeps
    and retries – never drops data.
    """
    batch: List[Tuple[int, str, str]] = []          # rows ready for INSERT
    batch_deadline = time.time() + BATCH_MAX_SECONDS

    while not shutdown_event.is_set():
        timeout = max(0.0, batch_deadline - time.time())
        try:
            # Wait for the next event, but give up after `timeout` seconds
            event: Event = await asyncio.wait_for(event_queue.get(), timeout=timeout)
            # Convert to the tuple format the DB layer expects
            row = (event.user_id, event.timestamp.isoformat(), json.dumps(event.metadata))
            batch.append(row)

            # If we reached size limit → write immediately
            if len(batch) >= BATCH_MAX_SIZE:
                await flush_batch(batch)
                batch = []
                batch_deadline = time.time() + BATCH_MAX_SECONDS

        except asyncio.TimeoutError:
            # Time limit reached – write whatever we have (might be empty)
            if batch:
                await flush_batch(batch)
                batch = []
            batch_deadline = time.time() + BATCH_MAX_SECONDS
        except Exception as exc:
            logger.exception(f"Unexpected error in worker: {exc}")

    # Final drain when the app is shutting down
    if batch:
        await flush_batch(batch)


async def flush_batch(batch: List[Tuple[int, str, str]]) -> None:
    """Write a batch to SQLite – honour the simulated outage flag."""
    if db_outage_event.is_set():
        # Simulated outage – just wait a bit and retry later
        logger.warning("🕒 DB outage active – postponing %d rows", len(batch))
        await asyncio.sleep(1)          # back‑off, then retry
        await flush_batch(batch)        # recursive retry (still safe because batch is small)
        return

    try:
        await batch_insert(db_conn, batch)   # safe, parameterised INSERT
        logger.info("✅ Inserted batch of %d rows", len(batch))
    except aiosqlite.OperationalError as e:
        # Real DB hiccup – keep the batch in memory and retry after a short pause
        logger.error("Database error (%s) – will retry batch of %d rows", e, len(batch))
        await asyncio.sleep(0.5)
        await flush_batch(batch)             # retry



# 5️.  Run the server (only when executed directly)
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        # workers=1  # keep a single process so the in‑memory queue is shared
    )