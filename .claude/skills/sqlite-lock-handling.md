# SQLite Concurrent-Write Lock Handling

## Problem
When two Python processes write to the same SQLite file simultaneously, the slower
one raises `sqlite3.OperationalError: database is locked`. Default SQLite timeout
is effectively 0 — it raises immediately rather than waiting.

## Solution (3 layers)

### 1. WAL mode + busy_timeout on the connection
```python
conn = sqlite3.connect("mydb.db", timeout=60)          # Python-level: poll for 60s
conn.execute("PRAGMA journal_mode=WAL")                # WAL = concurrent reads + 1 writer
conn.execute("PRAGMA busy_timeout=60000")              # SQLite C-level: wait 60s (ms units)
```
WAL mode is safe to set on a live database; it persists in the db file.
The two timeout settings complement each other — set both.

### 2. Retry wrapper with exponential backoff
```python
def _db_retry(fn, *args, retries=8, base_delay=1.0):
    """Retry SQLite call on 'database is locked' with exponential backoff.
    Waits 1, 2, 4, 8, 16, 32, 64, 128 s before final raise (~4 min total).
    """
    import time, sqlite3
    for attempt in range(retries):
        try:
            return fn(*args)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc) or attempt == retries - 1:
                raise
            wait = base_delay * (2 ** attempt)
            print(f"DB locked — retry {attempt+1}/{retries} in {wait:.0f}s")
            time.sleep(wait)
```

### 3. Wrap write calls
```python
# Instead of:
cur.execute("UPDATE tenders SET x=? WHERE id=?", (val, tid))
conn.commit()

# Use:
_db_retry(cur.execute, "UPDATE tenders SET x=? WHERE id=?", (val, tid))
_db_retry(conn.commit)
```

## Applied in this project
- `scrapers/enrich_nic.py` — `_db_retry` function + WAL/timeout PRAGMAs at function start
- `cli.py` — `sqlite3.connect(DB_PATH, timeout=60)` for the `--enrich-nic` path

## Why this matters
Running two enricher jobs in parallel (e.g. fresh portals + ETUP retry) hit this
bug. With busy_timeout=60000, SQLite waits up to 60s for the lock to clear. The
exponential-backoff retry adds a second safety net for extreme lock contention.
