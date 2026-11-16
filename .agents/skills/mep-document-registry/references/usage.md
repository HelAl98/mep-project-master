# CLI and configuration

All paths below are examples to replace with real input/output locations. The CLI has no hardcoded user paths. Use an installed Python with the documented local dependencies; in Codex obtain that interpreter from the workspace dependency loader. From the project directory:

```powershell
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py --help
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py scan --root "D:/Project Inputs" --db "D:/Project State/engineering.sqlite" --project-id "project-01"
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py rescan --root "D:/Project Inputs" --db "D:/Project State/engineering.sqlite" --project-id "project-01"
```

`--db` and `--project-id` are optional for scan/rescan. Default IDs are stable internal keys derived from the canonical project root; they are not official project numbers. An explicit ID cannot silently be assigned to another root. Database discovery looks for schema-v2 engineering databases; ambiguity stops with a list of candidates and requires `--db`. It never migrates an unrelated database. If none exists, state is created in `<source-root>/.mep-registry/engineering.sqlite`.

Scan/rescan generates a fresh dedicated report directory beside the selected database. Use `--output <new-directory>` for a specific output path or `--no-export` for registration only. Existing report directories are refused; no overwrite flag exists. `--fail-on-error` makes per-file parsing/registration errors produce exit code 1 after writing available reports. Usage/config/database errors produce 2; interruption produces 130. Normal safe continuation reports errors and `completed_with_errors` in JSON. The CLI prints UTF-8 JSON.

```powershell
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py issues --db "D:/Project State/engineering.sqlite" --project-id "project-01"
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py show --db "D:/Project State/engineering.sqlite" --project-id "project-01"
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py show --db "D:/Project State/engineering.sqlite" --project-id "project-01" --history
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py search --db "D:/Project State/engineering.sqlite" --project-id "project-01" --query "M-101"
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py export --db "D:/Project State/engineering.sqlite" --project-id "project-01" --output "D:/Reports/register-issue-02"
```

`issues` lists unresolved issues; `--all` includes resolved/invalidated entries. `show --history` retains original observations and revision candidates from old source versions. Search is literal FTS5, defaults to current source analyses, and accepts `--history` and `--limit`. Search returns original `value` separately from reviewed `current_value`. It is not semantic search and does not use embeddings.

## Engineering review

Use IDs from `show`/JSON reports. Supported target/decision pairs:

| Target type | Decisions |
|---|---|
| file | confirm_identity |
| revision | approve_applicability, supersede |
| relationship | confirm_relationship, reject_relationship |
| observation | correct_metadata |
| issue | resolve_issue, reopen_issue |

Every decision requires `--actor` and `--reason`. They record a supplied identity; the local tool does not authenticate a reviewer or grant approval authority. Do not invent an engineer or reason. Only observation correction accepts `--value-json`, a scalar JSON value, including explicit null. Corrections do not rewrite source text, coordinates or archived bytes.

```powershell
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py review --db "D:/Project State/engineering.sqlite" --project-id "project-01" --target-type revision --target-id "<revision-id>" --decision approve_applicability --actor "<actual reviewer>" --reason "<actual reviewed basis>"
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py review --db "D:/Project State/engineering.sqlite" --project-id "project-01" --target-type revision --target-id "<old-revision-id>" --decision supersede --actor "<actual reviewer>" --reason "<why this issue no longer applies>"
```

Approval applies only to its exact named file/sheet revision. It does not approve every revision with a similar name or automatically supersede another record. Source changes produce new analysis/revision IDs and do not inherit prior approval. Proposed relationships never become confirmed through filename similarity. A relationship based on replaced/excluded source evidence or corrected identity is invalidated; review its current proposal instead. CAD export metadata is never transferred into a DWG identity solely because files resemble each other.

## Project rules

Copy/edit `assets/project-rules.example.json` outside source report output, then pass `--config`. Rules have an ID, regex pattern, target (`filename`, `relative_path`, `content`), constant `fields`, and optional named-group `captures`. Use forward slashes for relative-path patterns. Path/name rules remain filename-derived; content classification rules remain inferred. Literal labeled contents outrank them. Unknown conflicting fields project to null with candidates retained. A bare filename stem remains only a candidate, not a verified document title.

Disciplines include HVAC, Plumbing, Fire Fighting, Electrical Power, Lighting, Low Current, Fire Alarm, BMS, Other MEP and generic Mechanical/Electrical labels where explicitly present. Category aliases cover drawings, specifications, BOQ, equipment/material schedules, general notes, scope of work, design reports and correspondence. No unknown value is silently coerced into a technical discipline. `revision_order` is an explicitly supplied ordering convention; ordering only proposes newer candidates, not contractual approval.

Limits are positive integers. Oversized files still register their bytes/hash but metadata extraction becomes pending. Limits on PDF pages, Office rows/columns, text length and uncompressed ZIP size generate visible review issues. Relationship discovery groups by identifiers/hashes/names rather than comparing unrelated document pairs; `max_relationship_pairs` bounds each file/sheet candidate pass and reports incomplete relationship discovery when reached. No source file is discarded to satisfy that limit.

## Outputs and exclusions

The new report directory contains `document_register.xlsx`, `document_relationships.md`, `document_relationships.json`, `issues_for_review.json`, and `registry_summary.json`. The JSON summary retains the full snapshot/provenance and any values exceeding Excel display limits. Files/sheets and issue/registry/review statuses are separate. All spreadsheet strings are literal, including values beginning with formula characters. No macros or links are executed.

Directories marked `.mep-registry-output.json`, including incomplete exports, are skipped. Database files/journals, the evidence archive, `.mep-registry`, tool metadata directories and explicit exclusion globs are not ingested. Sources are never renamed/moved/deleted. Missing files remain in history, with retained exact archives and review issues. Hashes are recomputed on rescans; metadata extraction is reused only for identical bytes and extraction/config fingerprints.

## Synthetic demonstration

```powershell
python -X utf8 -B .agents/skills/mep-document-registry/scripts/registry.py demo --output "./synthetic-registry-demo"
```

The directory must not exist. Fixtures are prominently synthetic, including a deliberately unparsed DWG placeholder. The demo registers independent/multi-sheet revisions, records one explicit synthetic approval, rescans idempotently, and exports reports. This demonstrates workflow, not CAD conversion or real engineering verification. Do not use these values/decisions in real project output.
