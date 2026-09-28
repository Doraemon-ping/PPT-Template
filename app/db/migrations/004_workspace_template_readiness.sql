ALTER TABLE workspace_templates ADD COLUMN placeholder_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workspace_templates ADD COLUMN binding_target_count INTEGER NOT NULL DEFAULT 0;

