CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_sources (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    connection_id INTEGER NOT NULL UNIQUE REFERENCES api_connections(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, connection_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_sources_workspace
    ON workspace_sources(workspace_id);

CREATE TABLE IF NOT EXISTS workspace_templates (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    slide_count INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_templates_workspace
    ON workspace_templates(workspace_id);
