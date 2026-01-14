import asyncio
import random
import string
import time
from datetime import datetime, timezone

import httpx

TARGET_URL = "http://127.0.0.1:8000/event"
CONCURRENCY = 1000          # total number of parallel requests
PAYLOAD_SIZE = 256          # bytes of random metadata per event


def random_metadata() -> dict:
    """Generate a random nested dict of roughly PAYLOAD_SIZE bytes."""
    # simple flat dict – you can make it deeper if you like
    return {
        "data": "".join(random.choices(string.ascii_letters + string.digits, k=PAYLOAD_SIZE))
    }




semaphore = asyncio.Semaphore(200)  # limit to 200 in-flight requests

async def fire_one(client: httpx.AsyncClient, idx: int):
    payload = {
        "user_id": random.randint(1, 1_000_000),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": random_metadata(),
    }
    async with semaphore:
        try:
            resp = await client.post(TARGET_URL, json=payload, timeout=15.0)
            return resp.status_code
        except Exception as exc:
            print(f"Request {idx} failed: {exc}")
            return None



async def main():
    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [fire_one(client, i) for i in range(CONCURRENCY)]
        results = await asyncio.gather(*tasks)
    duration = time.perf_counter() - start

    success = sum(1 for r in results if r == 202)
    failure = sum(1 for r in results if r != 202)
    print("\nLOAD TEST RESULT")
    print(f"Total requests sent:   {CONCURRENCY}")
    print(f"Successful (202):      {success}")
    print(f"Failed / other codes:  {failure}")
    print(f"Elapsed time:          {duration:.2f}s")
    print(f"Requests per second:   {CONCURRENCY/duration:.1f}")

if __name__ == "__main__":
    asyncio.run(main())