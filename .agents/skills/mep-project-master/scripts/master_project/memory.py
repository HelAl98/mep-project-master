"""Add only master_* tables to the SAME established engineering database."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import uuid
from .common import HOME, encoded, key, now, read, write


def connect(cfg, writable=False):
    path = Path(cfg["database"]).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if not writable:
            conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ValueError("Requires the existing MEP core schema 2")
        row = conn.execute("SELECT * FROM registry_projects WHERE id=?", (cfg["project_id"],)).fetchone()
        if not row or Path(row["root_path"]).resolve() != Path(cfg["source_directory"]):
            raise ValueError("Project ID/source directory do not match the document registry")
        return conn
    except BaseException:
        conn.close()
        raise


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class Memory:
    def __init__(self, cfg, writable=False):
        self.cfg, self.conn, self.writable = cfg, connect(cfg, writable), writable
        if writable:
            if "master_schema" in tables(self.conn) and [r[0] for r in self.conn.execute("SELECT version FROM master_schema")] != [1]:
                self.close()
                raise ValueError("Unsupported master schema; no automatic upgrade")
            # This migration is authored only. It is first applied on a later authorized run.
            self.conn.executescript((HOME / "scripts/master_project/schema.sql").read_text(encoding="utf-8"))
            self.conn.execute("INSERT OR IGNORE INTO master_project_configs VALUES(?,?,?,?,?)",
                              (key(cfg), cfg["project_id"], cfg["scope"]["id"], encoded(cfg), now()))
            for stage in read(HOME / "assets/config/workflow.json"):
                if not self.conn.execute("SELECT 1 FROM master_events WHERE project_id=? AND scope_id=? AND stage=?",
                                         (cfg["project_id"], cfg["scope"]["id"], stage["id"])).fetchone():
                    self.conn.execute("INSERT INTO master_events VALUES(?,?,?,?,?,?,?,?,?)",
                                      (uuid.uuid4().hex, cfg["project_id"], cfg["scope"]["id"], stage["id"], None,
                                       "PENDING", key([cfg["scope"], stage["id"]]), encoded({"dependencies": stage["dependencies"]}), now()))
            self.conn.commit()

    def close(self):
        self.conn.close()

    def event(self, stage, status, fingerprint, payload, job_id=None):
        if not self.writable:
            raise ValueError("Read-only project memory")
        if status not in ("PENDING", "RUNNING", "COMPLETED", "BLOCKED", "FAILED", "STALE"):
            raise ValueError("Unknown workflow status")
        event = uuid.uuid4().hex
        with self.conn:
            self.conn.execute("INSERT INTO master_events VALUES(?,?,?,?,?,?,?,?,?)",
                              (event, self.cfg["project_id"], self.cfg["scope"]["id"], stage, job_id, status,
                               fingerprint, encoded(payload), now()))
        return event

    def events(self, stage=None, job_id=None):
        if "master_events" not in tables(self.conn):
            return []
        sql = "SELECT rowid AS sequence,* FROM master_events WHERE project_id=? AND scope_id=?"
        args = [self.cfg["project_id"], self.cfg["scope"]["id"]]
        if stage:
            sql += " AND stage=?"; args.append(stage)
        if job_id:
            sql += " AND job_id=?"; args.append(job_id)
        rows = []
        for row in self.conn.execute(sql + " ORDER BY rowid", args):
            row = dict(row); row["payload"] = __import__("json").loads(row.pop("payload_json")); rows.append(row)
        return rows

    def latest(self, stage, job_id=None):
        rows = [r for r in self.events(stage, job_id) if (r["job_id"] is not None if job_id else r["job_id"] is None)]
        return rows[-1] if rows else None

    def cache(self, stage, job_id, fingerprint):
        # Old failed/stale attempts do not erase immutable successful artifacts.
        rows = [r for r in self.events(stage, job_id) if r["status"] == "COMPLETED" and r["fingerprint"] == fingerprint]
        return rows[-1] if rows else None

    def persist_packages(self, manifests):
        with self.conn:
            for item in manifests:
                identity = key(item)
                self.conn.execute("INSERT OR IGNORE INTO master_packages VALUES(?,?,?,?,?)",
                                  (identity, self.cfg["project_id"], self.cfg["scope"]["id"], encoded(item), now()))


@contextmanager
def project_lock(cfg):
    # Cross-process lock spans child CLIs, but never holds SQLite write locks over them.
    path = Path(cfg["database"]).with_suffix(Path(cfg["database"]).suffix + ".master.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    write(path, {"token": token, "pid": os.getpid(), "project_id": cfg["project_id"], "created_at": now()})
    try:
        yield
    finally:
        if path.is_file() and read(path).get("token") == token:
            path.unlink()
