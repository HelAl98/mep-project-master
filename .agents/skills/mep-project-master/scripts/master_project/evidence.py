"""Read-only fingerprints, persisted-output checks, coverage and engineering gates."""
import json
from pathlib import Path
from .common import sha, key, read, resolve
from .memory import tables


def current_files(memory):
    rows = memory.conn.execute('''SELECT f.id AS file_id,f.relative_path,s.version_id,s.analysis_id,s.status,v.sha256
        FROM registry_files f JOIN registry_scan_files s ON s.file_id=f.id
        LEFT JOIN versions v ON v.id=s.version_id
        WHERE f.project_id=? AND s.seq=(SELECT MAX(s2.seq) FROM registry_scan_files s2 WHERE s2.file_id=f.id)
        ORDER BY f.id''', (memory.cfg["project_id"],)).fetchall()
    return [dict(r) for r in rows]


def selected_files(memory):
    rows = current_files(memory)
    scope = memory.cfg["scope"]
    ids = set(scope.get("file_ids", []))
    if scope.get("system") and not ids:
        raise ValueError("System scope requires explicit registered file_ids including shared specifications/electrical/BMS sources")
    if ids - {r["file_id"] for r in rows}:
        raise ValueError("Scope includes unknown registered file IDs")
    return [r for r in rows if not ids or r["file_id"] in ids]


def source_fingerprint(cfg, memory=None, file_ids=None):
    # Intake hashes directory bytes every resume; it never skips from chat or mtimes.
    if memory is None:
        return key([(str(p.relative_to(cfg["source_directory"])), sha(p))
                    for p in sorted(Path(cfg["source_directory"]).rglob("*")) if p.is_file()])
    rows = selected_files(memory)
    if file_ids:
        if set(file_ids) - {r["file_id"] for r in rows}:
            raise ValueError("Job source_file_ids lie outside selected scope")
        rows = [r for r in rows if r["file_id"] in file_ids]
    values = []
    for row in rows:
        path = Path(cfg["source_directory"]) / row["relative_path"]
        normalized = dict(row)
        if normalized["status"] not in ("missing", "excluded", "error"):
            normalized["status"] = "present"
        values.append({**normalized, "live_sha256": sha(path) if path.is_file() else None})
    return key(values)


def database_signature(memory, include_reviews=True):
    # Project-scoped state only. No master tables, timestamps or unchanged scan IDs.
    conn, project = memory.conn, memory.cfg["project_id"]
    available = tables(conn)
    result = {}
    names = ["eq_imports", "eq_entities", "eq_matches", "eq_runs", "tr_imports", "tr_interpretations", "tr_runs"]
    if include_reviews:
        names += ["registry_reviews", "eq_reviews"]
    for table in names:
        if table in available:
            result[table] = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE project_id=? ORDER BY id", (project,))]
    version_ids = [r["version_id"] for r in current_files(memory) if r["version_id"]]
    result["core"] = []
    for version in sorted(set(version_ids)):
        for table, column in (("runs", "version_id"), ("reviews", None), ("activations", "version_id")):
            if table not in available:
                continue
            query = (f"SELECT id FROM {table} WHERE {column}=? ORDER BY id" if column else
                     "SELECT r.id FROM reviews r JOIN records d ON d.id=r.record_id WHERE d.version_id=? ORDER BY r.id")
            result["core"].append([version, table, [r[0] for r in conn.execute(query, (version,))]])
    return key(result)


def artifact(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Expected nonempty output: " + str(path))
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def valid_artifacts(payload):
    items = payload.get("artifacts", [])
    return bool(items) and all(Path(r["path"]).is_file() and sha(r["path"]) == r["sha256"] for r in items)


def valid_persisted(memory, payload):
    available = tables(memory.conn)
    files = {r["file_id"]: r for r in current_files(memory)}
    for ref in payload.get("persisted_refs", []):
        table = ref["table"]
        if table not in {"versions", "records", "runs", "registry_scans", "eq_imports", "eq_runs", "eq_entities", "tr_imports", "tr_mapping_runs", "tr_runs"} or table not in available:
            return False
        row = memory.conn.execute(f"SELECT * FROM {table} WHERE id=?", (ref["id"],)).fetchone()
        if not row:
            return False
        if table in ("eq_imports", "tr_imports"):
            file = files.get(row["file_id"])
            if not file or file["analysis_id"] != row["analysis_id"]:
                return False
            latest = memory.conn.execute(f"SELECT id FROM {table} WHERE project_id=? AND file_id=? AND slot=? ORDER BY rowid DESC LIMIT 1",
                                         (memory.cfg["project_id"], row["file_id"], row["slot"])).fetchone()
            if not latest or latest[0] != ref["id"]:
                return False
    return True


def persisted(memory, response, skill, command):
    """Check actual rows, not just child exit codes. Unknown response shape fails closed."""
    conn, available = memory.conn, tables(memory.conn)
    refs = []

    def exists(table, identity):
        if table not in available or identity is None or not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (identity,)).fetchone():
            raise ValueError(f"Expected persisted {table} row: {identity}")
        refs.append({"table": table, "id": identity})

    if skill == "etl-pipeline" and command == "ingest":
        exists("versions", response.get("version_id")); exists("runs", response.get("run_id"))
        for identity in response.get("record_ids", []):
            exists("records", identity)
    elif skill == "mep-document-registry" and command in ("scan", "rescan"):
        scan = conn.execute('''SELECT r.status,r.counters_json,s.id FROM registry_scans s
            JOIN registry_scan_results r ON r.run_id=s.id WHERE s.project_id=? ORDER BY s.rowid DESC LIMIT 1''',
                            (memory.cfg["project_id"],)).fetchone()
        if not scan or "error" in scan["status"] or json.loads(scan["counters_json"]).get("errors", 0):
            raise ValueError("Document registration incomplete; inspect persisted scan coverage/errors")
        refs.append({"table": "registry_scans", "id": scan["id"]})
    elif skill == "mep-equipment-matcher" and command in ("match", "group", "extract", "import-schedule", "import-cad", "import-json", "import-sql"):
        if command == "match":
            exists("eq_runs", response.get("run_id"))
        elif command == "group":
            if not response.get("proposed_entities"):
                raise ValueError("No equipment group proposed")
            for identity in response["proposed_entities"]:
                exists("eq_entities", identity)
        else:
            imports = response.get("results", []) if command == "extract" else [response]
            if not imports:
                raise ValueError("No equipment import produced")
            for item in imports:
                exists("eq_imports", item.get("import_id"))
                imported = conn.execute("SELECT * FROM eq_imports WHERE id=?", (item["import_id"],)).fetchone()
                if imported["status"] != "processed" or item.get("error"):
                    raise ValueError("Partial/unprocessed equipment import remains visible but cannot complete its declared scope")
    elif skill == "mep-cross-document-reviewer" and command in ("index", "map", "compare"):
        target = {"index": "tr_imports", "map": "tr_mapping_runs", "compare": "tr_runs"}[command]
        if command == "index":
            if not response.get("imports"):
                raise ValueError("No specification import produced")
            for item in response["imports"]:
                exists(target, item.get("import_id"))
                if item.get("error"):
                    raise ValueError("Specification indexing reported an error")
                imported = conn.execute("SELECT issues_json,coverage_json FROM tr_imports WHERE id=?", (item["import_id"],)).fetchone()
                if json.loads(imported["issues_json"]):
                    raise ValueError("Specification extraction gaps remain; inspect preserved import coverage")
        else:
            exists(target, response.get("mapping_run" if command == "map" else "run_id"))
    return refs


def database_audit(memory):
    """Orchestration integrity checks, not technical value interpretation or correction."""
    available = tables(memory.conn)
    findings = []
    project = memory.cfg["project_id"]
    selected = {r["file_id"] for r in selected_files(memory)}
    checked = 0
    if "eq_imports" in available:
        imports = {r["id"]: dict(r) for r in memory.conn.execute("SELECT * FROM eq_imports WHERE project_id=?", (project,))}
        if "eq_occurrences" in available:
            seen = {}
            for row in memory.conn.execute("SELECT * FROM eq_occurrences WHERE project_id=?", (project,)):
                imported = imports.get(row["import_id"])
                if not imported or imported["file_id"] not in selected:
                    continue
                checked += 1
                source, data = json.loads(row["source_json"]), json.loads(row["data_json"])
                def add(code):
                    findings.append({"code": code, "occurrence_id": row["id"], "import_id": row["import_id"], "source": source, "status": "candidate_requires_review"})
                if not source.get("method"):
                    add("missing_source_method")
                if not row["original_tag"]:
                    add("missing_equipment_tag")
                if not any(source.get(n) is not None for n in ("pdf_page", "row", "handle", "cad_handle", "record_index", "json_pointer")):
                    add("source_locator_requires_review")
                marker = key([row["import_id"], source, row["raw_json"]])
                if marker in seen:
                    add("repeated_same_source_observation")
                seen[marker] = row["id"]
        if "eq_parameters" in available:
            for row in memory.conn.execute("SELECT * FROM eq_parameters WHERE project_id=?", (project,)):
                value = json.loads(row["payload_json"])
                if value.get("normalization_status") in ("unknown_unit", "unresolved", "missing_unit"):
                    findings.append({"code": "unresolved_unit", "parameter_id": row["id"], "payload": value})
    if "tr_requirements" in available:
        for row in memory.conn.execute("SELECT * FROM tr_requirements WHERE project_id=?", (project,)):
            if not row["original_text"] or row["reference_status"] != "source_reference_available":
                findings.append({"code": "requirement_reference_or_text_requires_review", "requirement_id": row["id"], "reference_status": row["reference_status"]})
    return {"schema_version": "mep-master-database-audit/1", "project_id": project, "records_checked": checked,
            "findings": findings, "meaning": "Historical evidence integrity candidates; current engineering dispositions remain upstream",
            "engineering_approval": False, "database_signature": database_signature(memory)}


def coverage(memory, stage, jobs):
    """Declared scope reconciliation is separate from engineering approval."""
    spec = memory.cfg.get("stages", {}).get(stage, {})
    declaration = spec.get("coverage")
    if stage == "01":
        rows = selected_files(memory)
        if not rows or any(r["status"] in ("error", "missing") for r in rows):
            raise ValueError("No complete registered source inventory")
        return {"registered_file_ids": [r["file_id"] for r in rows], "meaning": "registration only; parsing and revisions remain unapproved"}
    if not isinstance(declaration, dict) or not declaration.get("actor") or not declaration.get("basis"):
        raise ValueError("Stage needs explicit coverage declaration: actor, basis, included_file_ids, exclusions")
    selected = {r["file_id"] for r in selected_files(memory)}
    included = set(declaration.get("included_file_ids", []))
    exclusions = declaration.get("exclusions", [])
    excluded = {r["file_id"] for r in exclusions if r.get("file_id") and r.get("reason")}
    if included & excluded or included | excluded != selected:
        raise ValueError("Every selected source must be included or explicitly excluded with a reason; unknown scope is not complete")
    if any(r.get("status") not in ("not_relevant", "not_applicable") for r in exclusions):
        raise ValueError("Unsupported/missing/unprocessed sources remain blockers; cannot hide them as successful coverage")
    covered = {f for job in jobs for f in job.get("source_file_ids", [])}
    if included - covered:
        raise ValueError("Included source files lack an executed job with exact source_file_ids")
    if not included and not spec.get("skip_reason"):
        raise ValueError("Empty declared stage requires an explicit skip_reason")
    return {**declaration, "engineering_approval": False}


def engineering_gate(cfg, selection=None):
    """Reuse package generator's existing read-only readiness projection."""
    import sys
    folder = Path(cfg["skills_root"]) / "mep-technical-package-generator/scripts"
    sys.path.insert(0, str(folder))
    from technical_package.repository import Repository
    from technical_package.planning import plans
    from technical_package.common import configuration
    repo = Repository(cfg["database"], cfg["project_id"], cfg.get("review_config"), cfg["skills_root"])
    try:
        scope = dict(cfg["scope"])
        if selection:
            if selection.get("entity-id"):
                if scope.get("entity_ids") and selection["entity-id"] not in scope["entity_ids"]:
                    raise ValueError("Approval target outside selected scope")
                scope["entity_ids"] = [selection["entity-id"]]
            if selection.get("category"):
                scope["categories"] = selection["category"] if isinstance(selection["category"], list) else [selection["category"]]
            if selection.get("tag"):
                raise ValueError("Approved master package selection needs exact entity-id or categories; resolve tag ambiguity first")
        record = repo.record()
        if scope.get("system") and not scope.get("entity_ids"):
            raise ValueError("System review/package scope needs explicit reviewed entity_ids; file selection alone cannot filter equipment")
        if scope.get("entity_ids"):
            ids = set(scope["entity_ids"])
            if ids - {t["id"] for t in record["targets"]}:
                raise ValueError("Unknown selected equipment IDs")
            # Each individual projection preserves type requirements in upstream readiness.
            groups = []
            for identity in sorted(ids):
                groups += plans(repo, repo.record(entity_id=identity), configuration(cfg.get("package_config")), scope.get("categories") or None)
        else:
            groups = plans(repo, record, configuration(cfg.get("package_config")), scope.get("categories") or None)
        if not groups:
            raise ValueError("No actual equipment groups available for engineering approval gate")
        return {"ready": all(g["readiness"]["status"] == "READY_FOR_EXPORT" for g in groups),
                "groups": [{"group_id": g["group_id"], "readiness": g["readiness"]} for g in groups],
                "comparison_status": record["comparison_status"], "approval_created": False}
    finally:
        repo.close()
