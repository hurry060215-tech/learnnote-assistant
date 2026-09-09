"""Local provider-reported usage ledger; never stores prompts or credentials."""
from datetime import datetime, timezone
from contextlib import contextmanager
import logging
import sqlite3
import time
from urllib.parse import urlsplit

from .config import DATA_DIR


@contextmanager
def _db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "token-usage.sqlite3", timeout=5)
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS usage (at TEXT, model TEXT, host TEXT, purpose TEXT, status TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, elapsed_ms INTEGER)")
            yield db
    finally:
        db.close()


def record_usage(client, model, purpose, usage, started, status="success"):
    def count(name):
        value = getattr(usage, name, None)
        return value if type(value) is int and value >= 0 else None
    try:
        with _db() as db:
            db.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)", (
                datetime.now(timezone.utc).isoformat(), str(model)[:256],
                urlsplit(str(getattr(client, "base_url", ""))).hostname or "unknown",
                purpose, status, count("prompt_tokens"), count("completion_tokens"),
                count("total_tokens"), round((time.monotonic() - started) * 1000)))
    except Exception:
        logging.getLogger(__name__).warning("Token usage could not be saved")


def tracked_completion(client, *, purpose="note", **kwargs):
    started = time.monotonic()
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception:
        record_usage(client, kwargs.get("model", ""), purpose, None, started, "failed")
        raise
    record_usage(client, kwargs.get("model", ""), purpose, getattr(response, "usage", None), started)
    return response


def usage_report():
    with _db() as db:
        db.row_factory = sqlite3.Row
        totals = dict(db.execute("SELECT COUNT(*) requests, COUNT(total_tokens) measured_requests, COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens, COALESCE(SUM(total_tokens),0) total_tokens FROM usage").fetchone())
        recent = [dict(row) for row in db.execute("SELECT * FROM usage ORDER BY rowid DESC LIMIT 100")]
        groups = [dict(row) for row in db.execute("SELECT host, model, COUNT(*) requests, COUNT(total_tokens) measured_requests, COALESCE(SUM(total_tokens),0) total_tokens FROM usage GROUP BY host, model")]
        daily = [dict(row) for row in db.execute("SELECT substr(at,1,10) day, COUNT(*) requests, COUNT(total_tokens) measured_requests, COALESCE(SUM(total_tokens),0) total_tokens FROM usage WHERE date(at) >= date('now','-13 days') GROUP BY day ORDER BY day")]
    return {"totals": totals, "recent": recent, "models": groups, "daily": daily}
