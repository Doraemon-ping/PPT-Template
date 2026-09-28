CREATE TABLE IF NOT EXISTS api_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    system_name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    auth_type TEXT NOT NULL DEFAULT 'none'
        CHECK (auth_type IN ('none', 'bearer', 'basic', 'api_key')),
    auth_config TEXT NOT NULL DEFAULT '{}',
    timeout REAL NOT NULL DEFAULT 30 CHECK (timeout > 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_connections_status
    ON api_connections(status);

CREATE TABLE IF NOT EXISTS api_endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL REFERENCES api_connections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('GET', 'POST')),
    headers TEXT NOT NULL DEFAULT '{}',
    query_params TEXT NOT NULL DEFAULT '{}',
    body_template TEXT,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(connection_id, name)
);

CREATE INDEX IF NOT EXISTS idx_api_endpoints_connection
    ON api_endpoints(connection_id);

CREATE TABLE IF NOT EXISTS api_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    location TEXT NOT NULL CHECK (location IN ('path', 'query', 'header', 'body')),
    source_type TEXT NOT NULL CHECK (source_type IN ('fixed', 'input', 'context')),
    source_key TEXT,
    default_value TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(endpoint_id, name, location)
);

CREATE INDEX IF NOT EXISTS idx_api_parameters_endpoint
    ON api_parameters(endpoint_id);

CREATE TABLE IF NOT EXISTS field_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    target_field TEXT NOT NULL,
    transform_type TEXT NOT NULL DEFAULT 'none'
        CHECK (transform_type IN ('none', 'enum')),
    transform_config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(endpoint_id, target_field)
);

CREATE INDEX IF NOT EXISTS idx_field_mappings_endpoint
    ON field_mappings(endpoint_id);

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_datasets_source_created
    ON datasets(source, created_at DESC);
