"""Explicit operator checkpoints and human-authorized upstream decisions."""
from pathlib import Path
import uuid
from .common import key, read, sha, now, encoded
from .memory import Memory, project_lock, tables
from .discovery import discover
from .evidence import artifact, selected_files
from .engine import jobs_for, job_fingerprint, attempt_directory
from .interfaces import execute


def checkpoint(cfg, stage, job_id, receipt_path):
    """Attest operational instruction work, never approve engineering through this API."""
    receipt_path = Path(receipt_path).resolve(strict=True)
    receipt = read(receipt_path)
    with project_lock(cfg):
        memory = Memory(cfg, writable=True)
        try:
            job = next((j for j in jobs_for(cfg, stage) if j["id"] == job_id), None)
            if not job or job.get("kind") != "codex":
                raise ValueError("Checkpoint requires a configured kind=codex task")
            inventory = discover(cfg)
            row = next(r for r in inventory if r["name"] == job["skill"])
            if not row["available"]:
                raise ValueError("Instruction skill/dependencies unavailable")
            fp = job_fingerprint(cfg, memory, job, inventory)
            if receipt.get("schema_version") != "mep-master-checkpoint/1" or receipt.get("input_fingerprint") != fp:
                raise ValueError("Receipt must name the current plan task fingerprint and checkpoint schema")
            if receipt.get("project_id") != cfg["project_id"] or receipt.get("scope_id") != cfg["scope"]["id"]:
                raise ValueError("Foreign project/scope receipt")
            if receipt.get("engineering_approval") is not False:
                raise ValueError("Operational checkpoint must explicitly state engineering_approval=false")
            for field in ("actor", "method", "summary", "limitations"):
                if not receipt.get(field):
                    raise ValueError("Receipt requires " + field)
            if set(receipt.get("source_file_ids", [])) != set(job.get("source_file_ids", [])):
                raise ValueError("Receipt scope must exactly match configured task sources")
            known = {r["file_id"]: r for r in selected_files(memory)}
            if not receipt.get("sources"):
                raise ValueError("Receipt requires original source hashes and file IDs")
            for source in receipt["sources"]:
                file = known.get(source.get("file_id"))
                if not file or file["sha256"] != source.get("sha256"):
                    raise ValueError("Receipt source is not the current registered version")
            if {r["file_id"] for r in receipt["sources"]} != set(job.get("source_file_ids", [])):
                raise ValueError("Receipt does not cover every declared source")
            artifacts = []
            for output in receipt.get("outputs", []):
                item = artifact(output["path"])
                if item["sha256"] != output.get("sha256"):
                    raise ValueError("Receipt output checksum mismatch")
                artifacts.append(item)
            if not artifacts:
                raise ValueError("Instruction workflow needs durable output, not a narrative completion claim")
            # Profiling is instruction-based, but its durable artifact must retain worksheet/column evidence.
            if job["skill"] == "data-profiler":
                profiles = [read(a["path"]) for a in artifacts if Path(a["path"]).suffix.lower() == ".json"]
                required = {"name", "source_file_id", "columns", "row_count", "missing_values", "data_types", "unit_columns", "column_naming_issues", "parsing_difficulties"}
                if not any(p.get("worksheets") and p.get("extraction_plan") and all(required <= set(w) for w in p["worksheets"]) for p in profiles):
                    raise ValueError("Profile JSON needs worksheets with actual columns, missingness/types/units and an extraction_plan")
            if stage == "08" and not receipt.get("database_checks"):
                raise ValueError("Stage 08 Codex database audit must document actual completeness/relationship/source-reference checks")
            if stage == "11" and receipt.get("visual_review") != "completed":
                raise ValueError("Document delivery checkpoint requires actual render/visual review via built-in authoring skills")
            payload = {"primary_output": artifacts[0]["path"], "artifacts": artifacts + [artifact(receipt_path)],
                       "receipt": receipt, "engineering_approval_created": False}
            return {"event_id": memory.event(stage, "COMPLETED", fp, payload, job_id), "stage_completion": "Run/resume to reconcile remaining tasks and coverage"}
        finally:
            memory.close()


DECISIONS = {
 "mep-document-registry": {"review": {"target-type", "target-id", "decision", "actor", "reason", "value-json"}},
 "mep-equipment-matcher": {"review": {"target-kind", "target-id", "decision", "actor", "reason", "value-json"}},
 "mep-cross-document-reviewer": {
   "review": {"target-kind", "target-id", "decision", "actor", "reason", "refs-json", "value-json"},
   "interpret": {"requirement-id", "payload-json", "actor", "reason", "refs-json", "method"},
   "accept-value": {"entity-id", "payload-json", "actor", "reason", "refs-json"}},
 "data-lineage-tracker": {"review": {"record", "reviewer", "decision", "reason", "field", "value-json"}},
 "etl-pipeline": {"activate": {"version", "reviewer", "reason"}}
}


def decision(cfg, request_path, authorized=False):
    if not authorized:
        raise ValueError("Requires explicit user authorization; inspect request then use --human-authorized")
    import sys
    request = read(request_path)
    skill, command, options = request["skill"], request["command"], request["options"]
    allowed = DECISIONS.get(skill, {}).get(command)
    if allowed is None or set(options) - allowed:
        raise ValueError("Unsupported decision command/options")
    actor = options.get("actor", options.get("reviewer"))
    if not actor or not options.get("reason") or request.get("project_id") != cfg["project_id"]:
        raise ValueError("Actual reviewer, rationale and matching project_id required")
    inventory = discover(cfg)
    row = next(r for r in inventory if r["name"] == skill)
    if not row["available"]:
        raise ValueError("Decision skill unavailable")
    with project_lock(cfg):
        memory = Memory(cfg, writable=True)
        try:
            args = [sys.executable, "-X", "utf8", "-B", str(Path(row["path"]) / row["interfaces"][0])]
            common = ["--db", cfg["database"]]
            if skill.startswith("mep-"):
                common += ["--project-id", cfg["project_id"]]
            if skill in ("mep-equipment-matcher", "mep-cross-document-reviewer"):
                args += common + ["--skills-root", cfg["skills_root"]]
                config_name = "matching_config" if skill == "mep-equipment-matcher" else "review_config"
                if cfg.get(config_name):
                    args += ["--config", cfg[config_name]]
                args += [command]
            elif skill == "mep-document-registry":
                args += ["--skills-root", cfg["skills_root"], command] + common
            else:
                args += [command] + common
            for name, value in options.items():
                if name.endswith("-json") and not isinstance(value, str):
                    value = encoded(value)
                args += ["--" + name, str(value)]
            attempt = attempt_directory(cfg, "09", "human-decision")
            # An intent audit precedes the child process; upstream own audit is authoritative if interrupted.
            with memory.conn:
                memory.conn.execute("INSERT INTO master_operator_events VALUES(?,?,?,?,?,?,?,?)",
                                    (uuid.uuid4().hex, cfg["project_id"], cfg["scope"]["id"], "authorized_decision_intent",
                                     actor, options["reason"], encoded({"request": request, "attempt": str(attempt)}), now()))
            output = execute(args, attempt, int(cfg.get("command_timeout_seconds", 1800)))
            response = read(output)
            # Verify the actual upstream decision row, rather than inventing approval in master tables.
            identity = response.get("review_id", response.get("activation_id", response.get("id"))) if isinstance(response, dict) else response if isinstance(response, int) else None
            target = "registry_reviews" if skill == "mep-document-registry" else "eq_reviews" if skill.startswith("mep-") else "reviews" if skill == "data-lineage-tracker" else "activations"
            if identity is None and isinstance(response, int):
                identity = response
            if target not in tables(memory.conn):
                raise ValueError("Expected upstream decision table absent")
            if identity is not None:
                if not memory.conn.execute(f"SELECT 1 FROM {target} WHERE id=?", (identity,)).fetchone():
                    raise ValueError("Upstream decision response not found in audit table")
            else:
                raise ValueError("Unsupported upstream decision response; inspect audit before retrying to avoid duplicate events")
            return {"upstream_response": response, "output": str(output), "next_action": "Resume to invalidate affected work and re-evaluate current readiness"}
        finally:
            memory.close()


def retrieve(cfg, tag=None, query=None):
    memory = Memory(cfg)
    try:
        if tag:
            import sys
            sys.path.insert(0, str(Path(cfg["skills_root"]) / "mep-technical-package-generator/scripts"))
            from technical_package.repository import Repository
            repo = Repository(cfg["database"], cfg["project_id"], cfg.get("review_config"), cfg["skills_root"])
            try:
                return repo.record(tag=tag)
            finally:
                repo.close()
        if not query or not query.strip():
            raise ValueError("Provide a literal search phrase")
        phrase = '"' + query.replace('"', '""') + '"'
        hashes = {r["sha256"] for r in selected_files(memory)}
        rows = memory.conn.execute('''SELECT d.*,v.filename,v.sha256,v.revision FROM evidence_fts f
            JOIN records d ON d.id=f.record_id JOIN versions v ON v.id=d.version_id
            WHERE evidence_fts MATCH ? AND EXISTS(SELECT 1 FROM registry_files rf
              JOIN registry_scan_files sf ON sf.file_id=rf.id JOIN versions rv ON rv.id=sf.version_id
              WHERE rf.project_id=? AND rv.sha256=v.sha256)''', (phrase, cfg["project_id"]))
        results = []
        for row in rows:
            if row["sha256"] in hashes:
                results.append(dict(row))
            if len(results) >= 50:
                break
        return {"results": results,
                "mode": "literal FTS5 in current selected source versions; no semantic completeness claim"}
    finally:
        memory.close()
