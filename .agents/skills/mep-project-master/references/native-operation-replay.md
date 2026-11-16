# Native operation replay — I-01

This correction separates cache discovery from stable requested work. It reuses the existing master lock, job cache/events, native validators, source-currency policy and append-only operation audit. No second cache, table, workflow engine or automatic retry is added.

## Stable identity

`operation_workflow.stable_work_basis(plan)` copies the exact fingerprint basis and excludes only:

- `fingerprint_basis.native_plan.reused`
- `fingerprint_basis.native_plan.actions[*].cached_event_id` and `.reused`, only for `kind: existing_master_run_job`

These fields remain available in the original plan for preview. The normalized basis is hashed by `identity(plan)`; planned work is not mutated. Identically named fields in the request, input/configuration or other payload remain hashed. Runtime result IDs do not become work identity.

Everything else stays bound: exact scope/request, project/output paths, registered source versions/hashes, saved assessment, evidence content, native job/input/configuration fingerprints, implementation signatures, review requirements, authorization and eligibility. Changed work requires a fresh inspected/authorized plan. Existing pre-correction plans/receipts are historical; no audit rewrite or silent conversion.

## Replay procedure

Under the existing project lock, require the exact authorized plan fingerprint, actual actor/reason and main executor role. Native processing still requires its explicit permission flag. Reassess eligibility under the existing source snapshot/freshness rules and verify selected live originals AND archives. Compare stable work bases before looking up success; a previous success is not permission to ignore source/configuration/code/evidence changes.

A matching SUCCEEDED receipt must have completed verification. Recheck its declared output hashes and its original `native_job_results` against real COMPLETED master job events for the same project/scope/job. Reuse existing `valid_artifacts` and `valid_persisted` to verify the actual extraction output and other native dependencies, not merely the operation's small projection JSON.

New native receipts retain `native_job_results` and a `native_dependencies` snapshot of those original event IDs, stages, job fingerprints, output artifact hashes and persisted references. These are provenance references to the existing cache/event mechanism, not a parallel cache. Missing, altered or historical native output/evidence blocks replay even when normal cache discovery reports `reused: false`. No new extraction or audit is triggered to repair it.

A valid replay returns the original receipt with `idempotent_reuse: true`, empty `new_processing_actions`, and `replay_verification` indicating verified basis/output/native dependencies and `new_execution: false`. The saved original receipt is not overwritten and no successful event is duplicated.

RUNNING/interrupted and FAILED_PARTIAL attempts remain non-reusable. They require inspection and the existing explicit new-attempt recovery path; no silent retry or overwritten partial outputs. Native legacy success lacking bound native-job result references fails closed rather than being assumed valid.

## Limits

This is replay of a compatible successful operation, not a source assessment refresh or new work authorization. If the configured native freshness window expires, obtain a new explicit assessment/plan; do not change timestamps on the old snapshot. Unknown/missing/changed source or review state remains a blocker under the existing policies. Source/configuration/code mismatches report affected basis sections; direct live hash failures identify the source ID, and output failures identify their declared output or native event/job.

The positive acceptance is genuine native PDF extraction and repeated/invalid replay on an isolated synthetic project. Reuse-only/draft receipts continue their existing path. Original matching/import executors can have additional one-use, upstream/dataset or new-result-path gates; this change does not bypass them or claim universal replay for workflows whose own evidence changes. Native result validation and formal stage histories are unchanged. I-02 warning compatibility remains out of scope.

This implementation is included in the release. Replay success never authorizes production processing, supplier contact or human approval.
