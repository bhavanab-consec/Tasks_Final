
# Firehose Collector – Architecture Overview

## Steps to Run

1. **Create and activate the virtual environment**
   ```powershell
   .\.venv\Scripts\Activate.ps1
````

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Start the FastAPI server**

   ```bash
   uvicorn main:app --host 127.0.0.1 --port 8000 --log-level info
   ```

4. **Open API documentation**

   * Visit: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

5. **Load testing (1,000+ concurrent requests)**

   * Open a new terminal and run:

     ```bash
     python load_test.py
     ```

6. **Test resilience (simulate database outage)**

   * Open another terminal and run:

     ```powershell
     Invoke-WebRequest -Uri "http://127.0.0.1:8000/simulate_outage" -Method POST
     ```

---

## 1. Overview

The **Firehose Collector** is a high-throughput event ingestion service designed to handle clickstream events from millions of client devices.
The system ensures:

* **Non-blocking writes**
* **Batched inserts**
* **Resilience to temporary database outages**

---

## 2. Components

### API Layer (`main.py`)

* Exposes a single HTTP endpoint: `POST /event`

* Accepts JSON payload:

  ```json
  {
    "user_id": 123,
    "timestamp": "2026-01-12T16:00:00Z",
    "metadata": {
      "action": "click",
      "page": "/home"
    }
  }
  ```

* Responds immediately with **HTTP 202 Accepted**

* Does **not wait** for database writes to complete

---

### Buffering Layer (In-Memory Queue)

* Incoming events are pushed into an **asynchronous in-memory queue**

  * Implemented using `asyncio.Queue` or a Python list
* Events are **batched** (e.g., 100 events per batch)
* Reduces database contention and improves throughput
* Enables non-blocking request handling

---

### Database Layer (`db.py`)

* Uses **batched inserts** via `executemany`
* Stores events in SQLite
* Parameterized queries ensure:

  * Safe handling of arbitrary JSON
  * Protection against SQL injection
* Gracefully handles temporary database outages:

  * Writes pause during outage
  * Automatically resume once DB is available

---

### Resilience

* API continues accepting requests even when the database is unavailable
* Buffered events are safely retained in memory
* Once the database recovers, buffered events are flushed automatically
* No event loss during temporary downtime

---

### Load Handling

* `load_test.py` simulates **1,000+ concurrent clients**
* Throughput scales based on:

  * Batch size
  * Database performance
* Demonstrates stability under high load

---

## 3. Architecture Diagram

```
            +-------------------+
            |   Client Devices  |
            +-------------------+
                     |
                     v
            +-------------------+
            |     API Layer     |  <-- POST /event (HTTP 202 immediately)
            +-------------------+
                     |
                     v
            +-------------------+
            |  In-Memory Queue  |  <-- Buffers events, batches for DB
            +-------------------+
                     |
                     v
            +-------------------+
            |   Database (SQL)  |  <-- Batched inserts, resilient to downtime
            +-------------------+
```

---

## 4. Notes

* The in-memory queue acts as a **buffer** between high-frequency clients and the database
* Batching significantly reduces database write overhead
* The system is:

  * **Highly resilient**
  * **Non-blocking**
  * Well-suited for **high-traffic analytics pipelines**

---

