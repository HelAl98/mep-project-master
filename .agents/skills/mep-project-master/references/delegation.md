# Native Codex delegation

This is an instruction layer around the existing 11-stage master, not another execution engine. Python remains deterministic and contains no model/API calls. Existing `workflow.json` and `skill-routes.json` are authoritative; the matrices below describe optional assistance, not additional stages or executable skill APIs.

## Independent policies

For the explicitly requested [one-request mechanical procurement](procurement-workflow.md), Main may delegate a useful bounded ambiguity and continue independent work without exposing routine Guided stops or per-role selection to the user. This scoped mode retains the six preferred settings and all read-only/single-writer/concurrency restrictions. critical_reviewer requires the user's explicit request. Legacy start/resume and standalone requests retain the policies below.

Stage progression stays **Guided** (default) or **Automatic**, exactly as implemented. Delegation is separately **single-agent**, **manual** (default), or **delegated workflow**:

- Single-agent: the main Codex agent does all authorized work with existing tools. Spawn none, even if parallelism could help.
- Manual: spawn only the specialty/stage explicitly requested by the human. A specialist-only evidence review does not authorize starting/resuming a pipeline or processing a whole project.
- Delegated workflow: only an explicit human request authorizes bounded delegation of eligible work during the existing workflow. Do not delegate trivial or deterministic work just because delegation is permitted. Guided still stops at each major stage; Automatic still stops at engineering approvals/blocks.

These are agent instruction policies, not invented native TOML flags, Python commands or a change to `execution_mode`. Record the actual request/scope in the parent-authored task/receipt. For a resumed chat without clear authorization evidence, use the main agent; a previous general interest in agents is not authorization for a new delegation scope. The human may change or revoke delegation at any time. `critical_reviewer` is excluded from ordinary delegated-workflow permission: require an explicit critical-review request or an applicable separately human-approved escalation policy identifying trigger, permitted scope/model, call/concurrency limit and stop condition. No escalation policy is pre-approved by this installation.

## Roles and model settings

Repository-local native files are `.codex/agents/<name>.toml`; user-global files are `~/.codex/agents/<name>.toml`. Resolve the selected installation and supplied instruction paths explicitly. Required name/description/developer_instructions and supported model/reasoning fields are configured. The configured `[agents]` limit is two concurrent spawned threads, excluding the primary thread. Do not create a seventh visual role, change the main model, or set global subagent-model defaults for unrelated work.

| Native name | Preferred model / effort | Bounded assistance |
|---|---|---|
| document_extractor | gpt-6-luna / low | Classify existing table/native extraction; help profiling, source metadata and supplemental document organization |
| specification_analyst | gpt-6.1-sol / medium | Exact clauses, conditions, mandatory wording, Mechanical/Electrical/BMS applicability candidates |
| cad_analyst | gpt-6.1-sol / medium | Supplied CAD export/text/visual evidence, tags, attributes and ambiguous drawing context |
| equipment_matcher | gpt-6.1-sol / medium | Interpret existing matching proposals; instances/types, ambiguous identity and quantities |
| conflict_analyst | gpt-6.1-sol / high | Compare scoped conditions/units/revisions and explain conflict candidates |
| critical_reviewer | gpt-6-astra / medium | Exceptional independent second interpretation, never routine approval |

Preserve these requested settings. No model inference call was made to verify access. If a role/model is unavailable, disclose it and use the main agent with existing deterministic tools as the supported default fallback, preserving its actual model/effort. Do not silently substitute Astra, higher effort, an API, or a second orchestrator. The parent can use another native model only when that change is permitted by the user's current request; record actual settings and the limitation. For genuine visual CAD interpretation, Terra (`gpt-6.1-terra`, medium) may be used through a native explicit-model spawn if available and authorized. Do not claim the Sol-pinned cad_analyst file changes model from a prompt: custom-file settings take precedence. A neutral no-write visual task using the same CAD instructions is a documented alternative on hosts with explicit-model tools; otherwise the parent performs the visual pass or reports unavailable capability.

## Skill routing: all 16 existing skills

Read selected existing SKILL.md before using its instructions. The main agent runs deterministic helpers; specialists read prepared evidence and return proposals. This table does not authorize every skill or every specialist on each request.

| Existing skill | Execution owner | Optional specialty |
|---|---|---|
| mep-project-master | Main agent + unchanged Python master | None: stage progression, lock, state and approvals stay central |
| mep-document-registry | Main agent runs registry scan/rescan/review as authorized | document_extractor for ambiguous supplied metadata; cad_analyst for drawing-reference uncertainty |
| data-profiler | Main agent performs instruction workflow; parent alone checkpoints | document_extractor for bounded actual worksheets/headers/types/gaps |
| pdf-to-structured | Main agent runs deterministic native PDF extractor/reuses artifacts | document_extractor only for unresolved classification; no whole-PDF model parsing |
| dwg-to-excel | Main agent runs supplied actual mapped XLSX adapter | cad_analyst interprets its output; native DWG remains unsupported |
| drawing-analyzer | Main agent runs deterministic text candidate helper | cad_analyst for ambiguous tag/note/context evidence |
| specification-extractor | Main agent runs deterministic exact-fragment helper | specification_analyst interprets relevant extracted clauses |
| etl-pipeline | Main agent only: imports/FTS/revision activation through existing controls | None for writes; a specialist may flag a source/mapping question for parent review |
| data-lineage-tracker | Main agent only: existing lineage CLI may initialize Store, so it is not a child query | conflict_analyst reads a parent-prepared lineage artifact |
| mep-equipment-matcher | Main agent runs existing import/match/group/export and actual authorized review | equipment_matcher investigates existing current candidates |
| mep-cross-document-reviewer | Main agent runs existing index/map/compare/review/export | specification_analyst for clauses; conflict_analyst for comparisons; critical_reviewer only exceptional |
| data-quality-check | Main agent runs deterministic QC plus existing master DB audit | conflict_analyst explains selected evidence-linked findings |
| mep-technical-package-generator | Main agent alone reads readiness and generates current requested components | No routine delegation; unresolved reasons route upstream to appropriate specialty |
| xlsx-construction | Main agent instruction/built-in spreadsheet authoring and actual visual review | document_extractor can review supplied layout/structure facts, never generate/checkpoint through a competing tool |
| docx-construction | Main agent instruction/built-in document authoring and actual visual review | document_extractor for organization; specification_analyst checks exact-clause fidelity if requested |
| pdf-construction | Main agent uses safe built-in PDF authoring/export workflow | document_extractor for supplied coverage/layout questions; original split/bookmark defects remain prohibited |

## Stage overlay: use the existing prerequisites

| Existing stage | Deterministic/master responsibility | Optional reasoning after inputs/prerequisites are ready |
|---|---|---|
| 01 Intake | Register bytes/files/sheets, revisions, inventory | document_extractor / cad_analyst for a bounded ambiguity |
| 02 Profiling | Codex instruction work, actual artifact and existing checkpoint | document_extractor |
| 03 Document extraction | Native PDF/actual CAD export/text candidates, exact current cache | document_extractor or cad_analyst |
| 04 Specification extraction | Exact-fragment extraction, no applicability approval | specification_analyst on selected evidence, still a candidate |
| 05 Integration/lineage | Serialized imports, hashes/source links; main agent only | Normally none; ask specialty for one identified mapping ambiguity |
| 06 Equipment matching | Existing matcher owns deterministic proposals | equipment_matcher |
| 07 Requirements mapping/comparison | Existing reviewer owns index/map/compare and stored cases | specification_analyst / conflict_analyst |
| 08 Quality control | Existing QC and DB integrity audit | conflict_analyst for selected findings |
| 09 Human approvals/readiness | Human decisions; parent alone persists through existing gates | conflict_analyst; critical_reviewer only under its separate authorization |
| 10 Packages | Parent/generator strict readiness and immutable versions | No routine child; unresolved questions return to upstream stage |
| 11 Professional export | Reuse valid documents; parent/built-in authoring/render review | document_extractor or specification_analyst for an explicitly requested bounded check |

A standalone analysis may inspect already available authorized evidence without advancing a stage. It cannot manufacture missing inputs, satisfy stage prerequisites, approve a requirement or claim an unsupported system filter. Speculative applicability identified at stage 04 remains unreviewed; stage 07 and human decisions remain required.

## Native dispatch and actual host support

When the native host exposes a custom-agent role/type selector, request the configured `name`. TOML metadata is separate from the skill's `agents/openai.yaml`; Python never launches these roles. Project trust, configuration reload, managed policy and model access can affect availability. Reload/start an appropriate trusted project session when necessary; no session restart or trust change was performed in this update.

Some desktop sessions expose only native `collaboration.spawn_agent` with `task_name`, `message`, `fork_turns`, `model`, `reasoning_effort`, rather than a custom role/type selector. In that case the parent must read the relevant role TOML and supply its developer instructions/contract explicitly in the bounded message; matching `task_name` alone does not load a TOML file. Use `fork_turns="none"` for a small context and explicit model/effort only where the tool supports them. Use native follow-up/wait/interrupt controls available on that host, not `create_thread`, shell subprocesses, SDKs or API calls. This explicit native-tool fallback applies the instructions by message, not as a verified native custom-agent configuration load. Custom-file feature restrictions are not automatically enforced by that fallback; keep the no-write/no-external-actions rules explicit and stop if they cannot be respected. Never silently inherit a larger model while claiming the preferred model ran.

Independent parallel work is limited to two live children, with distinct immutable evidence slices and no mutable shared-state access. If the host's supported control can close/release completed threads, use it before opening more; otherwise reuse/follow up an existing role or work sequentially and report the limit. Never spawn nested agents or overlap master pipeline invocations/imports. Do not delegate a task whose necessary tool would initialize or write a database. Prefer parent-prepared query-only projections/JSON artifacts. No background watcher/process, database-writing subagent, or external service is installed.

## Bounded task envelope

The parent checks current master status/prerequisites, source/revision fingerprints and cached outputs, then supplies only:

- A unique task ID, configured role, stage or standalone scope, actual human authorization and explicit question/stop condition.
- Actual project/scope IDs when available, current master input fingerprint and source IDs/hashes/revisions; missing project IDs stay null for standalone work.
- A small set of immutable artifact paths/hashes plus exact page/row/clause/handle slices or necessary image crops. No whole project folder or full specification by default.
- Selected skill instruction paths, requested actual model/effort and the result contract below. No database path is needed when prepared evidence suffices.

An independent critical second opinion gets the neutral question and original source evidence; do not bias it with an intended answer or earlier interpretation unless the review specifically concerns that interpretation. Missing evidence/capability returns BLOCKED or an escalation recommendation to the parent, not a self-spawn or an invented fact.

## Structured result and parent acceptance

Return JSON in the child's final message; **children do not write files or SQLite**. Fields:

```json
{
  "schema_version": "mep-delegated-analysis/1",
  "task_id": "<parent-assigned ID>",
  "role": "<configured role>",
  "project_id": null,
  "scope_id": null,
  "stage": null,
  "input_fingerprint": "<parent-supplied current fingerprint>",
  "analysis_status": "COMPLETED",
  "sources": [],
  "findings": [],
  "missing_evidence": [],
  "limitations": [],
  "escalation": null,
  "engineering_approval": false,
  "database_changes": false
}
```

This is a contract illustration, not a synthetic project output. `analysis_status` is COMPLETED or BLOCKED for that bounded reasoning task only; it never changes a master stage or upstream Verified/Pending/Conflict status. Each source must include actual file_id, sha256, revision (null if unknown), artifact hash and exact known locator fields (PDF page, worksheet/row/cell, section/clause/paragraph, CAD handle/layer/coordinates/units). Findings have id, type (observation/interpretation_candidate/match_candidate/conflict_candidate/uncertainty), exact source quotes/values, source references, rationale, uncertainty, missing conditions and recommended human question. Both sides of a claimed conflict need references. Never invent empty arrays as proof of project-wide completeness.

The main agent checks task identity/scope, actual reported sources against registered hashes/revisions and authorized slices, exact quotations/units/locators, source changes since dispatch, unsupported claims and completeness of the requested evidence. A model saying COMPLETED is not validation. Reject/re-request stale, source-free or invented statements without entering them as observations or approvals. Record actual native invocation metadata from the host (requested/actual model, effort, native handle where available, authorization reference, role-definition hash), not the child's guess. Unknown actual settings stay unknown.

Only the parent writes a new immutable analysis JSON in the project's configured generated-output area, refuses overwrite and calculates hashes. Reuse a still-current existing artifact/receipt before another model call. For a real configured `kind: codex` task, construct the existing `mep-master-checkpoint/1` receipt after independently validating all required outputs and provenance; its method may identify native subagent assistance and an additional `delegation` object may retain actual invocation metadata. `operations.checkpoint` already stores the complete receipt, so no schema or Python change is needed. A delegated analysis JSON alone is insufficient for a profiling checkpoint: the actual worksheet/extraction-plan artifact is still required. A document-delivery receipt still requires actual parent render/visual review.

For reproducible cache invalidation, include the selected `.codex/agents/<role>.toml`, `.codex/config.toml` and this reference as explicit paths in that configured Codex task's existing `inputs` (alongside actual evidence); those input bytes are already hashed by the master. Record an authorized override in that task's configuration/bounded request before using a different model so its task fingerprint is updated. The engine does not automatically fingerprint arbitrary native configuration files or treat the delegation overlay as executable routing. Standalone findings are advisory parent-owned artifacts; do not fake a stage job/checkpoint to persist them.

The parent alone serializes existing imports/checkpoints under the project lock, initiates stage transitions, reconciles readiness and performs actual human-authorized review commands. Read-only recommendation never authorizes `decision`, upstream `review`, `interpret`, `accept-value`, revision activation or RFQ issuance. The master lock does not protect an uncooperative external writer; role instructions are not OS-level read-only enforcement. All specialists inherit parent permissions. Do not run writes from any child, even when the host technically permits them.

## Invocation examples (not executed)

- Single-agent: `$mep-project-master Review the saved AHU-003 evidence using single-agent execution. Do not spawn subagents or start the pipeline.`
- Manual: `$mep-project-master Delegate the supplied schedule interpretation to document_extractor only. Return source-linked findings; do not run stages.`
- Manual CAD: `$mep-project-master Use cad_analyst to review these prepared drawing candidates, preserving handles and revisions. No extraction or database writes.`
- Manual matching: `$mep-project-master Use equipment_matcher to investigate these existing ambiguous AHU-003 proposals. Recommendations only.`
- Manual conflicts: `$mep-project-master Delegate this saved conflict to conflict_analyst; keep all decisions pending human review.`
- Exceptional: `$mep-project-master Explicitly use critical_reviewer once for this specified unresolved conflict as an independent second opinion. No approvals or additional agents.`
- Full delegated Guided request: `$mep-project-master Resume the configured project in Guided Mode with delegated workflow execution. Use at most two independent read-only specialists when useful, prefer deterministic processing, and stop after each newly completed major stage. Do not invoke critical_reviewer without my separate permission. Keep all persistence and approvals in the existing master.`

These are natural-language native Codex requests using actual configured names, not new CLI subcommands, slash commands, or a guarantee of model availability. For the full request, first inspect existing status/plan, execute/reuse deterministic operations, delegate only necessary eligible evidence interpretation, validate/persist its proper receipt centrally, complete the current stage through the existing master and wait at the Guided boundary. Repeat only when instructed. No stages were run during installation.

## Sources and validation boundary

Configuration structure and custom-agent inheritance were checked against [official native subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents). Concurrency keys and model reasoning settings were checked against [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). Preferred model IDs/effort levels were cross-checked with [OpenAI's model catalog](https://developers.openai.com/api/docs/models) and the current host tool declarations; this does not prove account access or a successful custom-role spawn. Static TOML parsing/file preservation is not runtime integration validation. No role/model dispatch, project processing, database migration, complete workflow, benchmark or test agents were run.
