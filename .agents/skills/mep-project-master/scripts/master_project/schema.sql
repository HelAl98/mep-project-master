CREATE TABLE IF NOT EXISTS master_schema(version INTEGER PRIMARY KEY CHECK(version=1));
INSERT OR IGNORE INTO master_schema VALUES(1);
CREATE TABLE IF NOT EXISTS master_project_configs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), scope_id TEXT NOT NULL,
 configuration_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS master_events(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), scope_id TEXT NOT NULL,
 stage TEXT NOT NULL, job_id TEXT, status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETED','BLOCKED','FAILED','STALE')),
 fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS master_event_lookup ON master_events(project_id,scope_id,stage,job_id);
CREATE TABLE IF NOT EXISTS master_packages(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), scope_id TEXT NOT NULL,
 manifest_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS master_operator_events(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), scope_id TEXT NOT NULL,
 action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS master_events_no_update BEFORE UPDATE ON master_events BEGIN SELECT RAISE(ABORT,'Append-only workflow history'); END;
CREATE TRIGGER IF NOT EXISTS master_events_no_delete BEFORE DELETE ON master_events BEGIN SELECT RAISE(ABORT,'Append-only workflow history'); END;
CREATE TRIGGER IF NOT EXISTS master_events_no_replace BEFORE INSERT ON master_events WHEN EXISTS(SELECT 1 FROM master_events WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Immutable workflow event ID'); END;
CREATE TRIGGER IF NOT EXISTS master_packages_no_update BEFORE UPDATE ON master_packages BEGIN SELECT RAISE(ABORT,'Immutable package receipts'); END;
CREATE TRIGGER IF NOT EXISTS master_packages_no_delete BEFORE DELETE ON master_packages BEGIN SELECT RAISE(ABORT,'Immutable package receipts'); END;
CREATE TRIGGER IF NOT EXISTS master_operator_no_update BEFORE UPDATE ON master_operator_events BEGIN SELECT RAISE(ABORT,'Append-only operator history'); END;
CREATE TRIGGER IF NOT EXISTS master_operator_no_delete BEFORE DELETE ON master_operator_events BEGIN SELECT RAISE(ABORT,'Append-only operator history'); END;
CREATE TRIGGER IF NOT EXISTS master_config_no_update BEFORE UPDATE ON master_project_configs BEGIN SELECT RAISE(ABORT,'Immutable configuration history'); END;
CREATE TRIGGER IF NOT EXISTS master_config_no_delete BEFORE DELETE ON master_project_configs BEGIN SELECT RAISE(ABORT,'Immutable configuration history'); END;
