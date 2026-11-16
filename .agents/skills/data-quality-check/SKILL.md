---
name: data-quality-check
description: Use when checking extracted MEP equipment schedules, BOQs, drawings and specification facts for missing tags or parameters, conflicting quantities or units, and cross-discipline discrepancies requiring engineering review.
metadata:
  variant: project-mep-local
  source-repository: https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction
  source-commit: 410ed1e71e4a5c6fd231afd0c8d1e586a9f546e8
---
# Evidence-linked MEP quality checks

Run `scripts/check_quality.py <package.json> [more-packages.json ...] [--config <project-rules.json>] [--output <new.json>]` using the Codex Python runtime. Only standard-library modules are needed. Packages follow `mep-evidence/1`; read [comparison rules](references/comparison-rules.md) before mapping facts or claiming a discrepancy.

Checks include missing/invalid equipment tags, required parameters, explicit quantities, missing equipment between comparable supplied inventories, scoped specification conflicts, repeated mentions, unknown units and configured cross-discipline dependencies. Supported discipline labels are HVAC, Plumbing, Fire Fighting, Electrical and Low Current. Map BMS or project-specific names explicitly; do not silently assign disciplines.

## Compare comparable evidence

Supply actual scope, discipline, equipment tag and role when available. Select the intended document revisions before checking; this command does not decide which revision is current. Cross-document comparisons require an explicit equal scope. Without it, checks stay within the same source bytes. Role distinguishes drawings/schedules/BOQs/specifications. A drawing tag occurrence is not a physical quantity or a complete inventory. Repetition produces a review finding, never a takeoff count.

Parameter facts use `data.parameters` entries with name/value/unit, or `kind: parameter` with those fields in data. Only comparable dimensions and equality operators are equated. A small explicit conversion table handles known units; unknown units remain unresolved. No voltage, density, motor efficiency, arbitrary tolerances or engineering requirements are inferred.

## Interpret output

Every finding is a candidate linked to exact input document/source locations and zero-based input record indexes. Missing-equipment findings mean absent from the supplied comparable inventory, not proven absent from the building. `no_findings_in_checked_subset` is not approval, completeness or verified design correctness. Qualitative requirements remain source paragraphs for manual review; this script does not interpret all specification language.

Keep the inputs and raw evidence unchanged. Use `data-lineage-tracker` to record an actually supplied engineering disposition. This skill does not resolve conflicts, approve equipment, generate procurement decisions or use external services. Output files refuse overwrite.
