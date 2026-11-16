# CLI and Codex invocation

Commands below are documentation, not executed examples. Resolve Python with `load_workspace_dependencies` in Codex. Use the installed absolute `scripts/master.py`. No runtime install or network is needed by the master itself (Python 3.10+); existing downstream dependencies must be present.

```powershell
$mepPython = '<actual dependency-loader Python>'
$mepMaster = '<repository>/.agents/skills/mep-project-master/scripts/master.py'
$mepConfig = '<project>/rules/master.json'
& $mepPython -X utf8 -B $mepMaster init --project-id '<actual ID>' --project-name '<actual name>' --source '<source directory>' --database '<existing or explicitly new state/engineering.sqlite>' --output '<dedicated outputs>' --skills-root '<repository>/.agents/skills' --write-config $mepConfig
& $mepPython -X utf8 -B $mepMaster --config $mepConfig discover
& $mepPython -X utf8 -B $mepMaster --config $mepConfig plan
& $mepPython -X utf8 -B $mepMaster --config $mepConfig start
& $mepPython -X utf8 -B $mepMaster --config $mepConfig status
& $mepPython -X utf8 -B $mepMaster --config $mepConfig resume
```

All global `--config` flags precede the command. `init` creates only a master config and refuses overwrite. Adapt the sibling skills' actual rule templates into separate registry/matching/review/package configuration files, then name them in master config. The master does not translate arbitrary naming/tag/unit rules into undocumented APIs. Those actual config files are hash-tracked. The example's empty task lists and null coverage are deliberate: actual worksheets, columns, file IDs and scope must be inspected before tasks can be configured.

`start`, `run`, `resume` share the same incremental engine. `--stage 03` requests exactly that stage; prerequisites must still be current. Guided mode stops after one newly completed stage. Existing completed current stages are verified and reused before advancing. Set `execution_mode: automatic` explicitly to continue consecutive eligible configured stages. An instruction-only task can be completed by Codex without asking the user to approve routine profiling; checkpoint then resume that same stage. Stop for the human at the major stage boundary in Guided Mode.

```powershell
& $mepPython -X utf8 -B $mepMaster --config $mepConfig files
& $mepPython -X utf8 -B $mepMaster --config $mepConfig review-equipment --tag AHU-003
& $mepPython -X utf8 -B $mepMaster --config $mepConfig search --query 'chilled water'
& $mepPython -X utf8 -B $mepMaster --config $mepConfig reviews
& $mepPython -X utf8 -B $mepMaster --config $mepConfig readiness
& $mepPython -X utf8 -B $mepMaster --config $mepConfig checkpoint --stage 02 --job '<configured task ID>' --receipt '<actual receipt.json>'
& $mepPython -X utf8 -B $mepMaster --config $mepConfig decision --request '<reviewed actual decision.json>' --human-authorized
& $mepPython -X utf8 -B $mepMaster --config $mepConfig packages --mode draft --category '<actual pump category>'
& $mepPython -X utf8 -B $mepMaster --config $mepConfig packages --mode approved --entity-id '<actual reviewed entity>'
```

`packages` creates an explicit stage-10 task for that invocation; the request and configuration are preserved in SQLite. It still needs stage-10 source coverage declared in master config and valid stage 08. Approved requests check and record the existing upstream readiness for the exact requested category/entity scope; this does not declare all other equipment approved or complete the whole project's stage 09. Sequential approved workflow requires stage 09. An explicit draft request can proceed without stage 09. Never silently label only a subset as all eligible equipment. Category aliases must be from actual package configuration, not an assumed pump catalogue. The underlying generator remains final readiness authority.

`review-equipment` requires all upstream schemas so its read-only facade can project current technical records. Before those exist, use `files`/`search` and the already available upstream source tools; a missing schema is not initialized by a query. `reviews`/`readiness` return current gate reasons, not an authentication or approval UI. `status` historical issue counts are labeled historical; do not present them as the number of open current cases.

```powershell
& $mepPython -X utf8 -B $mepMaster --config $mepConfig scope --id chilled-water --system 'Chilled Water' --file-id '<drawing ID>' --file-id '<schedule ID>' --file-id '<shared spec ID>' --entity-id '<reviewed equipment ID>' --write-config '<project>/rules/chilled-water.json'
```

The scope command writes a separate configuration with fresh task/coverage declarations, sharing the same engineering DB. It does not guess system membership from filenames. Include applicable electrical/BMS/shared requirements too. Current global upstream CLIs cannot isolate a system when unrelated imports already exist; the master blocks those operations and reports this interface limit. No new competing DB is created as a workaround.

User-facing prompts:

- `$mep-project-master Start a new MEP project from the provided directory using Guided Mode.`
- `$mep-project-master Resume the existing project from the last valid checkpoint.`
- `$mep-project-master Show completed, stale, blocked stages and outstanding engineering reviews.`
- `$mep-project-master Retrieve and review all source information for AHU-003.`
- `$mep-project-master Process the Chilled Water System only.`
- `$mep-project-master Generate draft technical packages for all eligible pump equipment.`

Native delegation examples (no new Python CLI commands):

- `$mep-project-master Use document_extractor for these prepared schedule excerpts only; return source-linked findings without running stages.`
- `$mep-project-master Use cad_analyst to review the supplied CAD-export candidates; no native DWG conversion or database writes.`
- `$mep-project-master Use equipment_matcher to investigate these existing identity proposals; recommendations only.`
- `$mep-project-master Delegate this technical comparison to conflict_analyst. Keep engineering decisions pending human review.`
- `$mep-project-master Resume in Guided Mode with delegated workflow execution. Use at most two read-only specialists when useful, retain deterministic processing, and wait after each newly completed major stage. Do not use critical_reviewer without my separate permission.`

Manual delegation is default; a normal start/resume prompt does not request subagents. For single-agent execution, explicitly say "do not spawn subagents." Specialist-only requests do not start a full pipeline. Read [delegation](delegation.md) for all six actual configured names, supported host dispatch/fallback, model settings, source-linked results and existing checkpoint acceptance. Settings are configured/static-checked only; no native-role load, agent spawn or model inference has been verified.

Exit codes: 0 successful query/operation; 1 saved stage BLOCKED/FAILED; 2 invalid config/interface/runtime failure; 130 interruption. Full child stdout/stderr remains in the immutable attempt folder. Summarize counts/status/path/next action concisely instead of loading complete extraction/specification JSON into context.
