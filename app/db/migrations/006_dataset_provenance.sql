ALTER TABLE datasets ADD COLUMN connection_id INTEGER;
ALTER TABLE datasets ADD COLUMN endpoint_id INTEGER;
ALTER TABLE datasets ADD COLUMN parameters TEXT NOT NULL DEFAULT '{}';

UPDATE datasets
SET connection_id = (
    SELECT c.id FROM api_connections c
    WHERE c.system_name = datasets.source
    ORDER BY c.id LIMIT 1
)
WHERE connection_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_datasets_connection_created
    ON datasets(connection_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_endpoint_created
    ON datasets(endpoint_id, created_at DESC);
