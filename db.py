import sqlite3
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from config import settings
from models import ReplyJob

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_reply_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tid INTEGER NOT NULL,
    fid INTEGER NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'reply',
    source_pid INTEGER,
    source_authorid INTEGER,
    source_subject TEXT DEFAULT '',
    source_message TEXT,
    reply_message TEXT NOT NULL,
    bot_pid INTEGER,
    parent_job_id INTEGER,
    status INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

_CREATE_INDEX_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_source_pid ON bot_reply_jobs(source_pid);",
    "CREATE INDEX IF NOT EXISTS idx_status_created ON bot_reply_jobs(status, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_tid ON bot_reply_jobs(tid);",
    "CREATE INDEX IF NOT EXISTS idx_tid_jobtype ON bot_reply_jobs(tid, job_type);",
]

_ALTER_TABLE_SQL = [
    "ALTER TABLE bot_reply_jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'reply';",
    "ALTER TABLE bot_reply_jobs ADD COLUMN bot_pid INTEGER;",
    "ALTER TABLE bot_reply_jobs ADD COLUMN parent_job_id INTEGER;",
]


class Database:
    def __init__(self) -> None:
        db_path = Path(settings.DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(db_path),
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(_CREATE_TABLE_SQL)
        for sql in _ALTER_TABLE_SQL:
            try:
                self._conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        for sql in _CREATE_INDEX_SQL:
            try:
                self._conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        logger.info("SQLite database ready at {}", db_path)

    @staticmethod
    def _now() -> int:
        return int(time.time())

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore

    def fetch_next_job(self) -> Optional[ReplyJob]:
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM bot_reply_jobs "
            "WHERE status IN (0, 3) AND retry_count < ? "
            "ORDER BY status ASC, created_at ASC "
            "LIMIT 1",
            (settings.MAX_RETRY_COUNT,),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        return ReplyJob.from_dict(dict(row))

    def mark_processing(self, job_id: int) -> None:
        conn = self._conn
        conn.execute(
            "UPDATE bot_reply_jobs SET status = 1, updated_at = ? WHERE id = ?",
            (self._now(), job_id),
        )
        conn.commit()

    def mark_sent(self, job_id: int, bot_pid: Optional[int] = None) -> None:
        conn = self._conn
        if bot_pid is not None:
            conn.execute(
                "UPDATE bot_reply_jobs SET status = 2, bot_pid = ?, updated_at = ? WHERE id = ?",
                (bot_pid, self._now(), job_id),
            )
        else:
            conn.execute(
                "UPDATE bot_reply_jobs SET status = 2, updated_at = ? WHERE id = ?",
                (self._now(), job_id),
            )
        conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        conn = self._conn
        conn.execute(
            "UPDATE bot_reply_jobs "
            "SET status = CASE WHEN retry_count + 1 >= ? THEN 4 ELSE 3 END, "
            "retry_count = retry_count + 1, "
            "last_error = ?, "
            "updated_at = ? "
            "WHERE id = ?",
            (settings.MAX_RETRY_COUNT, error, self._now(), job_id),
        )
        conn.commit()

    def insert_job(
        self,
        tid: int,
        fid: int,
        job_type: str,
        source_pid: Optional[int],
        source_authorid: Optional[int],
        source_subject: str,
        source_message: Optional[str],
        reply_message: str,
        parent_job_id: Optional[int] = None,
    ) -> int:
        conn = self._conn
        now = self._now()
        cursor = conn.execute(
            "INSERT INTO bot_reply_jobs "
            "(tid, fid, job_type, source_pid, source_authorid, source_subject, "
            "source_message, reply_message, parent_job_id, status, retry_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
            (
                tid, fid, job_type, source_pid, source_authorid,
                source_subject, source_message, reply_message,
                parent_job_id, now, now,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def has_reply_job(self, tid: int, job_type: str = "reply") -> bool:
        conn = self._conn
        row = conn.execute(
            "SELECT 1 FROM bot_reply_jobs WHERE tid = ? AND job_type = ? LIMIT 1",
            (tid, job_type),
        ).fetchone()
        return row is not None

    def get_completed_jobs(self, job_type: str = "reply") -> list[ReplyJob]:
        conn = self._conn
        rows = conn.execute(
            "SELECT * FROM bot_reply_jobs "
            "WHERE status = 2 AND job_type = ? "
            "AND bot_pid IS NOT NULL "
            "ORDER BY updated_at DESC",
            (job_type,),
        ).fetchall()
        return [ReplyJob.from_dict(dict(r)) for r in rows]

    def get_already_replied_tids(self, fid: int) -> set[int]:
        conn = self._conn
        rows = conn.execute(
            "SELECT DISTINCT tid FROM bot_reply_jobs WHERE fid = ?",
            (fid,),
        ).fetchall()
        return {r["tid"] for r in rows}

    def has_quote_reply(self, tid: int, source_pid: int) -> bool:
        conn = self._conn
        row = conn.execute(
            "SELECT 1 FROM bot_reply_jobs "
            "WHERE tid = ? AND job_type = 'quote_reply' AND source_pid = ? LIMIT 1",
            (tid, source_pid),
        ).fetchone()
        return row is not None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()
