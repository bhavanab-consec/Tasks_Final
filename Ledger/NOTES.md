
````md
# Legacy Ledger Refactoring Notes

## Steps to Run

1. **Activate the virtual environment**
```powershell
.\.venv\Scripts\Activate.ps1
````

2. **Install dependencies**

```bash
pip install -r requirements.txt
```

3. **Run the application**

```bash
python -m uvicorn legacy_ledger:app
```

4. **Open API documentation (optional)**

* Visit: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Context

We maintain a legacy internal service (`legacy_ledger.py`) used by support staff to:

* Search for users
* Process manual credit adjustments

### Issues Identified

1. **Security**

   * Automated scans flagged potential data leakage vulnerabilities

2. **Performance**

   * Application froze when multiple transactions were processed simultaneously

This refactoring addresses both issues while **preserving API compatibility** with the original service.

---

## 1. Security Hardening

### Vulnerability Found

* The original `/search` endpoint was vulnerable to **SQL injection**
* User input was directly embedded into SQL queries
* Risk: Unauthorized data access or manipulation

### Fix Implemented

* Replaced raw SQL with **parameterized queries**

```python
cursor.execute(
    "SELECT id, username, role FROM users WHERE username = ?",
    (q,)
)
```

* Added **Pydantic models** for request validation

  * Restricts `/transaction` inputs to valid numeric values

### Result

* API is resistant to SQL injection
* Only valid `user_id` and `amount` values are accepted

---

## 2. Performance Optimization

### Issue

* Original `/transaction` endpoint used blocking `time.sleep()`
* Caused the server to freeze during long-running operations

### Solution

* Converted transaction processing to **asynchronous background tasks**
* Used FastAPI `BackgroundTasks` with `asyncio.sleep()`

```python
async def _process_transaction(user_id: int, amount: float):
    await asyncio.sleep(3)  # simulate slow banking system
```

### Outcome

* Background tasks ensure **non-blocking behavior**
* API remains responsive under concurrent requests

### Evidence of Async Execution

* Logs show delayed execution after immediate response:

```text
[WARN] Transaction failed: user 99 not found
```

* API returns `200 OK` immediately, proving responsiveness

---

## 3. Data Integrity

* Transactions use **atomic database operations**

```python
conn.isolation_level = None
cursor.execute("BEGIN IMMEDIATE")
```

* Rollback occurs on failure or invalid user:

```python
if cursor.rowcount == 0:
    conn.rollback()
    print(f"[WARN] Transaction failed: user {user_id} not found")
```

### Guarantees

* No partial updates
* Consistent account balances
* Safe concurrent access

---

## 4. API Behavior

### `GET /search?q=<username>`

* `200 OK` → user exists
* `404 Not Found` → user does not exist
* Input is trimmed and validated to prevent empty queries

---

### `POST /transaction`

#### Request Payload

```json
{
  "user_id": 1,
  "amount": 25.0
}
```

#### Response

```json
{
  "status": "processed",
  "deducted": 25.0
}
```

* Returns `200 OK` immediately
* Deduction processed asynchronously
* Invalid `user_id` logs a warning without crashing the server

---

## 5. Optional Improvements / Observations

* `/search?q=<nonexistent>` currently returns `404`

  * Returning an empty list `[]` is also a valid design choice
* Logging in `_process_transaction` confirms async execution
* Could enhance logging with:

  * Timestamps
  * User IDs
  * Transaction IDs (for auditing)

---

## 6. Technical Decisions

| Requirement               | Decision                              |
| ------------------------- | ------------------------------------- |
| SQL injection prevention  | Parameterized queries (`?`)           |
| Non-blocking transactions | FastAPI `BackgroundTasks` + `asyncio` |
| Atomic DB updates         | `BEGIN IMMEDIATE` + commit/rollback   |
| Input validation          | Pydantic models (`gt=0` constraints)  |
| Framework                 | FastAPI (replacing legacy Flask)      |
| Database                  | SQLite3 (assessment constraint)       |

---

## 7. Testing & Validation

| Scenario                          | Result                           |
| --------------------------------- | -------------------------------- |
| GET existing user (`alice`)       | `200 OK`, user info returned     |
| GET non-existing user (`notreal`) | `404 Not Found`                  |
| POST valid transaction            | `200 OK`, async deduction logged |
| POST invalid user                 | `200 OK`, warning logged         |
| POST invalid payload              | `422 Unprocessable Entity`       |

### Observations

* API remains responsive under concurrent load
* Async transactions do not block new requests

---

## Conclusion

* Security vulnerabilities resolved (SQL injection hardened)
* Performance improved via asynchronous background processing
* Data integrity preserved with atomic transactions
* API compatibility with legacy service maintained

```
