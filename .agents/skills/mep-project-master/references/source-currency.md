# P1-01 Source currency and saved change impact

Use `scripts/master.py --config <absolute master.json> source-currency --output <new report.json>`. Resolve the interpreter with the workspace dependency loader and use absolute scripts with `-X utf8 -B` on Windows. Output is optional, with JSON on stdout by default. The existing project config supplies registry project identity, original source root, DB and output root. The command supports an unavailable source root so registered missing originals can be reported.

The module `scripts/master_project/source_currency.py` reuses the existing query-only connection/identity checks and registry head query. It starts a read transaction, denies write authorization, and closes through rollback. It does not initialize a Store, call migrations, invoke extractors/matching, append checkpoints or approve revisions. Reports are newly created files outside original sources and the installed master. Exit 0 means assessment completed, not that every source is CURRENT. Invalid config/connection/report path errors retain the standard CLI error handling.

## Currency

- CURRENT requires the recorded source identity/path and SHA256 to match readable original bytes.
- MODIFIED means original bytes differ from the registered SHA256.
- MISSING means the registered original path is unavailable.
- UNVERIFIED covers unreliable/malformed identity/hash, permission/IO errors, non-files and a file changing while read. The optional `--max-source-mb` limit also produces UNVERIFIED when exceeded.

Files are hashed in chunks with handle/path identity/size/mtime checks. Windows ctime is compared within the same handle only because path-stat and handle-stat can expose different semantics. This detects observed races, not an atomic filesystem-wide snapshot. The DB snapshot and original-file check times are distinct. Hash-only assessment does not prove engineering truth or revision approval.

Original archive locations are taken from recorded versions. Archive bytes are checked for MODIFIED/MISSING originals only, and archive comparison is reported separately. Other archives have NOT_CHECKED, so CURRENT never claims an archive-content verification that did not occur.

## Dependency contracts

The report preserves actual SQL row IDs, JSON pointers and direct dependency edges. Supported existing relations cover versions/analyses, extraction runs/records, equipment imports/occurrences/parameters, entity-source membership, optional reviewer imports/requirements, and existing optional `uc_*` consolidated profiles/context/specification evidence. DOC-to-PDF extraction versions can trace original IDs through preserved supplied metadata. Unsupported/missing extensions supply no invented relationships.

Saved master events/operator receipts/packages and existing JSON evidence/manifests are inspected by exact known IDs and registered/installed artifact paths. No filename similarity, tag similarity, discipline assumption or hash-only identity guessing creates a dependency. Co-listed outputs are not each other's inputs. Declared producer-output edges require a saved input basis. Nested source-artifact lists are treated as input evidence, not generated outputs. Explicit exclusions and full registered-head inventories are retained as context, not positive consumption relations.

Impact statuses are POTENTIALLY_OUTDATED for a recorded path to a MODIFIED/MISSING source, UNKNOWN for missing/unverified provenance or an unverified source, and UNAFFECTED_BY_DETECTED_SOURCE_CHANGES for recorded paths whose sources remain current without recorded uncertainty. These are report projections only. Direct changed-source IDs and transitive roots are separate. UNAFFECTED is limited to recorded dependency paths and is not certification of complete provenance. Unknown reasons are displayed up to 25 per node, with their total count and direct parents retained for trace inspection.

Accepted Source Limitations remain visible as original audit payloads/IDs. Their host relations can be inspected without searching unavailable external Xrefs or retiring/re-approving an event. Existing full-stage states and scoped-operation eligibility retain their existing mechanisms. This phase does not alter the engine's cache invalidation policy or implement later roadmap items.

## Bounded output inspection

Only the configured project output tree is inspected. Historical `snapshots`, `backups` and `qa` subtrees and links escaping that tree are excluded from the current-output scan. JSON parsing defaults to at most 2,000 files and 32 MiB per file, configurable by `--max-json-files` and `--max-json-mb`. Limited/unreadable JSON remains UNKNOWN with a reported reason. XLSX/HTML/PDF/DOCX/ZIP files are inventoried as outputs, and dependency comes from saved provenance. Their contents are not re-extracted or regenerated.

Unlinked supplier/Excel/HTML documents may remain UNKNOWN, even when a nearby evidence file looks relevant. Missing lineage is a finding to report, not permission to infer a relationship. The report assesses all registered sources in the named project, including sources outside an HVAC-only study. It does not scan for unregistered new files or external reference restoration.

## Delivery and synchronization

This source-currency module is included in the release. When updating an installation, compare current hashes, preserve installation-path adaptations and back up destination files. The new module changes the existing master code signature. Reassess saved operational prerequisites through the existing compatible-upgrade process when needed, retaining prior checkpoint history. No checkpoint reset or implicit re-approval is authorized by this assessment command.
