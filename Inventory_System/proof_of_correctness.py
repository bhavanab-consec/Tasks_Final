"""
Spawns many concurrent processes that call POST /buy_ticket.
After the run it checks that exactly 100 purchases were recorded
and that the inventory count is 0 (never negative, never positive).

Run:
    python proof_of_correctness.py
"""

import os
import time
import multiprocessing
from collections import Counter

import requests
from sqlalchemy import create_engine, MetaData, Table, select

# Config – must match app.py
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
ENDPOINT = f"{BASE_URL}/buy_ticket"

DB_URL = os.getenv(
    "DATABASE_URL", "sqlite:///inventory.db?check_same_thread=False"
)

engine = create_engine(DB_URL, future=True)
metadata = MetaData()
inventory_tbl = Table("inventory", metadata, autoload_with=engine)
purchase_tbl = Table("purchase_record", metadata, autoload_with=engine)


def worker(request_id: int, results: dict):
    """Each worker fires ONE request and stores the HTTP status."""
    payload = {"item_name": "Item A"}
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=5)
        results[request_id] = r.status_code
        #debug print
        print(f"Request {request_id} -> {r.status_code}")
    except Exception as exc:
        results[request_id] = f"error:{type(exc).__name__}"
        print(f"Request {request_id} -> error: {type(exc).__name__}")


def run_load_test(total_requests: int = 1000, batch_size: int = 50):
    manager = multiprocessing.Manager()
    results = manager.dict()

    processes = [
        multiprocessing.Process(target=worker, args=(i, results))
        for i in range(total_requests)
    ]

    # Start them in batches so we don’t exceed OS limits
    for i in range(0, total_requests, batch_size):
        batch = processes[i : i + batch_size]
        print(f"Starting batch {i // batch_size + 1} / {total_requests // batch_size} ...")
        for p in batch:
            p.start()
        for p in batch:
            p.join()

    # Statistics
    counter = Counter(results.values())
    ok = counter.get(200, 0)
    gone = counter.get(410, 0)
    other = sum(v for k, v in counter.items() if k not in (200, 410))

    print("\nLoad test finished")
    print(f"Total requests sent : {total_requests}")
    print(f"200 OK (purchased)   : {ok}")
    print(f"410 GONE (sold out)  : {gone}")
    print(f"Other responses      : {other}")
    print("Full breakdown:", dict(counter))

    # Verify DB state
    with engine.begin() as conn:
        stock = conn.execute(select(inventory_tbl.c.stock)).scalar_one()
        purchase_cnt = conn.execute(select(purchase_tbl.c.id)).fetchall()
        purchase_cnt = len(purchase_cnt)

    print("\n=== DB verification ===")
    print(f"Inventory.stock   : {stock}")
    print(f"Purchase records  : {purchase_cnt}")

    assert stock == 0, f"Inventory not zero! ({stock})"
    assert purchase_cnt == 100, f"Expected 100 purchases, got {purchase_cnt}"
    assert ok == 100, f"Expected exactly 100 successful 200 responses, got {ok}"
    assert gone == total_requests - 100, "All remaining requests should be 410"

    print("\n All assertions passed – the SQLite implementation is strictly consistent!")


if __name__ == "__main__":
    # Feel free to change the numbers to stress it more
    run_load_test(total_requests=1000, batch_size=50)