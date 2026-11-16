---
name: data-lineage-tracker
description: Use when tracing MEP equipment or requirement records to exact documents and source locations, verifying archived evidence, or recording reviewed corrections without replacing original extraction results.
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
---
# MEP evidence lineage and review

Run `scripts/lineage.py` by absolute path with the Codex Python runtime. This skill requires the sibling project `etl-pipeline/scripts/mep_store.py`; consult its `references/data-contract.md` for version/review semantics. No network services or API keys are required.

## Inspect first

`inspect --db <project.sqlite> --record <record-id> [--output <new.json>]` returns original evidence and locators, document identity/revision/hash, extraction runs/issues, archived-file hash verification and complete review history. Missing pages, clauses, coordinates and other facts stay null.

Compare the actual evidence before resolving a discrepancy. A PASS label, extraction guess, or synthetic reviewer name is not approval. If `evidence_verified` is false, report suspected loss/tampering and stop relying on that archived file until reconciled. Hash verification authenticates retained bytes, not the engineering truth of their content.

## Append review events

After the user supplies or authorizes an actual disposition, run:

`review --db <project.sqlite> --record <id> --reviewer <name> --decision <approved|rejected|needs_review> --reason <reason> [--field <field> --value-json <JSON-value>]`

An optional field/value records a corrected interpretation, not a modification of the original text, data or source. Explicit JSON null clears an interpretation. Preserve conflicting decisions in order; do not present an earlier approval as current after a later request for further review. Identify which field and evidence a disposition covers; approving one field does not approve the whole system.

Review and revision activation are separate. Use ETL `activate` only after a replacement revision has been selected. This is an audit log, not automatic conflict resolution, authentication or RFQ approval. Output files refuse overwrite. Inspecting an unknown database fails without creating it.
