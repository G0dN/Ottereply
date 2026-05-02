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

CREATE UNIQUE INDEX IF NOT EXISTS uniq_source_pid ON bot_reply_jobs(source_pid);
CREATE INDEX IF NOT EXISTS idx_status_created ON bot_reply_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tid ON bot_reply_jobs(tid);
CREATE INDEX IF NOT EXISTS idx_tid_jobtype ON bot_reply_jobs(tid, job_type);
