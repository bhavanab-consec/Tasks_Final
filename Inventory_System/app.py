"""
Flask API (ASGI‑compatible) that implements a strict‑consistency
“buy ticket” operation on a **SQLite** database.

Key points
----------
* SQLite's `UPDATE … WHERE stock > 0` is atomic – no overselling.
* The whole operation runs inside `BEGIN IMMEDIATE` which obtains a
  RESERVED lock so no other writer can start until we COMMIT/ROLLBACK.
* On “database is locked” we retry (max 5 attempts) with exponential back‑off.
* 200 – purchase succeeded
* 410 – sold out (stock already 0)
"""

import os
import time
from typing import Optional

from flask import Flask, jsonify, request
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    DateTime,
    func,
    text,
    update,
    insert,
    select,
)
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy.orm import sessionmaker

# Configuration
# SQLite file will sit next to the source code.
DB_URL = os.getenv(
    "DATABASE_URL", "sqlite:///inventory.db?check_same_thread=False"
)

# Engine with a small connection pool (4 workers * 2 = 8 is enough)
engine = create_engine(
    DB_URL,
    connect_args={"timeout": 30},  # wait up to 30 s for a lock
    pool_size=8,
    future=True,
)

metadata = MetaData()

inventory_tbl = Table(
    "inventory",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_name", String(64), nullable=False, unique=True),
    Column("stock", Integer, nullable=False),
)

purchase_tbl = Table(
    "purchase_record",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer, nullable=False),
    Column("purchased_at", DateTime(timezone=True), server_default=func.now()),
)

Session = sessionmaker(bind=engine, future=True)


# Flask app (runs under any ASGI server – Hypercorn, Uvicorn, etc.)
app = Flask(__name__)


# Helper – run a function inside an IMMEDIATE transaction with retry
MAX_RETRIES = 5
BASE_BACKOFF = 0.05  # seconds (will be multiplied by attempt)

def run_in_transaction(fn):
    """Execute fn(session) inside a BEGIN IMMEDIATE transaction.
    Retries on `database is locked` (SQLite error 5)."""
    attempt = 0
    while True:
        attempt += 1
        sess = Session()
        # IMMEDIATE acquires a RESERVED lock right away
        sess.execute(text("BEGIN IMMEDIATE"))
        try:
            result = fn(sess)
            sess.commit()
            return result
        except OperationalError as exc:
            # SQLite error code 5 == database is locked
            if getattr(exc.orig, "sqlite_errorcode", None) == 5 and attempt <= MAX_RETRIES:
                sess.rollback()
                backoff = BASE_BACKOFF * (2 ** (attempt - 1))
                time.sleep(backoff)
                continue
            sess.rollback()
            raise
        finally:
            sess.close()

# Endpoint
@app.route("/buy_ticket", methods=["POST"])
def buy_ticket():
    """
    Expected JSON payload:
        {"item_name": "Item A"}
    """
    data = request.get_json(force=True)
    item_name: Optional[str] = data.get("item_name")
    if not item_name:
        return jsonify({"error": "item_name required"}), 400

    try:
        def txn_logic(sess):
            # 1️.  Find the inventory row (no lock needed – UPDATE will lock)
            inv_row = sess.execute(
                select(inventory_tbl.c.id, inventory_tbl.c.stock)
                .where(inventory_tbl.c.item_name == item_name)
            ).first()

            if not inv_row:
                raise ValueError("Item not found")

            # 2️.  Try to decrement stock atomically.
            #    The WHERE clause guarantees we only affect rows with stock > 0.
            upd = (
                update(inventory_tbl)
                .where(inventory_tbl.c.id == inv_row.id)
                .where(inventory_tbl.c.stock > 0)
                .values(stock=inventory_tbl.c.stock - 1)
            )
            result = sess.execute(upd)

            if result.rowcount == 0:
                # Stock already 0 – nothing changed
                return False

            # 3️.  Record the purchase
            sess.execute(
                insert(purchase_tbl).values(item_id=inv_row.id)
            )
            return True

        succeeded = run_in_transaction(txn_logic)

        if succeeded:
            return jsonify({"status": "purchased"}), 200
        else:
            return jsonify({"status": "sold out"}), 410

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as exc:  # pragma: no cover
        app.logger.exception("Unexpected error in /buy_ticket")
        return jsonify({"error": "internal server error"}), 500


# Run locally (single‑process, helpful for debugging)
if __name__ == "__main__":
    # Flask's built‑in server – *single* process only
    app.run(host="0.0.0.0", port=8000, debug=True)