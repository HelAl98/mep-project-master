# Validation scope and compatibility

The generic procurement integration test exercises the actual Master CLI, native
Registry/ETL, SQLite reuse, unit retention, field choices after resume, bounded
ASCII DXF LINE geometry, partial coverage, material discrepancy and issue gates.
It opens and checks generated XLSX/DOCX contents. Prior samples were rendered by
native Office and visually inspected. Reproducible commands are in the repository
README. These checks do not validate every legacy stage, specialist dispatch,
every CAD entity or complete Mechanical/Electrical/BMS design review.

The following is retained historical authoring context for legacy integration,
not a statement that the current procurement route has never been exercised.

# Execution deferred; compatibility assumptions

No pytest/unit/integration/regression suite, synthetic fixtures, demo pipeline, real ingestion, database migration, benchmark, generated sample document, import probe, bytecode compilation, skill quick-validator or command smoke run was executed during authoring. Files were inspected as source; installation/file hashes establish packaging only. Do not describe this integration as tested or production-validated.

The pre-existing matcher, reviewer and package generator were themselves delivered with execution validation deferred. Their actual source and CLI usage were inspected for this adapter. Remaining practical assumptions include:

- SQLite table names, row-ID fields, project scoping and core/registry/eq/tr version ledgers stay at the inspected versions; changes require explicit compatibility review.
- Upstream CLI response IDs/shapes and read-only facade contracts remain compatible. Unknown responses fail completion instead of silently accepting a zero exit code.
- Module presence does not prove version compatibility, FTS5 support, parser completeness, formula correctness or rendering. Native CAD exporter/OCR are unavailable; optional DXF behavior depends on installed upstream support.
- Source hashes and immutable audit history prove retained bytes/events, not engineering correctness or authenticated reviewer authority.
- Any extraction issue/warning is conservatively blocked from completing its declared full scope. This can require narrower evidence scope or a real source correction/review; no silent warning suppression is implemented.
- Source-local extraction reuse is precise when explicit file IDs and artifact dependencies are configured. Derived review invalidation is conservative; not every source-to-equipment dependency is available for minimal invalidation.
- Original instruction skills still need Codex to perform actual profiling/authoring and provide inspectable artifacts. They cannot be auto-invoked as Python agents. Automatic mode continues deterministic steps and Codex may handle instruction steps within scope, but human approvals are never automatic.
- System-only global matcher/reviewer execution is unavailable when other imports exist in the same DB. This is an explicitly enforced upstream limitation, not a claimed implemented filter.
- Recovery is serialized by a filesystem lock and SQLite short transactions. Stale locks after abrupt termination require actual process/attempt inspection. Child termination, power-loss recovery, WAL/backup, Windows path behavior, large-file timing and interruption boundaries remain unvalidated.
- Output checksums prove existence/provenance; OOXML/PDF pagination, fonts, RTL behavior, source link usability and actual visual quality need future authorized render review. Generator is English-first; no automatic PDF or Arabic rendering claim.

On the first authorized real-project workflow, begin in Guided Mode, inspect the configuration and dependency report, back up the shared DB/archive, then process only the intended first stage. The future operator should explicitly authorize practical validation then. This document does not authorize any test or project processing now.
