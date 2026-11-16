# Release verification — 2026-11-16

## Executed

- Full generic procurement fixture against the installed user-global Master: PASS.
- Same fresh fixture against the portable repository copy: PASS.
- All 9 focused procurement unit tests against the repository: PASS.
- Skill Creator quick validator for the Master: PASS (local validation-only PyYAML).
- All 15 sibling routes discovered as available with the supplied Python runtime.
- All 16 skills are included. The published edition uses English documentation
  and messages; multilingual input aliases are preserved as Unicode escapes.
- Python syntax (77 files), JSON (24 files), TOML (7 files): parsed successfully.
- Internal relative Markdown links: no missing targets.
- Package scan: no local user paths, historical project names, real project
  source files/databases or recognized credential patterns were found. This is a
  bounded content scan, not a claim of exhaustive security review.

The integration fixtures create BOQ, calibrated ASCII DXF geometry, specification
PDF, schedule and unreadable-source samples. They invoke the actual CLI and check
SQLite plus generated Excel and Word contents. They verify 37/40 close under the
configured tolerance, 370/40 discrepancy, 36 m partial, separate verified risers,
duplicate views, wrong units/scope, unsupported curves, field-level choice after
resume, header units, unresolved issue blocking, explicit exclusion, source reuse
and disclosed selection omissions. Each fresh fixture ends with 59 core records,
5 extraction runs and 3 persisted geometry-check events; unchanged resume adds no
duplicate extraction work.

## Scope limits

No historical engineering project was opened. Native model delegation and the full
legacy Mechanical/Electrical/BMS workflow were not exercised. Direct DWG and the
other documented geometry limits remain. This release pass checked new Office
files structurally and by content; previous samples from the same document
renderer were visually reviewed in native Office. No new full visual certification
is claimed. Supplier messaging and n8n execution remain outside scope.

The English publication edition passed the same 9 focused tests and the fresh
full procurement fixture, including actual Excel and Word content inspection.
