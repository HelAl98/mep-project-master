-- Additive migration only. Core user_version=2 and registry migration=1 stay unchanged.
CREATE TABLE eq_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE eq_categories(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), name TEXT NOT NULL,
 config_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE eq_imports(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id),
 file_id TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES versions(id), analysis_id TEXT NOT NULL REFERENCES registry_analyses(id),
 slot TEXT NOT NULL, signature TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL,
 manifest_json TEXT NOT NULL, issues_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,file_id) REFERENCES registry_files(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_occurrences(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), import_id TEXT NOT NULL,
 sheet_id TEXT REFERENCES registry_document_sheets(id), core_record_id TEXT REFERENCES records(id),
 original_tag TEXT, normalized_tag TEXT, category_id TEXT, identity_kind TEXT NOT NULL,
 source_json TEXT NOT NULL, raw_json TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,import_id) REFERENCES eq_imports(project_id,id),
 FOREIGN KEY(project_id,category_id) REFERENCES eq_categories(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_parameters(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), occurrence_id TEXT NOT NULL,
 name TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,occurrence_id) REFERENCES eq_occurrences(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_entities(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id),
 kind TEXT NOT NULL CHECK(kind IN ('instance','type','group')), basis_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE eq_entity_sources(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, entity_id TEXT NOT NULL, occurrence_id TEXT NOT NULL,
 FOREIGN KEY(project_id,entity_id) REFERENCES eq_entities(project_id,id),
 FOREIGN KEY(project_id,occurrence_id) REFERENCES eq_occurrences(project_id,id), UNIQUE(entity_id,occurrence_id));
CREATE TABLE eq_runs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id),
 basis_hash TEXT NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE eq_results(
 run_id TEXT PRIMARY KEY REFERENCES eq_runs(id), status TEXT NOT NULL, counters_json TEXT NOT NULL, finished_at TEXT NOT NULL);
CREATE TABLE eq_matches(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL,
 left_id TEXT NOT NULL, right_id TEXT NOT NULL, kind TEXT NOT NULL,
 proposed_status TEXT NOT NULL CHECK(proposed_status IN ('probable','possible')),
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, CHECK(left_id<>right_id),
 FOREIGN KEY(project_id,run_id) REFERENCES eq_runs(project_id,id),
 FOREIGN KEY(project_id,left_id) REFERENCES eq_occurrences(project_id,id),
 FOREIGN KEY(project_id,right_id) REFERENCES eq_occurrences(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_relationships(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL,
 occurrence_id TEXT NOT NULL, target_occurrence_id TEXT NOT NULL, kind TEXT NOT NULL,
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,run_id) REFERENCES eq_runs(project_id,id),
 FOREIGN KEY(project_id,occurrence_id) REFERENCES eq_occurrences(project_id,id),
 FOREIGN KEY(project_id,target_occurrence_id) REFERENCES eq_occurrences(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_issues(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, code TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('potential_discrepancy','missing_evidence','unprocessed_source','not_applicable')),
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,run_id) REFERENCES eq_runs(project_id,id), UNIQUE(project_id,id));
CREATE TABLE eq_reviews(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id),
 target_kind TEXT NOT NULL, target_id TEXT NOT NULL, decision TEXT NOT NULL,
 actor TEXT NOT NULL CHECK(length(trim(actor))>0), reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 value_json TEXT, basis_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE VIRTUAL TABLE eq_fts USING fts5(project_id UNINDEXED, occurrence_id UNINDEXED, text);
CREATE INDEX eq_import_file_slot ON eq_imports(project_id,file_id,slot);
CREATE INDEX eq_occurrence_tag ON eq_occurrences(project_id,normalized_tag);
CREATE INDEX eq_occurrence_import ON eq_occurrences(import_id);
CREATE INDEX eq_parameter_occurrence ON eq_parameters(occurrence_id,name);
CREATE INDEX eq_review_target ON eq_reviews(project_id,target_kind,target_id);
CREATE INDEX eq_runs_project ON eq_runs(project_id,created_at);
