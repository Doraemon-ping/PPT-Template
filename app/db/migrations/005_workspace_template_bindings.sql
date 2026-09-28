CREATE TABLE IF NOT EXISTS workspace_template_bindings (
    workspace_id INTEGER NOT NULL,
    template_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    binding_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, template_id),
    FOREIGN KEY (workspace_id, template_id)
        REFERENCES workspace_templates(workspace_id, template_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workspace_template_bindings_workspace
    ON workspace_template_bindings(workspace_id);
