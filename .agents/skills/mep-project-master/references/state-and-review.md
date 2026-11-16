# Persistent memory, recovery and human decisions

## One database

Registry is the only initial engineering database creator. The master never creates an empty competing evidence store. Before DB existence it writes only an immutable bootstrap journal in generated workflow output; the registry scan then creates/initializes its own core and registry schema. After a registered project exists, the master adds `master_schema` version 1, `master_project_configs`, `master_events`, `master_packages`, `master_operator_events`. It does not alter `PRAGMA user_version` or upstream tables. No SQL migration was applied during skill creation.

Project/configuration/scope identity, source/skill/config fingerprints, stage/job lifecycle, input references, persisted upstream IDs, output files/checksums, blockers, errors, package/version receipts and actual operator decision intents remain in this same DB. Raw sources, observations, matching, requirements, conflicts and engineering review events remain exclusively in their original core/registry/eq/tr tables and source archive. Review actors are supplied labels, not authenticated accounts.

Events are append-only and initialized PENDING for each new scope. Statuses: PENDING, RUNNING, COMPLETED, BLOCKED, FAILED, STALE. A child failure is recorded separately from a missing-configuration/coverage block. Interrupted work may remain RUNNING; it is never projected as completed. Read-only status derives staleness without writing; a later run appends the stale/recovery outcome. Completion verifies actual persisted rows or durable output, original registered hash linkage and declared stage coverage. QC findings remain candidates even when the QC operation completed.

## Caching and invalidation

Hash original source bytes, task inputs, explicit mapping/metadata files, actual per-skill configuration, master implementation and installed skill implementations. Exact file-ID scopes permit per-source extraction reuse; task references propagate actual artifact hashes. Changes to evidence/config/review IDs invalidate derived matching/review/package tasks. Current registry analysis/version state participates; live-source changes also invalidate work before a rescan. New/deleted sources invalidate intake and force stage coverage reconciliation. Do not rely on timestamps, prior conversation or a previous successful exit code.

Source-local task artifacts are reused when their exact input fingerprint and all output hashes remain valid. Derived matching/review jobs conservatively track project-wide shared review/import dependencies where narrower impact cannot be proven. This may mark additional derived tasks/potentially affected packages stale; it never treats an unknown dependency as current. Existing upstream idempotent imports/run IDs provide a second reuse boundary. Rerun does not silently activate an older extraction/import version.

Package checksums and immutable manifests stay authoritative in the generator's dedicated root. The master records references, not duplicate engineering package content. Cached reports are reused, changed versions get fresh attempt directories; no overwrite/delete of prior documents or raw evidence. Package RFQs are always drafts, regardless of technical readiness.

## Recovery

A `<engineering.sqlite>.master.lock` file excludes concurrent master writers across subprocesses. SQLite write transactions are short; the master does not hold a write lock while an upstream CLI runs. Native SQLite busy timeouts remain. The lock includes PID/token/time. Process death may leave it behind. Inspect the OS process and recorded attempt before manually removing a stale lock; the master never guesses that another process is dead. Never remove a lock owned by an active process.

Inspect status, task stdout/stderr, bootstrap journals and partial output. If the process stopped after upstream commit but before master receipt, resume calls the existing idempotent operation; it does not invent completion. Partial exports receive new attempt directories. The package generator independently inspects/reuses complete versions and preserves partial attempts. Back up engineering.sqlite together with its adjacent evidence archive before first real processing/migrations; ordinary live SQLite backup must include committed WAL state through an appropriate backup method, not a blind partial file copy.

## Engineering decision gateway

Request JSON specifies project_id, skill, command and options using actual upstream flags. Only `decision --request <file> --human-authorized` may execute review/interpret/accept-value/revision activation. The flag records the operator's assertion of explicit human authorization; Codex must already have that authorization for the exact decision. Never manufacture reviewer names, rationale, supporting references or accepted values. No automatic/guided task configuration can dispatch an approval command.

Allowed routes:

| Existing skill | Commands | Actual review scope |
|---|---|---|
| Registry | review | target-type/target-id/decision/actor/reason, optional value-json |
| Matcher | review | target-kind/target-id/decision/actor/reason, optional value-json |
| Reviewer | review, interpret, accept-value | actor/reason plus actual refs-json; actual payload/target IDs |
| Lineage | review | record/reviewer/decision/reason; optional field/value-json |
| ETL | activate | version/reviewer/reason |

Read the upstream usage reference for supported decision values. The gateway persists an intent before execution and then verifies the returned actual review/activation ID exists. If interrupted after upstream commit, inspect that audit before retrying to avoid a duplicate explicit event. A proposed Codex interpretation remains unreviewed until separately approved by the human through the existing reviewer. Revision applicability, instance identity, technical type, parameter approval, requirement wording, applicability, interpretation and coverage are independent decisions.

Changed sources do not inherit prior approval. Old reviews remain historical; current upstream bases reject stale targets/reopen affected engineering questions. Run current map/compare and readiness after source/disposition changes. The master does not forge a reopen decision on the engineer's behalf.

Stage 09 is an operational verification that selected upstream review prerequisites are ready. It creates no engineering approval. Full sequential approved generation requires it. An explicit selected `packages --mode approved` request may check just that requested category/entity scope directly after valid stage 08, recording a selected readiness receipt without declaring the whole project's stage 09 complete. The generator independently enforces its strict selected readiness again. Any mandatory unresolved approval in that selected scope blocks output. Draft generation may proceed explicitly without stage 09 and must retain gaps prominently.

## Optional delegated reasoning

The [native delegation contract](delegation.md) adds no tables, migrations, stage transitions or approval logic. Subagents return read-only source-linked proposals to the parent. The parent checks exact hashes/revisions/quotes/locators and current fingerprints, writes immutable artifacts and, for an actual configured Codex task only, submits the existing operational receipt. Its complete receipt JSON can retain a delegation metadata object without a schema change. Include relevant native config/role files as explicit task inputs to reuse the existing fingerprint mechanism; they are not automatically discovered as engineering job dependencies.

At most two independent reasoning children may run concurrently; no child invokes master/upstream pipeline CLIs, checkpoint/decision commands or database writes. The parent remains the sole serialized import/checkpoint owner under the existing project lock. These are instruction-level no-write controls: native agents inherit parent permissions and are not a separate OS-enforced read-only sandbox. Inconclusive child findings remain pending; no model may approve a requirement, match, revision, value, coverage or RFQ. Preserve the distinction between bounded analysis completion and a completed workflow stage.
