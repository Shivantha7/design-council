"""Job table (SQLite) and per-job event logs. Plain SQL, one lock, no ORM.

Events are appended to runs_live/_jobs/<job_id>/events.jsonl as they happen. An event's
id is its line number, so a client that reconnects with Last-Event-ID resumes exactly
where it left off.
"""

import json
import sqlite3
import threading
from pathlib import Path

from design_council.run_logging import utc_now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    created_utc TEXT NOT NULL,
    status TEXT NOT NULL,              -- queued | running | succeeded | failed | interrupted
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    conditions TEXT NOT NULL,          -- JSON list
    profile TEXT NOT NULL,
    encoding TEXT NOT NULL,            -- JSON
    run_ids TEXT NOT NULL DEFAULT '{}',-- JSON {condition: run_id}
    estimate_usd REAL NOT NULL,
    cost_usd REAL,
    error TEXT,
    finished_utc TEXT
)
"""


class Store:
    def __init__(self, db_path: Path, jobs_root: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root = jobs_root
        self.lock = threading.Lock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute(SCHEMA)
            # A job left running by a previous process cannot be resumed mid-run.
            self.db.execute("UPDATE jobs SET status='interrupted', error='service restarted during the run', "
                            "finished_utc=? WHERE status IN ('queued','running')", (utc_now_iso(),))
            self.db.commit()

    def create(self, job_id, workflow_id, workflow_name, conditions, profile, encoding_json, estimate_usd):
        with self.lock:
            self.db.execute(
                "INSERT INTO jobs (job_id, created_utc, status, workflow_id, workflow_name, conditions, profile, "
                "encoding, estimate_usd) VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, utc_now_iso(), "queued", workflow_id, workflow_name, json.dumps(conditions), profile,
                 encoding_json, estimate_usd))
            self.db.commit()
        (self.jobs_root / job_id).mkdir(parents=True, exist_ok=True)

    def update(self, job_id, **fields):
        if "run_ids" in fields:
            fields["run_ids"] = json.dumps(fields["run_ids"])
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.db.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))
            self.db.commit()

    def get(self, job_id) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list_jobs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM jobs ORDER BY created_utc DESC").fetchall()
        return [self._row(r) for r in rows]

    def spent_today(self, today_prefix: str) -> float:
        """Spend committed today: actual cost of finished jobs, the estimate for unfinished ones."""
        with self.lock:
            rows = self.db.execute("SELECT cost_usd, estimate_usd FROM jobs WHERE created_utc LIKE ?",
                                   (today_prefix + "%",)).fetchall()
        return sum(r["cost_usd"] if r["cost_usd"] is not None else r["estimate_usd"] for r in rows)

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        d["conditions"] = json.loads(d["conditions"])
        d["run_ids"] = json.loads(d["run_ids"])
        return d

    # --- events ---------------------------------------------------------------

    def events_path(self, job_id) -> Path:
        return self.jobs_root / job_id / "events.jsonl"

    def emit(self, job_id, event: str, **data) -> None:
        record = {"event": event, "utc": utc_now_iso(), **data}
        with self.lock:
            with self.events_path(job_id).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
                handle.flush()

    def read_events(self, job_id, after: int = 0) -> list[tuple[int, dict]]:
        path = self.events_path(job_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [(i, json.loads(line)) for i, line in enumerate(lines, start=1) if i > after and line.strip()]
