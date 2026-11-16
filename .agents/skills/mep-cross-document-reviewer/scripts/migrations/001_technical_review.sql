-- Additive technical schema; existing core/registry/equipment versions are untouched.
CREATE TABLE tr_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE tr_imports(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), file_id TEXT NOT NULL,
 version_id TEXT NOT NULL REFERENCES versions(id), analysis_id TEXT NOT NULL REFERENCES registry_analyses(id),
 slot TEXT NOT NULL, manifest_json TEXT NOT NULL, coverage_json TEXT NOT NULL, issues_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,file_id) REFERENCES registry_files(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_requirements(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, import_id TEXT NOT NULL, core_record_id TEXT REFERENCES records(id),
 original_text TEXT NOT NULL, source_json TEXT NOT NULL, context_json TEXT NOT NULL,
 classification_json TEXT NOT NULL, interpretations_json TEXT NOT NULL, reference_status TEXT NOT NULL,
 created_at TEXT NOT NULL, FOREIGN KEY(project_id,import_id) REFERENCES tr_imports(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_interpretations(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, requirement_id TEXT NOT NULL, payload_json TEXT NOT NULL,
 method TEXT NOT NULL, review_id TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,requirement_id) REFERENCES tr_requirements(project_id,id),
 FOREIGN KEY(project_id,review_id) REFERENCES eq_reviews(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_links(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, entity_id TEXT NOT NULL, requirement_id TEXT NOT NULL,
 basis_hash TEXT NOT NULL, level TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id),
 FOREIGN KEY(project_id,requirement_id) REFERENCES tr_requirements(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_mapping_runs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), basis_hash TEXT NOT NULL,
 manifest_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE tr_runs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), basis_hash TEXT NOT NULL,
 foundation_hash TEXT NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE tr_comparisons(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 parameter TEXT, outcome TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,run_id) REFERENCES tr_runs(project_id,id),
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_cases(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, entity_id TEXT NOT NULL,
 case_key TEXT NOT NULL, type TEXT NOT NULL, initial_status TEXT NOT NULL, confirmable INTEGER NOT NULL CHECK(confirmable IN(0,1)),
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,run_id) REFERENCES tr_runs(project_id,id),
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_coverage_scopes(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, entity_id TEXT NOT NULL, category TEXT NOT NULL,
 foundation_hash TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_results(
 run_id TEXT PRIMARY KEY REFERENCES tr_runs(id), summary_json TEXT NOT NULL, coverage_json TEXT NOT NULL, finished_at TEXT NOT NULL);
CREATE TABLE tr_approved_values(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, entity_id TEXT NOT NULL, parameter_id TEXT,
 requirement_id TEXT, interpretation_id TEXT, review_id TEXT NOT NULL, basis_hash TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id),
 FOREIGN KEY(project_id,parameter_id) REFERENCES eq_parameters(project_id,id),
 FOREIGN KEY(project_id,requirement_id) REFERENCES tr_requirements(project_id,id),
 FOREIGN KEY(project_id,interpretation_id) REFERENCES tr_interpretations(project_id,id),
 FOREIGN KEY(project_id,review_id) REFERENCES eq_reviews(project_id,id), UNIQUE(project_id,id));
CREATE TABLE tr_decision_evidence(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, review_id TEXT NOT NULL, references_json TEXT NOT NULL,
 previous_status_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,review_id) REFERENCES eq_reviews(project_id,id), UNIQUE(project_id,review_id));
CREATE VIRTUAL TABLE tr_fts USING fts5(project_id UNINDEXED, requirement_id UNINDEXED, text);
CREATE INDEX tr_requirement_import ON tr_requirements(import_id);
CREATE INDEX tr_import_file ON tr_imports(project_id,file_id,slot);
CREATE INDEX tr_link_entity ON tr_links(project_id,entity_id,basis_hash);
CREATE INDEX tr_link_requirement ON tr_links(requirement_id);
CREATE INDEX tr_cases_entity ON tr_cases(project_id,entity_id,case_key);
CREATE INDEX tr_comparison_entity ON tr_comparisons(project_id,entity_id,parameter);
CREATE INDEX tr_approved_entity ON tr_approved_values(project_id,entity_id);
CREATE INDEX tr_interpretation_requirement ON tr_interpretations(requirement_id);
