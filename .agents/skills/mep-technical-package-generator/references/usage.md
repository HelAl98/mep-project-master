# Local package generation

Status: authored implementation, execution validation deferred. No command/example below was executed during creation. No project database was opened, migrated or processed; no Word/Excel examples were generated.

## Runtime

Python 3.10+, existing SQLite schema ledgers, openpyxl and python-docx are required. Resolve the bundled interpreter using Codex's workspace dependency loader; outside Codex use an equivalent local environment. No dependency installation, paid API or AI call is required. Ordinary local execution runs deterministic Python and SQL; using Codex to author/operate commands is distinct from a model-free standalone run.

The actual Registry, Equipment Matcher and Cross-Document Reviewer folders/interfaces were inspected and are installed. The latter two have not been execution-tested. The generator's read-only compatibility integration is therefore provisional too. It refuses absent/upgraded incompatible prerequisites instead of rebuilding them.

From the project directory, set actual selected paths. Global flags precede the command:

```powershell
$packagePython = 'python'
$packageScript = '.agents/skills/mep-technical-package-generator/scripts/package_generator.py'
$packageDb = 'D:/MEP Project/State/engineering.sqlite'
$packageProject = 'actual-registered-project-id'
$packageConfig = 'D:/MEP Project/Rules/package-settings.json'
$packageReview = 'D:/MEP Project/Rules/technical-review.json'
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview categories
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview readiness --category CHWP
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview issues --tag CHWP-003
```

Replace `python` with the actual interpreter path as needed. `--category` can repeat. Tags reused in different scopes are not silently merged; use `--entity-id` to disambiguate. Categories with reference-only evidence but no upstream equipment entity remain visible in listing and cannot be silently fabricated into a package. Resolve missing entities through the upstream workflow.

## Generate

```powershell
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview draft --category CHWP --output 'D:/MEP Project/TECHNICAL_PACKAGES'
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview approved --category CHWP --output 'D:/MEP Project/TECHNICAL_PACKAGES'
```

`draft` includes missing/unapproved information as internal-review evidence, not approved supply scope. Every draft Word document is marked. `approved` blocks the selected set when any group is not ready; it does not quietly drop pending groups. Select an explicit ready entity scope if other category groups remain pending. Group readiness is preserved independently in reports.

Component commands: `register`, `specifications`, `matrix`, `rfq`; each accepts `--mode draft|approved` (default draft) and the same selectors/output root. They still produce data/manifest receipts. `rfq` is always a non-issued draft, even with approved technical information. No estimated prices, addresses, supplier names or delivery/payment promises are populated.

## Readiness

Statuses: READY_FOR_EXPORT, DRAFT_INCOMPLETE, BLOCKED_BY_CONFLICTS, PENDING_ENGINEERING_REVIEW, SUPERSEDED. Readiness checks identity, a single verified technical type, relevant instance/type source revisions, reconciled quantity, consistent approved values, original-clause review/applicability/interpretations, required coverage and outstanding current engineering cases. Missing review or zero detected conflicts is not approval.

Final quantities are accepted only from compatible independently documented counts or a current explicit quantity interpretation already approved upstream. An explicit quantity interpretation needs canonical quantity, discrete normalized units, `count_basis: individual_equipment`, the actual `scope` and exact `equipment_ids` represented (or the single selected entity). It is not supplied on the package CLI. Set/package/duty/accessory quantities remain distinct until an actual decision resolves them. A native table lacking a documented count basis will commonly need upstream clarification rather than automatic reconciliation.

This skill records no new approvals. Resolve issues, approve/withdraw values and select revisions through the upstream skills, then rerun their review before generating a new package. Optional formal-release configuration only checks existing actual authority; generation itself never declares a formally issued RFQ.

## Output and versions

```text
TECHNICAL_PACKAGES/
  <actual-discipline>/
    <actual-category>_<stable-category-key>/
      V_<source-selection-version>/
        Equipment_Register.xlsx
        Technical_Specifications.docx
        Requirements_Matrix.xlsx
        Review_Status.xlsx
        RFQ_Draft.docx
        Source_References.xlsx
        Package_Data.json
        Package_Manifest.json
        Generation_State.json
```

Only actual selected equipment categories produce folders. Component commands omit unrequested files. Safe hashed category suffixes prevent Windows name/case collisions. Generation_State is an immutable attempt-start receipt; a completed Package_Manifest is authoritative for completion. Failed attempts retain partial files and a failure receipt when available. A retry uses a separate attempt directory; it never overwrites a partial/complete version.

The root must be a dedicated new directory or one already marked by this generator. It cannot be the source root/ancestor or database directory itself. The registry-compatible root marker prevents re-ingestion. A root lock prevents concurrent generation; a stale lock requires inspection and manual recovery, never automatic removal of unknown work.

Identical complete source/selection/configuration/component/template/code versions are reused after output checksum checks. Source/review changes yield new versions. Damaged completed output is reported and preserved rather than silently regenerated over it. Do not edit a completed package in place and expect checksums to remain valid.

```powershell
& $packagePython -X utf8 -B $packageScript --db $packageDb --project-id $packageProject --config $packageConfig --review-config $packageReview inspect --output 'D:/MEP Project/TECHNICAL_PACKAGES'
```

`inspect --manifest <actual-manifest>` selects one version inside that output root. It reports original readiness, potentially-outdated source state, output hash problems and incomplete generation directories without modifying previous versions. Old issued status is never inferred or overwritten. Data receipt changes are deliberately conservative and may flag a package after another project-level review changes.

Exit codes: 0 command completed, 2 validation/readiness/generation error, 130 interruption. Reports are implementation outputs, not a claim that Word/Excel rendering has been visually verified. Complete original text and long values remain in Package_Data.json when Excel display limits apply. No original source documents are copied wholesale.
