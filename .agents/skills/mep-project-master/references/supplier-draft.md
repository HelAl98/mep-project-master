# P1-03 — Compact Supplier Draft Generator

Draft-only compilation through **EvidenceReader `mep-evidence-reader/1`**. No independent SQL, source reprocessing, matching, engineering selection, pricing, approval or supplier communications. The existing stage graph and specialized package generator remain unchanged.

## API

```python
from master_project.source_currency import load_config
from master_project.evidence_reader import EvidenceReader
from master_project.supplier_draft import generate_supplier_drafts, SupplierDraftGenerator

cfg = load_config("/absolute/project/rules/master.json")
with EvidenceReader(cfg, currency_snapshot="/absolute/explicit-phase01.json") as reader:
    # Deterministic in-memory compilation, with no output writes:
    content = SupplierDraftGenerator(reader, options).compile()
    # Explicit new output only, one subfolder per stored family:
    receipt = generate_supplier_drafts(
        reader, options, "/absolute/new-output-directory",
        node_executable="/absolute/bundled/node",
        artifact_module_root="/absolute/bundled/node_modules",
    )
```

Resolve bundled Python, Node and `node_modules` with the Codex workspace dependency loader. Add this master's absolute `scripts` directory to Python's `sys.path`. No dependency installation is performed. Rendering requires bundled `reportlab` and `@oai/artifact-tool`; explicitly requested DOCX also requires `python-docx`. Compilation uses Python's standard library and the existing reader.

## CLI

```text
python -X utf8 -B /absolute/master/scripts/master.py --config /absolute/master.json supplier-draft --options /absolute/options.json --output /absolute/new-output --currency-snapshot /absolute/phase01.json --node-executable /absolute/node --artifact-module-root /absolute/node_modules
```

The CLI is separate from `start/resume/run` and never starts a stage. `--config` precedes the command. A source-currency snapshot is optional and explicitly selected. If the selected snapshot is missing/incompatible, the CLI creates a reader without enrichment and records the error/status UNKNOWN; it does not recompute hashes or accept revisions. The Python API caller should create a compatible reader or omit enrichment. Database/configuration errors still fail safely.

Existing output directories are rejected. Source/state/archive/master output protections are delegated to the reader's exclusive-create `write_json` interface; no competing safety query or database is created. Rendering errors retain partial draft files and a `FAILED_PARTIAL_DRAFT` receipt instead of reporting completion. No production checkpoint/event is written.

## Options

Start from [supplier-draft.example.json](../assets/config/supplier-draft.example.json). Replace example references with real saved references or use `family` with an exact stored family. If both family and references are supplied, references select within that family. Missing references are explicit errors. Source-reference/UC identity contract gaps are not replaced with a second matching pipeline.

| Option | Behavior |
|---|---|
| `schema_version` | Required `mep-supplier-draft-config/1` |
| `project_name`, `title` | User-facing labels; project name otherwise from existing configuration |
| `family` or `references` | Exact stored family, tags or exposed profile IDs; references may span families |
| `disciplines` | Included labels; default Mechanical/Electrical/BMS |
| `role_disciplines` | Optional explicit role-to-discipline map; default schedule/drawing/boq → Mechanical, electrical → Electrical, bms → BMS |
| `language` | English (`en`) only in this version; technical clauses are never translated |
| `schedule_format`, `specification_format` | Required defaults `xlsx` and `pdf` |
| `source_reference_visibility` | `compact` or `detailed`; citations cannot be disabled |
| `optional_context` | Explicit roles `boq/electrical/bms/drawing`; separate optional worksheet, default empty |
| `include_missing_information` | Must remain true |
| `essential_parameters` | Explicit saved parameter names expected for this requested scope; missing values are reported, never designed |
| `location_parameter_names`, `area_parameter_names`, `quantity_parameter_names` | Explicit recognized saved field names; original values and citations retained |
| `specification_rules` | Explicit section selection rules; empty means no automatically selected supplier clauses |
| `max_equipment` | 1..10000, default 500; oversized scopes fail visibly |
| `max_supplier_clauses` | 1..300, default 60; oversized selections fail instead of truncating |
| `status` | `draft` only |
| `docx` | false by default; additional Word export only on explicit true |

Physical quantity is always UNKNOWN in this reader version: approved physical-count basis is not exposed/revalidated by EvidenceReader v1. Explicit schedule declarations are preserved separately with their evidence IDs and unapproved status. BMS controller/electrical panel quantities, annotation repetitions and matching pairs are never counted. A blank/printed placeholder remains missing while the original printed value remains visible. An equipment identity Type/Group/Reference is not promoted to Confirmed Instance.

## Specification rules

Every rule requires `section`, `discipline` and a plain `basis` explaining the explicit selection. Optional `families` restricts the rule. `evidence_ids` selects exact existing clause records; omitted means inspect all saved paragraph candidates in that explicit section. `title_evidence_id` identifies an exact saved heading fragment, providing a traceable section title. No keyword match creates applicability or an engineering confidence score.

`category` is one of:

- Directly Supported by Available Evidence.
- General Requirement.
- Candidate — Requires Review.
- Conditional — Requires Confirmation.

Directly Supported cannot be assigned over a saved Pending/unreviewed status; it is downgraded to Candidate (or Conditional when the saved relationship is conditional). A configured general requirement remains General with the original applicability status and condition intact. No category changes the underlying review state. Current source bytes also do not imply engineering approval.

Example rule structure (replace section/IDs with actual saved evidence):

```json
{
  "section": "ACTUAL_SECTION",
  "discipline": "Mechanical",
  "evidence_ids": ["EXACT_EXISTING_EVIDENCE_ID"],
  "category": "Candidate — Requires Review",
  "basis": "Explicit project/family selection based on saved section evidence; applicability pending"
}
```

The generator probes the total candidate count without expanding it. It traverses only configured section pages. Existing UC family+run scope is queried once per shared scope; missing run identity uses a separate reference rather than guessing equivalence. Exact duplicates collapse by original source/hash/section/page/whitespace-normalized text, retaining all provenance references. Same text in distinct sources/pages is not silently merged.

Negative filters exclude non-requirement classifications, empty fragments, covers, structural headings, revision/page footers and manufacturer-list/context rows. A manufacturer's technical qualification paragraph may remain a source requirement; a manufacturer list is not a supported equipment selection. Incomplete citations and unselected uncertain paragraphs within inspected sections are placed in the internal review list. Other sections remain explicitly unqueried, not approved or exhaustively rejected.

Clauses require a registered original source ID/version/hash and actual physical PDF page. A DOC/DOCX original also requires a distinct derived-PDF identity. Missing citations are internal review blockers. Original clause wording is preserved; section order and saved physical page/position order are retained. Only the stored clause/paragraph number is printed; full parent hierarchy and revision verification are not inferred when the reader does not expose them.

## Output contract

Compilation version: `mep-supplier-draft/1`. Each family has equipment, all selected schedule parameter rows, issues, specifications, optional context and internal specification-review records. Every exported parameter/clause references an internal audit entry containing its full saved fact and EvidenceReader provenance, including original/derived identities, hash, revision as recorded, locator, evidence ID, relationship/review and source currency/dependency impact. Project-level source limitation audits are retained separately and are not assumed equipment-specific.

Content fingerprint is SHA256 of canonical compilation JSON. Generation receipts use `mep-supplier-render-receipt/1`, with separate variable generation time and actual exported-file hashes. Determinism covers compilation and logical supplier cell/text content for the same database snapshot, options and explicit currency assessment. ZIP timestamps/Excel file metadata, runtime-generated package identifiers and receipt generation metadata are not a binary determinism guarantee. PDF rendering uses invariant metadata and can be byte-compared in bounded validation.

Each stored-family subfolder has exactly two default supplier documents:

1. `Equipment Technical Schedule.xlsx`: Equipment, Parameters, Outstanding and Specifications index worksheets; optional context only if requested. Frozen headers/identifier column, filters, literal printed values, compact source references and clear draft/missing status.
2. `Equipment Technical Specifications.pdf`: selected exact clauses once per family, source filename, physical-page basis, stored clause, category, original applicability state and concise outstanding information.

Both identify **DRAFT — FOR TECHNICAL REVIEW**. Missing data additionally identifies **INCOMPLETE SOURCE DATA — ENGINEERING CONFIRMATION REQUIRED**. These are not approved submissions or RFQs.

The `internal` subfolder holds `provenance-manifest.json` (`mep-supplier-provenance/1`), `specification-review.json`, previews and renderer inspection/logs. A root `internal` holds compilation/receipt. These are audit artifacts, not additional supplier reports. Full lineage stays internal; compact source-ref IDs resolve there. If DOCX is explicitly requested it is an additional output, not a default third report.

## Known gaps and validation scope

- No direct SQL is used by this generator. Unsupported domains/contract mismatches are explicit gaps/errors from the reader contract.
- EvidenceReader v1 does not certify active approved physical quantities, current entity/match review bases, verified contractual revisions or complete parent-clause hierarchy. Those remain UNKNOWN/unverified, with original decisions/values preserved.
- General/conditional requirements do not replace missing equipment-specific mechanical data or a dedicated specification.
- Output is English only. An individual saved fact may be long; collection limits are explicit, not byte limits.
- Bounded AHU/Chiller pilot exports use a consistent DB copy. They validate compilation, rendered values, provenance, status, logical determinism and preservation, not the complete engineering workflow or procurement fitness.
- DOCX, nondefault optional-context/detailed-column render modes and other future-project schema variants are not all runtime-validated by these two default pilots.

For later installation updates, compare current source/destination hashes, preserve installation-specific path/routing extensions and back up changed files. Do not reset checkpoints or change specialist skills, native agents/models, project SQLite or original sources. The master code signature changes; preserve existing history and use the established prerequisite compatibility mechanism only when explicitly authorized.
