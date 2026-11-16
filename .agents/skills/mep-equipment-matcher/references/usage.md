# CLI and review

Implementation is authored but **not execution-tested**. These commands were not run. No project database was migrated in this delivery.

## Environment and existing registry

Python 3.10+, FTS5 SQLite, openpyxl, pypdf and pdfplumber are required. Existing runtime dependencies were not reinstalled. ezdxf is optional and currently unavailable. In Codex resolve Python using the workspace dependency loader; outside Codex use an equivalent local environment.

From the project directory, set real selected paths:

```powershell
$matcherPython = 'python'
$matcherScript = '.agents/skills/mep-equipment-matcher/scripts/matcher.py'
$matcherDb = 'D:/MEP Project/State/engineering.sqlite'
$matcherProject = 'actual-registered-project-id'
$matcherConfig = 'D:/MEP Project/Rules/equipment.json'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig --help
```

Replace `python` with the dependency-loader interpreter if needed. Global flags go **before the command**. The first actual command installs equipment migration 1 into the existing database if absent; even `show` can initialize equipment tables. Missing databases, unknown projects and incompatible schema versions are refused. Back up the database and its adjacent evidence archive together before first real use. Get actual file IDs and revision dispositions through the existing registry.

## Intake

```powershell
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig extract --file-id '<registered-drawing-file-id>'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig import-schedule --file-id '<schedule-file-id>' --mapping 'D:/Rules/schedule.json' --role schedule --slot 'schedule-main'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig import-schedule --file-id '<boq-file-id>' --mapping 'D:/Rules/boq.json' --role boq --slot 'boq-main'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig import-cad --file-id '<actual-xlsx-export-file-id>' --mapping 'D:/Rules/cad.json' --slot 'cad-elements'
```

Without a file ID, `extract` selects registered PDF/DWG/DXF documents classified as drawings. It prefers one existing extraction run for the exact registered source; ambiguous SQL runs require `--run-id`. PDF fallback uses existing local helpers. Native DWG never runs a converter. Optional DXF reads INSERT attributes only.

`import-schedule` supports XLSX/CSV and explicitly selected PDF tables. Roles: schedule, boq, electrical, bms, register, drawing. Electrical/BMS roles represent references to supplied/controlled equipment by default. Exact column headers and actual page/table/row references are required. Adapt the examples, removing absent columns; no schema guessing occurs.

```powershell
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig import-json --file-id '<original-source-file-id>' --input 'D:/Evidence/equipment.json' --role schedule --slot 'structured-main'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig import-sql --file-id '<registered-file-id>' --run-id '<existing-extraction-run-id>' --role specification --slot 'spec-paragraphs'
```

JSON requires the exact original registered source SHA-256, not its transport JSON hash. Arbitrary SQL is not accepted. Existing SQL records remain unchanged and retain original IDs. Existing document/core review events are preserved but are not silently promoted into equipment approvals.

A stable import slot identifies one adapter view, such as a worksheet/PDF table. Reuse it for new mappings; use separate slots for intentionally separate tables. The latest import per current file/slot is active. Source/config/mapping/helper fingerprints control reuse. Source changes require registry rescan and reimport. Replaying an older exact signature does not roll back a newer import; no implicit import activation command exists.

Use the same config throughout. After changing aliases, units or category rules, reimport current sources before matching; mixed import configs are refused by `match`. Source bytes are read from verified archives, with isolated suffix-bearing copies where existing helpers need them. Original files remain untouched.

## Inspect and group

```powershell
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig match
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig unmatched
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig conflicts
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig show --id '<occurrence-entity-or-cluster-id>'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig show --history
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig search --query 'CHWP-003'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig group --by type
```

Grouping accepts type/category/location. Technical signatures preserve supplied parameters, motor/duty distinctions and mandatory material fields. Type proposals do not certify engineering equivalence. Category/location groups are packages. FTS5 is literal lexical search of current observations and indexed reviewed aliases, not semantic retrieval. Historical aliases can retrieve the current record, whose original and current fields remain distinguishable.

## Engineering dispositions

Use current IDs and an actual authorized reviewer/reason. The following values are placeholders, not actual approvals:

```powershell
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig review --target-kind match --target-id '<match-id>' --decision confirm --actor '<actual engineer>' --reason '<reviewed identity evidence>'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig review --target-kind entity --target-id '<instance-entity-id>' --decision confirm_instance --actor '<actual engineer>' --reason '<basis for one physical item>'
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig review --target-kind occurrence --target-id '<occurrence-id>' --decision correct --actor '<actual engineer>' --reason '<reviewed correction basis>' --value-json '{"floor":"L02"}'
```

| Target | Decisions |
|---|---|
| match / relationship | confirm, reject |
| entity | confirm_instance, confirm_type, confirm_group, reject; must match entity kind |
| occurrence | correct with supported scalar field changes |
| parameter | correct with value/unit, approve_value, reject_value |
| issue | confirm_discrepancy, resolve, not_applicable, reopen |

Corrections accumulate fieldwise while retaining original observations. Match confirmation, physical-instance identity, source revision applicability and parameter approval are independent. A confirmed identity cluster contributes one physical item only after explicit instance confirmation; this is not contractual quantity certification. Source applicability/supersession is reviewed through the document registry.

Blocked identity matches need conflicting observations corrected first. Type confirmation needs configured material fields and numeric unit evidence. Stale/foreign targets are refused. Source/config/registry decisions or equipment corrections invalidate the dataset's prior matching run conservatively. Regenerate matching/grouping and review current IDs. Reviewer identities are recorded without authentication.

## Exports and error handling

```powershell
& $matcherPython -X utf8 -B $matcherScript --db $matcherDb --project-id $matcherProject --config $matcherConfig export --output 'D:/MEP Project/Reports/equipment-issue-01'
```

The fresh directory contains `equipment_master_register.xlsx`, `equipment_matching_review.json`, `equipment_summary.json`, and a completion marker. Workbook sheets: EquipmentMaster, SourceMapping, Occurrences, Matches, ReviewIssues, Associations, TypesAndGroups, Quantities, ReviewHistory. JSON preserves long/raw values exceeding Excel cell limits. All strings remain literal spreadsheet text. Export reads stored records/projections, marks stale matching explicitly, and creates a registry-compatible exclusion marker before writing other files. Existing output is never overwritten.

CLI output is compact UTF-8 JSON. Exit codes: 0 completed command, 1 per-file extraction errors with persisted issues, 2 validation/runtime error, 130 interruption. Completed imports remain committed; incomplete transactions roll back. Partial extraction is never proof of absent equipment.
