# Configuration, tasks and coverage

Use `assets/config/project.example.json` as a configuration shape, not a project fixture. `init` fills paths and actual project identity without starting intake. Paths in config, task inputs and mapping/metadata options resolve relative to the master config file. Keep source immutable and database/output outside source directory. Windows paths with spaces are passed as argument-list elements, never interpolated into a shell.

## Project rules

The project name/ID, disciplines, equipment categories and named scope are persisted in `master_project_configs`. `registry_config` references the actual registry rules for document naming/revisions; `matching_config` references the matcher rules for tags/aliases/unit conventions/categories and quantities; `review_config` references reviewer rules for technical units/sections/applicability/coverage; `package_config` references formatting/grouping/readiness configuration. These are existing sibling interfaces, not a new parallel engineering rules engine. Read their actual references before editing. `quality_config` is passed to explicit QC tasks as `options.config` when needed. Categories/disciplines in master are declarative scope, not automatic source classification or approval.

`routing.<skill>.enabled=false` disables that route; it cannot replace a missing script. Stage `active=false` leaves the stage blocked if downstream work requires it. A genuinely irrelevant stage may have `skip_reason`, an empty job list and a complete explicit coverage declaration excluding only not-relevant/not-applicable sources. This records completion of the declared zero-work scope, not extraction or engineering approval. Unsupported DWG/OCR/partial sources cannot be hidden as successful processing: they require another supported source or a real, documented scope decision. Upstream engineering coverage gates still apply independently.

## Task contract

Every task has a unique safe `id` across the configuration scope and a routed `skill`. Executable tasks also name a supported logical `command`. Original instruction-only tasks use `kind: codex`; no Python subprocess tries to invoke Codex as an independent agent. Jobs execute in listed order, stages in the shipped DAG. `inputs` hold config-relative file paths or `@earlier-task-id`, meaning that task's persisted primary output. Reference tasks must precede their consumers. No arbitrary shell/script/SQL command is accepted.

Example configuration fragments below illustrate contracts only; the symbolic IDs and paths must be replaced with actual registered values. They were not executed or saved as project observations.

```json
{"id":"profile-schedules","kind":"codex","skill":"data-profiler","source_file_ids":["<actual-file-id>"],"inputs":["../sources/<actual-workbook>.xlsx"]}
```

For a PDF: stage 03 `pdf-to-structured` command `extract`, one source input and one exact `source_file_ids` ID; optionally `options.metadata` for actual document metadata. A drawing may feed `drawing-analyzer` command `analyze` with `inputs:["@native-pdf-task"]`. A specification's native PDF evidence feeds stage 04 `specification-extractor` command `extract`. Their logical command names are master adapter labels: the real scripts take positional input directly, without an invented extract/analyze subcommand.

Stage 03 CAD task: `dwg-to-excel`, `command: ingest`, one actual export XLSX input, `options.mapping` and optional `options.metadata`. This never converts DWG. `probe`/`verify` inspect presence/hash only and cannot fulfill drawing extraction coverage.

Stage 05: `etl-pipeline` `tabular` takes one XLSX/CSV and exact mapping/metadata; `ingest` takes one earlier `mep-evidence/1` artifact. Ingesting raw/native/specification/candidate views is explicit: do not automatically combine incompatible packages or lose their run IDs. `data-lineage-tracker` `inspect` takes `options.record` referencing an actual core record. Use command stdout's `run_id` when configuring the downstream SQL view.

```json
{"id":"equipment-schedule","skill":"mep-equipment-matcher","command":"import-schedule","source_file_ids":["<actual-file-id>"],"options":{"file-id":"<actual-file-id>","mapping":"schedule-map.json","role":"schedule","slot":"main"}}
```

Stage 06 supports matcher extract/import-schedule/import-cad/import-json/import-sql/match/group/export. Prefer `import-sql` with exact `run-id`, `file-id`, `role`, `slot` after stage 05. Intake requires one actual `options.file-id` matching exactly one declared source ID; implicit whole-project extraction is refused. `match` and `group --by type` use current shared records; they propose candidates, not approvals. Use `source_file_ids` covering all included source scope for these aggregate operations. Native extraction is available only when no reliable exact extraction exists; do not configure both paths for the same view.

Stage 07 `index` requires exact file-id and can use `options.mode: sql` with an existing `run-id`, avoiding duplicate parsing. Supported commands also include map/compare/export/export-approved. Index output stays unreviewed; interpret/review/accept-value are separate explicit actions. Native DOCX requirement intake supported by reviewer can be deferred to stage 07; stage 04's PDF-only scope must state that delegation and preserve DOCX visibility. Do not pretend PDF specification-extractor handles DOCX.

Stage 08 `data-quality-check` logical command `check` takes multiple supplied evidence artifacts and optional `options.config`. BMS/discipline mappings and comparable scopes must be explicit. The master adds a read-only SQLite integrity audit to the stage result, including malformed tags/locators, duplicate exact-source observations, unresolved unit status and incomplete requirement references. Historical findings are not automatically current engineering cases or approvals.

Stage 10 generator supports draft/approved/register/specifications/matrix/rfq, actual category/tag/entity selectors and mode for components. Output path, database, project ID, sibling-root and per-skill config flags are injected centrally. A task cannot redirect them. Stage 11 reuses existing package components or performs additional instruction-based document authoring/visual review only when requested. A document checkpoint must name `visual_review: completed` after actual built-in rendering/inspection. No sample rendering occurred during implementation.

## Coverage declaration

Every non-intake, non-approval stage needs `coverage`:

```json
{"actor":"<actual scope operator>","basis":"<actual source scope and selection rationale>","included_file_ids":["<actual ID>"],"exclusions":[{"file_id":"<other actual ID>","status":"not_relevant","reason":"<actual reason this stage does not apply>"}]}
```

Every selected current source must appear exactly once, included or excluded. Included IDs must have a configured completed job covering that ID. Exclusions support not_relevant/not_applicable with reasons, never unavailable/unprocessed as successful coverage. Stage 01 verifies a persisted finished registration scan and registered inventory, while explicitly limiting its completion meaning to registration. Stage 09 checks current upstream readiness instead of accepting coverage assertions. Completion of profiling/extraction/QC does not mean engineering approval.

## Instruction-work checkpoint

Read `plan` to obtain the exact current task fingerprint. Codex performs the selected instruction skill and writes a durable output artifact plus a receipt with schema `mep-master-checkpoint/1`: project_id, scope_id, input_fingerprint, source_file_ids, actor, method, summary, limitations, engineering_approval=false, sources (file_id/sha256), outputs (absolute path/sha256). Each source must match the registered bytes and each output must exist with the stated hash. A receipt is an operational attestation, not authentication or technical certification.

For profiling, at least one output JSON must have nonempty `worksheets` and `extraction_plan`. Each worksheet records name, source_file_id, columns, row_count, missing_values, data_types, unit_columns, column_naming_issues, parsing_difficulties. CSV may be represented as one explicitly named logical table. Preserve unknowns and parsing gaps; do not invent unit semantics from a header. The extraction plan records exact header mappings proposed for later explicit configuration. No inline Markdown class is imported or evaluated by the master.

For stage 08 Codex audits, additionally record `database_checks`. Stage 11 requires completed actual visual review. Do not mark unfinished work complete to satisfy the receipt. If a real missing dependency prevents work, keep the stage BLOCKED and report the exact dependency.
