# Operation workflow — P1-05 (development)

Use this interface for an explicitly scoped request. It is a thin eligibility and execution bridge to the existing master, EvidenceReader, Supplier Draft Generator and native jobs. It does not schedule a second DAG, initialize a project database, migrate schemas or approve engineering facts. Existing stage commands remain available.

## Operations and old stages

| Operation | Existing stages | Supported actions |
|---|---|---|
| A Register & Scope | 01 intake, 02 profiling | Reuse document register; rescan an already registered complete root |
| B Prepare & Extract | 03 document extraction, 04 specifications, 05 ETL | Reuse stored extraction; explicit supported native job |
| C Consolidate Equipment | 05 ETL, 06 matching | Reuse saved equipment; exact audited import; original matching-plan executor |
| D Link & Check Sources | 07 mapping/review, 08 QC | Reuse saved candidates/context/findings and bounded literal checks; native QC job |
| E Draft & Delivery | 10 package, 11 export | Existing supplier generator or hash-verified compatible draft reuse |

Stage 09 human review stays an independent gate. Operations never create whole-stage completion events. An operation can succeed while a broader historical stage remains BLOCKED. Guided and Automatic both execute only one explicitly authorized operation per call; there is no implicit chain or delegated writer.

## Contracts

`assets/config/operations.json` is the routing/requirements catalog. `assets/config/operation-scope.example.json` is a generic starting request. `operation-contracts.schema.json` describes scope/plan/receipt envelopes; Python performs semantic, path, source-closure and native checks beyond JSON Schema.

`mep-operation-scope/1` includes project, operation, action, exact source IDs and/or families/references, source selection, required evidence, exclusions with reasons, accepted-limitation audit IDs, coverage limitations, currency policy, mode, approval requirements and a new output destination. Additional source/native/options details live in the same request. Existing source/configuration identities and eligibility are resolved into `mep-operation-plan/1`, not asserted by the caller.

Selection `explicit` is a closed source set: supporting evidence outside it blocks. `equipment_evidence` explicitly authorizes resolving the supporting-source closure of selected saved equipment; that closure is listed before execution. `registered_root` is for an explicit whole registered root only. Parent source/entity scope still constrains all selections. Unknown references never fall back to all equipment. Excluded sources cannot be used as required dependencies. Missing unregistered material is an explicit coverage limitation, not a fictitious file ID.

Required evidence names: `registration`, `extraction`, `equipment`, `parameters`, `specification_candidates`, `boq_context`, `electrical_context`, `bms_context`. Presence means evidence availability under the exposed contract, not full coverage, quantity verification or approved applicability. `candidate_limit` bounds the first saved specification page per family/run; pagination metadata and omitted evidence remain visible.

Eligibility outcomes are READY, READY_WITH_LIMITATIONS, BLOCKED, REQUIRES_HUMAN_ACTION, UNKNOWN, separate from old stage statuses. Priority is blocking errors, uncertain essential interfaces, required human decisions, then limitations. Unsupported bootstrap/database/schema raises an explicit error without creating data. Plan-only requests do not write SQLite, create locks, run processors or request human confirmation. Explicit plan JSON export is the sole requested file write in planning CLI usage.

## Currency, reviews and reuse

An explicit P1-01 snapshot is timestamped, not a live guarantee. Read-only projections and draft exports expose UNKNOWN/unverified evidence and incomplete coverage; MODIFIED/MISSING selected sources block unless `allow_historical_draft_evidence: true` explicitly permits historical draft evidence. Changed unrelated sources do not invalidate scoped content. UNKNOWN lineage stays UNKNOWN.

Native processing needs compatible registered source versions and a fresh explicit snapshot (`max_snapshot_age_seconds`, default 900, range 1–3600), live selected source/archive checks and original native validators. Nothing activates or approves a revision. Accepted source limitations are displayed by related host IDs; historical acceptance metadata is never a blanket exemption. The original native validator determines whether its permitted-operation contract applies.

P1-04 checks separate identity, quantity, clause applicability and revision assertions. A required missing/invalid/test-only assertion requires human action. The operation does not call the confirmation prompt. Recorded actor labels are not authenticated identities. `delivery_mode` other than `draft` and requested procurement release require human action; this adapter has no approved release route.

The plan fingerprint binds the request, scoped source/version identities, selected stored record contents, projection, current review validity, source assessment identity, declared artifacts, configuration, implementation and native plans. It deliberately excludes unrelated full-database writes. At execution the basis is recomputed under the existing project lock. Existing job caches and P3 draft receipts are hash-validated before reuse. Reusing an old draft may tolerate only changed top-level assessment metadata; per-fact source states, provenance, options and material contents must still match. Original package timestamps stay intact.

## Native interfaces and limits

Read each selected sibling SKILL.md before using an adapter. Do not fabricate functions for instruction-only skills.

- B routes existing PDF extraction, drawing analysis, specification extraction, mapped CAD-export ingestion and tabular ETL commands from `interfaces.py`; D routes existing QC. Native evidence JSON must identify the exact original path and hash. No direct DWG or DOC conversion is invented. Legacy XLS input needs an existing supported conversion; tabular native routing accepts XLSX/CSV.
- Native specification extraction currently emits a mandatory layout-review warning rejected by the original engine output contract. This route reports UNKNOWN until compatibility is deliberately resolved. No warning validator is weakened.
- C import uses the existing `equipment_scope.assess_job` and `engine.run_job`, preserving exact audited intake, mapping/cell/CAD lineage, quantity-warning dispositions, source/archive hashes, native validation and job audit. Only the coarse whole-project Stage01/02 completion prerequisite is replaced in this new operation route by those source-specific conditions. The old scoped executor is unchanged. Existing legacy inventory-wide receipt fingerprints can still block after unrelated changes; they are not waived.
- Native matching has no source filter, so its original upstream and exact full-dataset guards remain. Unsupported narrow matching cannot silently become global matching.
- A rescan only supports an existing fully registered root with exactly matching file inventory and compatible initialized schemas. New/unregistered/deleted root files need the original Registry intake workflow. No automatic bootstrap or migrations.
- D reuses current saved candidate links and existing QC findings. Missing source references/units and literal differing printed values within identical saved equipment/name/unit/context are unreviewed findings, without unit conversion, design inference or automatic conflict resolution. Broad new semantic mapping remains an explicit capability gap; advanced conflict review stays optional.

## CLI

Use the resolved Codex Python and the absolute local `scripts/master.py` path. Relative request paths resolve against the existing project config. Examples below use shell variables for the operator's actual paths.

```powershell
& $python -X utf8 -B $master operation list
& $python -X utf8 -B $master operation requirements --operation C
& $python -X utf8 -B $master --config $config operation assess --scope $scope --currency-snapshot $snapshot
& $python -X utf8 -B $master --config $config operation plan --scope $scope --currency-snapshot $snapshot --output $newPlan
# Inspect the saved plan; separately authorize its exact fingerprint and actions.
& $python -X utf8 -B $master --config $config operation execute --plan $newPlan --authorize-plan $fingerprint --actor $actor --reason $reason --currency-snapshot $snapshot
# Add --allow-native-processing only for explicitly authorized native processing.
& $python -X utf8 -B $master --config $config operation receipts --operation C --limit 25 --offset 0
```

The fingerprint flag is a scoped execution assertion, not human engineering approval or authentication. Do not invent authorization because a plan is eligible. Subagents return recommendations only; `--executor-role subagent` cannot execute. This is an application rule, not an OS security boundary.

## Python

```python
from master_project.source_currency import load_config
from master_project.operation_workflow import operations, requirements, plan_operation
from master_project.operation_adapters import execute_operation, operation_receipts

cfg = load_config(config_path)
plan = plan_operation(cfg, explicit_request, currency_snapshot=snapshot_path)
# After actual authorization of this exact plan:
receipt = execute_operation(cfg, plan,
    authorized_plan_fingerprint=authorized_fingerprint, actor=actual_actor,
    reason=actual_reason, currency_snapshot=snapshot_path,
    allow_native_processing=False, executor_role='main')
```

For new E rendering, supply explicit existing `supplier_runtime.node_executable` and `supplier_runtime.artifact_module_root`; reportlab must already be available. No dependency installation or paid service is invoked. Alternatively supply `reuse_supplier_receipt` with its exact `path` and `sha256`.

## Persistence and recovery

Existing `master_operator_events` append-only triggers and `project_lock` are required. No new tables or database. `mep-operation-receipt/1` records RUNNING, SUCCEEDED or FAILED_PARTIAL separately from eligibility and stage states, with source/configuration basis, actual sources, reuse, actions, outputs/hashes, limitations and verification. Native jobs retain job-level audits. Reusable operations write only their JSON artifacts and audit events. P3 supplier output is DRAFT only.

A completed identical fingerprint is reused only after output hash verification, with no duplicate audit. A changed basis requires a newly inspected/authorized plan. Interrupted or failed attempts remain visible and block silent retry of that fingerprint; inspect partial artifacts, then choose a new explicit output/attempt scope. No rollback of already persisted native job evidence is pretended. Old whole-stage history is never rewritten.

Development validation: 17 bounded fixture checks, copied-state compatibility/reused draft execution; see the Phase05 report. Positive real native import/conversion/matching and end-to-end rendering remain unvalidated in this phase. Global installation was not synchronized.
