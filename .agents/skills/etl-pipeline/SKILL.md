---
name: etl-pipeline
description: Use when incrementally ingesting MEP PDF evidence, mapped equipment schedules or BOQs into a local SQLite database, reconciling revisions, or searching preserved source records with SQLite Full Text Search.
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
---
# Local MEP evidence pipeline

Use `scripts/mep_store.py`; read [the data contract](references/data-contract.md) before preparing an adapter or interpreting stored results. Resolve scripts relative to this SKILL.md and use the Codex Python runtime from the workspace dependency loader. Storage uses standard-library SQLite with FTS5. PDF page-bound validation uses pypdf; mapped XLSX intake uses openpyxl. No API keys, price enrichment, Airflow, ERP, or supplier communication are included.

## Operations

- `tabular --input <xlsx-or-csv> --mapping <mapping.json> --metadata <metadata.json> --output <package.json>` creates a `mep-evidence/1` package. Supply exact column headers and the worksheet name for XLSX. Preserve cell formulas; never treat unevaluated formulas as verified quantities. CSV is UTF-8; this adapter does not read legacy XLS.
- `ingest --db <project.sqlite> --package <package.json>` validates source bytes and references, archives the source, and appends observations. Use one database per project. Results include record/version IDs, review issues and new-record count.
- `search --db <project.sqlite> --query <literal-phrase> [--active-only]` performs FTS5 phrase search. Default results include historical versions; state the mode when presenting results.
- `activate --db <project.sqlite> --version <id> --reviewer <name> --reason <reason>` appends a revision-selection event. Obtain the actual user's disposition before selecting a replacement version. Revision names are not assumed sortable.

Run `--help` for details. Output packages refuse overwrite. The first observed version becomes the active working version, still unreviewed. Further revisions remain inactive until explicitly selected. Same document/revision with different bytes is flagged rather than overwritten. Without a supplied project document ID, identity is path-based and moved/renamed sources need manual reconciliation.

## Review and boundaries

Use the sibling `data-lineage-tracker` for review events and corrections, and `data-quality-check` for proposed findings. Keep unknown document IDs/revisions null. Do not convert tag mentions into physical equipment counts or approve data from extraction confidence. SQL evidence/history tables are append-only; archive hashes detect tampering. This is logical immutability, not OS-level WORM storage or authentication.

These are tested local ingestion primitives. They do not automatically orchestrate a complete project, resolve conflicts, approve engineering decisions, generate approved RFQ folders, or install `rag-construction`.
