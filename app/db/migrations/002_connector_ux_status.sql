CREATE TABLE IF NOT EXISTS connector_source_status (
    connection_id INTEGER PRIMARY KEY REFERENCES api_connections(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'not_tested'
        CHECK (status IN ('not_tested', 'normal', 'failed')),
    reason_code TEXT,
    reason_message TEXT,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_used_at TEXT,
    record_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_connector_source_status_recent
    ON connector_source_status(last_used_at DESC);
