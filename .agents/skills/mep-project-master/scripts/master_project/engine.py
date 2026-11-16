"""Resumable stage coordinator. Not a new engineering extractor or approval engine."""
from pathlib import Path
import json
import uuid
from .common import HOME, key, sha, read, write, now, encoded, code_hash, resolve
from .discovery import discover, workflow
from .memory import Memory, project_lock, tables
from .evidence import (selected_files, source_fingerprint, artifact, valid_artifacts,
                       persisted, valid_persisted, coverage, engineering_gate, database_signature, database_audit)
from .interfaces import reference, build, execute


def jobs_for(cfg, stage):
    spec = cfg.get("stages", {}).get(stage, {})
    jobs = list(spec.get("jobs", []))
    if stage == "01" and not jobs:
        jobs = [{"id": "document-intake", "skill": "mep-document-registry", "command": "rescan"}]
    if len({j["id"] for j in jobs}) != len(jobs):
        raise ValueError("Task IDs must be unique within a stage")
    for job in jobs:
        if not job.get("id") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in job["id"]):
            raise ValueError("Use safe task IDs of letters, numbers, hyphen or underscore")
    return jobs


def validate_config(cfg):
    ids = []
    for stage in workflow():
        for job in jobs_for(cfg, stage["id"]):
            ids.append(job["id"])
            if job["skill"] not in stage["skills"]:
                raise ValueError("Task skill not routed to stage " + stage["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Task IDs must be unique across this scope for @task references")


def data_basis(memory, job):
    """Only the actual read dependencies; no self-generated run IDs."""
    skill, command = job["skill"], job.get("command")
    names = []
    if skill == "mep-document-registry" and command == "export":
        names = ["registry_reviews"]
    if skill == "mep-equipment-matcher" and command in ("match", "group", "export"):
        names = ["eq_imports", "registry_reviews", "eq_reviews"]
        if command in ("group", "export"):
            names += ["eq_runs"]
    if skill == "mep-cross-document-reviewer" and command and command != "index":
        names = ["eq_imports", "eq_entities", "eq_runs", "registry_reviews", "eq_reviews", "tr_imports", "tr_interpretations"]
        if command != "map":
            names += ["tr_mapping_runs"]
        if command.startswith("export"):
            names += ["tr_runs"]
    if skill == "mep-technical-package-generator":
        return database_signature(memory)
    if job.get("kind") == "codex" and skill not in ("data-profiler", "xlsx-construction", "docx-construction", "pdf-construction"):
        return database_signature(memory)
    result = {}
    available = tables(memory.conn)
    for table in names:
        if table in available:
            result[table] = [r[0] for r in memory.conn.execute(f"SELECT id FROM {table} WHERE project_id=? ORDER BY id", (memory.cfg["project_id"],))]
        else:
            result[table] = None
    return key(result)


def job_fingerprint(cfg, memory, job, inventory, *, result_policy=None):
    inputs = []
    for value in job.get("inputs", []):
        path = reference(memory, value)
        inputs.append([str(path), sha(path)])
    for name, value in job.get("options", {}).items():
        if name in ("mapping", "metadata", "config", "exporter"):
            path = reference(memory, value); inputs.append([str(path), sha(path)])
    config_names = {"mep-document-registry": ("registry_config",), "mep-equipment-matcher": ("matching_config",),
                    "mep-cross-document-reviewer": ("matching_config", "review_config"),
                    "mep-technical-package-generator": ("matching_config", "review_config", "package_config"),
                    "data-quality-check": ("quality_config",)}.get(job["skill"], ())
    for name in config_names:
        if cfg.get(name):
            inputs.append([name, sha(cfg[name])])
    if job.get("scoped_request"):
        from .limited_scope import fingerprint_basis
        scoped_path = reference(memory, job["scoped_request"])
        inputs.append([str(scoped_path), sha(scoped_path)])
        inputs.append(["scoped_eligibility_basis", key(fingerprint_basis(cfg, memory))])
    # All relevant installed dependency code participates; source files remain selective.
    source = source_fingerprint(cfg, None if job["skill"] == "mep-document-registry" and job["command"] in ("scan", "rescan") else memory,
                                job.get("source_file_ids"))
    fingerprint = key({"job": job, "scope": cfg["scope"], "sources": source, "input_files": inputs,
                "database_basis": data_basis(memory, job), "code": code_hash(),
                "skills": [(r["name"], r["signature"], r["available"]) for r in inventory]})
    return key({'native_job_fingerprint':fingerprint,'result_policy':result_policy}) if result_policy is not None else fingerprint


def attempt_directory(cfg, stage, identity):
    path = Path(cfg["output_directory"]) / "workflow" / cfg["scope"]["id"] / stage / identity / uuid.uuid4().hex
    root = Path(cfg["output_directory"]).resolve()
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Unsafe scope/output path")
    path.mkdir(parents=True, exist_ok=False)
    return path


def validate_result(memory, job, response, primary, scoped_eligibility=None, *, result_policy=None, validation_result=None):
    if not isinstance(response, dict):
        raise ValueError("Expected structured JSON object from installed CLI")
    accepted=None
    if result_policy is not None:
        from .specification_layout import validate_result as validate_specification
        accepted=validate_specification(memory,job,response,primary,result_policy)
    if response.get("schema_version") == "mep-evidence/1":
        document = response.get("document", {})
        rows = selected_files(memory)
        expected = set(job.get("source_file_ids", []))
        if len(expected) != 1 or not any(r["file_id"] in expected and r["sha256"] == document.get("sha256") for r in rows):
            raise ValueError("Extraction source hash is not linked to selected registered source_file_ids")
        if not response.get("records"):
            raise ValueError("Empty extraction retained for inspection; it cannot establish coverage")
        # Warnings remain in the output. Any extraction gaps block completion rather than disappearing.
        if response.get("issues") and accepted is None:
            raise ValueError("Extraction has gaps/warnings; inspect output and narrow scope or obtain supported evidence")
    if job["skill"] == "data-quality-check":
        if response.get("packages_checked", 0) < 1 or "findings" not in response:
            raise ValueError("No quality-control evidence was checked")
    if job["skill"] == "data-lineage-tracker" and response.get("evidence_verified") is not True:
        raise ValueError("Archived source evidence failed lineage verification")
    if scoped_eligibility and scoped_eligibility.get("eligibility_kind") == "EQUIPMENT_IMPORT_ONLY":
        from .equipment_scope import validate_import
        refs = validate_import(memory, job, response, scoped_eligibility)
    else:
        refs = persisted(memory, response, job["skill"], job["command"])
    if not valid_persisted(memory, {"persisted_refs": refs}):
        raise ValueError("Returned imports are historical rather than the current file/slot; explicit upstream reconciliation is required")
    packages = []
    if job["skill"] == "mep-technical-package-generator":
        for item in response.get("packages", []):
            manifest_path = Path(item["directory"]) / "Package_Manifest.json"
            manifest = read(manifest_path)
            if manifest.get("project_id") != memory.cfg["project_id"] or manifest.get("generation_status") != "completed":
                raise ValueError("Package manifest missing/foreign/incomplete")
            output_root = (Path(memory.cfg["output_directory"]) / "technical-packages").resolve()
            if not manifest_path.resolve().is_relative_to(output_root):
                raise ValueError("Package escaped configured root")
            for file in manifest["outputs"]:
                path = (manifest_path.parent / file["name"]).resolve()
                if not path.is_relative_to(manifest_path.parent.resolve()) or sha(path) != file["sha256"]:
                    raise ValueError("Package output checksum/path mismatch")
            packages.append({"manifest": str(manifest_path), "sha256": sha(manifest_path), "package_id": manifest["package_id"],
                             "version_id": manifest["version_id"], "readiness": manifest["technical_readiness"], "rfq_issued": False})
        if not packages:
            raise ValueError("No equipment package generated; empty result is not completion")
    if validation_result is not None:validation_result.update(accepted or {})
    return refs, packages


def run_job(cfg, memory, stage, job, inventory, *, result_policy=None):
    if result_policy is not None:
        from .specification_layout import POLICY
        if result_policy!=POLICY or stage!='04' or job.get('skill')!='specification-extractor' or job.get('command')!='extract' or getattr(memory,'operation_result_scope',None)!=('B','native_job'):
            raise ValueError('Specification result policy is restricted to Operation B native extraction')
    scoped_eligibility = None
    if job.get("scoped_request"):
        from .limited_scope import job_eligibility
        scoped_eligibility = job_eligibility(cfg, memory, stage, job)
    fp = job_fingerprint(cfg, memory, job, inventory,result_policy=result_policy)
    cached = memory.cache(stage, job["id"], fp)
    if cached and valid_artifacts(cached["payload"]) and valid_persisted(memory, cached["payload"]):
        validation=cached['payload'].get('validation',{})
        if result_policy is not None and (validation.get('policy')!=result_policy or validation.get('status')!='ACCEPTED_UNREVIEWED_WITH_LAYOUT_LIMITATION'):
            raise ValueError('Native specification cache lacks verified unreviewed warning disposition')
        return {"job": job["id"], "status": "COMPLETED", "reused": True, "event_id": cached["id"],**({'validation':validation} if result_policy is not None else {})}
    if job.get("kind") == "codex":
        raise ValueError("Instruction-only task needs Codex work and an evidence receipt; use checkpoint, not a Python agent call")
    if stage == "10" and (job["command"] == "approved" or job.get("options", {}).get("mode") == "approved"):
        gate = engineering_gate(cfg, job.get("options"))
        if not gate["ready"]:
            raise ValueError("Current upstream engineering readiness blocks approved package generation")
        memory.event("09", "COMPLETED", key(gate), {"selected_package_gate": gate, "approval_created": False}, "readiness-" + job["id"])
    attempt = attempt_directory(cfg, stage, job["id"])
    args, primary, inputs = build(cfg, memory, job, inventory, attempt)
    memory.event(stage, "RUNNING", fp, {"attempt": str(attempt), "argv": args, "input_files": [str(p) for p in inputs]}, job["id"])
    try:
        stdout = execute(args, attempt, int(cfg.get("command_timeout_seconds", 1800)))
        if not primary.is_file():
            primary = stdout
        response = read(primary)
        validation={}
        refs, packages = validate_result(memory, job, response, primary, scoped_eligibility,result_policy=result_policy,validation_result=validation)
        # Fail if source bytes changed during execution. Registration itself is allowed to update its heads.
        after = job_fingerprint(cfg, memory, job, inventory,result_policy=result_policy)
        if after != fp:
            raise ValueError("Inputs changed during execution; retained output needs review before retry")
        artifacts = [artifact(p) for p in sorted(attempt.rglob("*")) if p.is_file() and p.stat().st_size]
        artifacts += [artifact(p["manifest"]) for p in packages]
        for package in packages:
            manifest = read(package["manifest"])
            artifacts += [artifact(Path(package["manifest"]).parent / f["name"]) for f in manifest["outputs"]]
        payload = {"primary_output": str(primary), "artifacts": artifacts, "persisted_refs": refs,
                   "packages": packages, "source_file_ids": job.get("source_file_ids", []), "scoped_eligibility": scoped_eligibility, "engineering_approval_created": False}
        if validation:payload['validation']=validation
        memory.persist_packages(packages)
        event = memory.event(stage, "COMPLETED", fp, payload, job["id"])
        return {"job": job["id"], "status": "COMPLETED", "reused": False, "event_id": event,**({'validation':validation} if validation else {})}
    except BaseException as error:
        memory.event(stage, "FAILED", fp, {"attempt": str(attempt), "error": str(error), "error_type": type(error).__name__}, job["id"])
        raise


def stage_signature(cfg, memory, stage, inventory):
    tasks = jobs_for(cfg, stage)
    return key({"stage": stage, "configuration": cfg.get("stages", {}).get(stage, {}),
                "scope": cfg["scope"], "jobs": [job_fingerprint(cfg, memory, j, inventory) for j in tasks],
                "gate_state": database_signature(memory) if stage in ("08", "09") else None})


def status(cfg):
    inventory = discover(cfg)
    if not Path(cfg["database"]).is_file():
        return {"project_id": cfg["project_id"], "database": cfg["database"], "stages": [{**s, "status": "PENDING"} for s in workflow()],
                "next_action": "run to register sources; no database exists", "skills": inventory}
    memory = Memory(cfg)
    try:
        result = []
        previous = {}
        for stage in workflow():
            identity = stage["id"]
            event = memory.latest(identity)
            state = event["status"] if event else "PENDING"
            reason = None
            try:
                fp = stage_signature(cfg, memory, identity, inventory)
                dependencies = dependencies_for(cfg, stage)
                blocked = [d for d in dependencies if previous.get(d) != "COMPLETED"]
                scoped_ready = False
                if event and state == "COMPLETED" and blocked:
                    try:
                        from .limited_scope import bridge
                        bridge(cfg, memory, identity, jobs_for(cfg, identity), blocked, previous)
                        scoped_ready = True
                    except (ValueError, OSError, KeyError, TypeError):
                        pass
                if event and state == "COMPLETED" and (event["fingerprint"] != fp or (blocked and not scoped_ready)):
                    state = "STALE"; reason = "Source/configuration/review/upstream dependency changed"
                for job in jobs_for(cfg, identity):
                    if job.get("scoped_request"):
                        from .limited_scope import job_eligibility
                        job_eligibility(cfg, memory, identity, job)
                    old = memory.cache(identity, job["id"], job_fingerprint(cfg, memory, job, inventory))
                    if state == "COMPLETED" and (not old or not valid_artifacts(old["payload"]) or not valid_persisted(memory, old["payload"])):
                        state = "STALE"; reason = "Expected output missing or checksum differs"
                audit = event["payload"].get("database_audit") if event else None
                if state == "COMPLETED" and audit and (not Path(audit["path"]).is_file() or sha(audit["path"]) != audit["sha256"]):
                    state = "STALE"; reason = "Database audit output missing or changed"
            except (ValueError, OSError, KeyError) as error:
                if state == "COMPLETED":
                    state = "STALE"
                reason = str(error)
            if state == "RUNNING":
                reason = "Inspect project lock/process and partial task artifacts; resume never assumes completion"
            previous[identity] = state
            result.append({**stage, "status": state, "staleness": state == "STALE", "reason": reason,
                           "last_event": event, "active": cfg.get("stages", {}).get(identity, {}).get("active", True)})
        from .limited_scope import audit_summary
        return {"available_scope_receipts": audit_summary(memory), "project_id": cfg["project_id"], "scope": cfg["scope"], "mode": cfg["execution_mode"],
                "database": cfg["database"], "stages": result, "skills": inventory,
                "review_registers": {t: memory.conn.execute(f"SELECT COUNT(*) FROM {t} WHERE project_id=?", (cfg["project_id"],)).fetchone()[0]
                                     for t in ("registry_issues", "eq_issues", "tr_cases", "registry_reviews", "eq_reviews") if t in tables(memory.conn)},
                "review_counts_are_historical_not_open_issue_counts": True}
    finally:
        memory.close()


def dependencies_for(cfg, stage):
    if stage["id"] == "10" and (cfg.get("package_mode", "draft") == "draft" or cfg.get("explicit_package_request")):
        return ["08"]  # Explicit internal drafts may precede engineering approval; upstream readiness still shown.
    return stage["dependencies"]


def bootstrap(cfg, inventory):
    """Registry creates the only engineering DB. A durable pre-DB journal survives interruption."""
    from types import SimpleNamespace
    jobs = jobs_for(cfg, "01")
    if len(jobs) != 1 or jobs[0]["skill"] != "mep-document-registry" or jobs[0]["command"] not in ("scan", "rescan"):
        raise ValueError("Initial intake must be one registry scan/rescan task")
    attempt = attempt_directory(cfg, "01", "bootstrap")
    shim = SimpleNamespace(cfg=cfg)
    args, primary, _ = build(cfg, shim, jobs[0], inventory, attempt)
    write(attempt / "bootstrap-journal.json", {"state": "RUNNING", "database": cfg["database"], "argv": args, "timestamp": now()})
    stdout = execute(args, attempt, int(cfg.get("command_timeout_seconds", 1800)))
    return attempt, stdout, jobs[0]


def run(cfg, requested=None):
    validate_config(cfg)
    inventory = discover(cfg)
    summaries = []
    with project_lock(cfg):
        boot = None
        if not Path(cfg["database"]).is_file():
            if requested and requested != "01":
                raise ValueError("Start with project intake before another stage")
            boot = bootstrap(cfg, inventory)
        memory = Memory(cfg, writable=True)
        try:
            if boot:
                attempt, stdout, job = boot
                response = read(stdout)
                refs = persisted(memory, response, job["skill"], job["command"])
                fp = job_fingerprint(cfg, memory, job, inventory)
                memory.event("01", "COMPLETED", fp, {"primary_output": str(stdout), "artifacts": [artifact(p) for p in sorted(attempt.rglob("*")) if p.is_file() and p.stat().st_size],
                             "persisted_refs": refs, "engineering_approval_created": False}, job["id"])
            for stage in workflow():
                identity = stage["id"]
                if requested and requested != identity:
                    continue
                spec = cfg.get("stages", {}).get(identity, {})
                try:
                    fp = stage_signature(cfg, memory, identity, inventory)
                    states = {s["id"]: s["status"] for s in status(cfg)["stages"]}
                    if states[identity] == "COMPLETED":
                        summaries.append({"stage": identity, "status": "COMPLETED", "reused": True}); continue
                    if states[identity] == "STALE":
                        memory.event(identity, "STALE", fp, {"reason": "Inputs/upstream/output validity changed; cached per-file tasks will be reconciled"})
                    blocked = [d for d in dependencies_for(cfg, stage) if states[d] != "COMPLETED"]
                    if blocked:
                        from .limited_scope import bridge
                        bridge(cfg, memory, identity, jobs_for(cfg, identity), blocked, states)
                    if spec.get("active", True) is False:
                        raise ValueError("Stage disabled by configuration; downstream cannot assume it was performed")
                    if identity == "09":
                        gate = engineering_gate(cfg)
                        if not gate["ready"]:
                            memory.event(identity, "BLOCKED", fp, {"reason": "Explicit upstream engineering review required", "gate": gate})
                            summaries.append({"stage": identity, "status": "BLOCKED", "gate": gate}); break
                        memory.event(identity, "COMPLETED", fp, {"gate": gate, "approval_created": False})
                        summaries.append({"stage": identity, "status": "COMPLETED", "gate": gate})
                    else:
                        jobs = jobs_for(cfg, identity)
                        if not jobs and not spec.get("skip_reason"):
                            raise ValueError("No configured tasks: read routed SKILL.md and configure source mappings/Codex work")
                        memory.event(identity, "RUNNING", fp, {"upstream_dependencies": dependencies_for(cfg, stage)})
                        results = [run_job(cfg, memory, identity, job, inventory) for job in jobs]
                        scoped_coverage = coverage(memory, identity, jobs)
                        audit_output = None
                        if identity == "08":
                            directory = attempt_directory(cfg, identity, "database-audit")
                            audit_output = directory / "database-quality.json"
                            write(audit_output, database_audit(memory))
                        memory.event(identity, "COMPLETED", stage_signature(cfg, memory, identity, inventory),
                                     {"tasks": results, "coverage": scoped_coverage, "skip_reason": spec.get("skip_reason"),
                                      "database_audit": artifact(audit_output) if audit_output else None,
                                      "meaning": "Declared operational scope completed; engineering approval is separate"})
                        summaries.append({"stage": identity, "status": "COMPLETED", "tasks": results, "coverage": scoped_coverage})
                    if cfg["execution_mode"] == "guided":
                        break
                except Exception as error:
                    fallback = key({"stage": identity, "error": str(error)})
                    # Child task failures and stage coverage blocks are both retained distinctly.
                    failed = any((memory.latest(identity, j["id"]) or {}).get("status") == "FAILED" for j in jobs_for(cfg, identity))
                    failure_status = "FAILED" if failed else "BLOCKED"
                    memory.event(identity, failure_status, locals().get("fp", fallback), {"reason": str(error), "error_type": type(error).__name__})
                    summaries.append({"stage": identity, "status": failure_status, "reason": str(error)})
                    break
            return {"project_id": cfg["project_id"], "mode": cfg["execution_mode"], "results": summaries,
                    "next_action": "Review summary/limitations and instruct resume" if cfg["execution_mode"] == "guided" else "Resolve blocked stage or inspect status",
                    "engineering_approvals_created": False}
        finally:
            memory.close()
