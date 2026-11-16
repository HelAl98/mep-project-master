# Native specification layout limitation — I-02

Operation B may retain otherwise valid native specification fragments as **ACCEPTED_UNREVIEWED_WITH_LAYOUT_LIMITATION**, never as reviewed requirements or full coverage. The original extractor is unchanged and its original `specification_layout_review` warning remains in the evidence, native job validation/audit and operation receipt.

## Scope

The internal policy `operation-B-native-specification-layout/1` applies only to Operation B/native_job, stage 04, specification-extractor/extract through the existing allow-listed interface. There is no general CLI flag to ignore issues. Legacy stage execution and other extraction/QC/result validators retain their strict behavior. The policy is an explicit part of the native job fingerprint; a strict historical stage cannot consume this limited-acceptance cache as an ordinary strict success.

Preflight requires one exact registered original PDF and one native mep-evidence/1 input, original path/name/hash/archive integrity, actual PDF page/line bounds, at least one line and no upstream package or record issues. Native ETL's existing validate_package is reused without constructing Store or importing evidence into SQLite.

Result acceptance requires the persisted output to match the parsed native result, the original document identity to remain exact, nonempty specification fragments with unreviewed status, exact original line text/indexes/locators and union bboxes, and native line-fragment/group locators intact. Only the exact single native global warning (code AND message AND structure) is permitted. Unexpected/duplicate/missing warnings, malformed or empty records, changed provenance/text, broken/out-of-range locators, record-level issues and page continuations fail closed. OCR/missing-bbox/reading-order/other source gaps are not waived. More complex layouts still require a separately supported review/scope path; this policy does not certify their content.

## Persistence and replay

The existing native COMPLETED **job** event stores the immutable evidence artifact/hash plus a validation object containing accepted_issues, source/input/output references, checks and `full_source_coverage: false`, unreviewed applicability, no engineering approval, no ETL authorization and no supplier release. COMPLETED here records a bounded tool run, not completion of historical stage 04.

The operation receipt records `evidence_acceptance` and `accepted_native_warnings` verbatim. Its normal native_job_results/dependencies point to the original engine event and artifacts. I-01 stable work identity and native output/source revalidation are unchanged; successful replay returns those same limitations without rerunning the job or adding job/audit events. Cache discovery metadata remains separate from stable work; the policy and its code/input/configuration remain identity-bearing.

Authorization, fresh compatible source assessment, project lock, append-only audit, native source/output validation and human review gates remain mandatory. No ETL call, applicability decision, stage completion, RFQ, supplier release or global synchronization follows automatically from acceptance.

The development acceptance evidence is under I02_Specification_Warning_Remediation: one actual specification extraction through Operation B, negative calls to the real native result validator, replay/event-count checks and unchanged formal stage history. This correction does not revisit the separate global config.toml hash incident or overwrite any global settings.
