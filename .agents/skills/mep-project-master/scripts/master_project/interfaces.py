"""Allow-listed adapters for source-inspected CLIs. No arbitrary shell or approvals."""
from pathlib import Path
import subprocess
import sys
from .common import read, write, resolve

# Command option sets reflect inspected argparse interfaces. Database/project flags
# are injected centrally and cannot be changed by a task's options.
OPS = {
 "mep-document-registry": {
   "scan": {"config"}, "rescan": {"config"}, "export": {"history"}},
 "pdf-to-structured": {"extract": {"metadata"}},
 "drawing-analyzer": {"analyze": set()},
 "specification-extractor": {"extract": set()},
 "dwg-to-excel": {"ingest": {"mapping", "metadata"}, "probe": {"exporter"}, "verify": {"exporter", "sha256"}},
 "etl-pipeline": {"tabular": {"mapping", "metadata"}, "ingest": set()},
 "data-lineage-tracker": {"inspect": {"record"}},
 "data-quality-check": {"check": {"config"}},
 "mep-equipment-matcher": {
   "extract": {"file-id", "run-id"}, "import-schedule": {"file-id", "mapping", "role", "slot"},
   "import-cad": {"file-id", "mapping", "role", "slot"}, "import-json": {"file-id", "role", "slot"},
   "import-sql": {"file-id", "role", "slot", "run-id"}, "match": set(), "group": {"by"}, "export": set()},
 "mep-cross-document-reviewer": {
   "index": {"file-id", "mode", "run-id", "slot"}, "map": set(), "compare": set(),
   "export": {"entity-id", "tag", "category", "history"},
   "export-approved": {"entity-id", "tag", "category", "history", "require-complete"}},
 "mep-technical-package-generator": {
   "draft": {"category", "tag", "entity-id"}, "approved": {"category", "tag", "entity-id"},
   "register": {"category", "tag", "entity-id", "mode"}, "specifications": {"category", "tag", "entity-id", "mode"},
   "matrix": {"category", "tag", "entity-id", "mode"}, "rfq": {"category", "tag", "entity-id", "mode"}}
}
PATH_OPTIONS = {"mapping", "metadata", "config", "exporter"}


def reference(memory, value):
    """@task-id means that task's durable primary output, never conversation text."""
    if not isinstance(value, str):
        raise ValueError("Input/config references must be strings")
    if value.startswith("@"):
        identity = value[1:]
        rows = [r for r in memory.events() if r["job_id"] == identity and r["status"] == "COMPLETED"]
        if not rows:
            raise ValueError("Missing completed task reference: " + value)
        from .evidence import valid_artifacts, valid_persisted
        event = rows[-1]
        if not valid_artifacts(event["payload"]) or not valid_persisted(memory, event["payload"]):
            raise ValueError("Referenced output checksum changed")
        return Path(event["payload"]["primary_output"])
    return resolve(Path(memory.cfg["config_path"]).parent, value)


def build(cfg, memory, job, inventory, attempt):
    skill, command = job["skill"], job["command"]
    if command not in OPS.get(skill, {}):
        raise ValueError("No supported executable adapter: " + skill + "/" + command)
    row = next(r for r in inventory if r["name"] == skill)
    if not row["available"]:
        raise ValueError("Skill/dependency unavailable: " + skill)
    script = Path(row["path"]) / row["interfaces"][0]
    args = [sys.executable, "-X", "utf8", "-B", str(script)]
    options = dict(job.get("options", {}))
    if set(options) - OPS[skill][command]:
        raise ValueError("Unsupported/reserved command options: " + str(set(options) - OPS[skill][command]))
    if skill in ("mep-equipment-matcher", "mep-cross-document-reviewer"):
        if command in ("extract", "import-schedule", "import-cad", "import-json", "import-sql", "index"):
            if not options.get("file-id") or set(job.get("source_file_ids", [])) != {options["file-id"]}:
                raise ValueError("Use one explicit registered file-id per intake task, exactly matching source_file_ids")
        if cfg["scope"].get("system") and command in ("match", "group", "map", "compare"):
            # Existing CLIs have no system filter. Do not pretend a config scope is an API filter.
            from .memory import tables
            selected = set(cfg["scope"].get("file_ids", []))
            for table in ("eq_imports", "tr_imports"):
                if table in tables(memory.conn):
                    outside = [r[0] for r in memory.conn.execute(f"SELECT DISTINCT file_id FROM {table} WHERE project_id=?", (cfg["project_id"],)) if r[0] not in selected]
                    if outside:
                        raise ValueError("Upstream CLI has no system-only filter and database contains other systems; stage unavailable for isolated execution until a supported interface exists")
    inputs = [reference(memory, v) for v in job.get("inputs", [])]
    for path in inputs:
        if not path.is_file():
            raise ValueError("Missing task input: " + str(path))
    primary = attempt / "result.json"
    db = ["--db", cfg["database"]]
    project = ["--project-id", cfg["project_id"]]
    siblings = ["--skills-root", cfg["skills_root"]]
    if skill == "mep-document-registry":
        args += siblings + [command] + db + project
        if command in ("scan", "rescan"):
            args += ["--root", cfg["source_directory"], "--fail-on-error"]
            if cfg.get("registry_config") and "config" not in options:
                options["config"] = cfg["registry_config"]
        args += ["--output", str(attempt / "files")]
    elif skill in ("mep-equipment-matcher", "mep-cross-document-reviewer", "mep-technical-package-generator"):
        args += db + project + siblings
        config_name = {"mep-equipment-matcher": "matching_config", "mep-cross-document-reviewer": "review_config",
                       "mep-technical-package-generator": "package_config"}[skill]
        if cfg.get(config_name):
            args += ["--config", cfg[config_name]]
        if skill == "mep-technical-package-generator" and cfg.get("review_config"):
            args += ["--review-config", cfg["review_config"]]
        args += [command]
        if command.startswith("export"):
            args += ["--output", str(attempt / "files")]
        if command == "import-json" or (skill == "mep-cross-document-reviewer" and command == "index" and options.get("mode") == "json"):
            if len(inputs) != 1:
                raise ValueError("JSON import/index requires one source evidence input")
            args += ["--input", str(inputs[0])]
        if skill == "mep-technical-package-generator":
            args += ["--output", str(Path(cfg["output_directory"]) / "technical-packages")]
            scope = cfg["scope"]
            if scope.get("system") and not options.get("entity-id"):
                raise ValueError("System package task requires explicit entity-id; upstream CLI has no system filter")
            if options.get("entity-id") and scope.get("entity_ids") and options["entity-id"] not in scope["entity_ids"]:
                raise ValueError("Package entity lies outside declared scope")
            if not options.get("category") and scope.get("categories"):
                options["category"] = scope["categories"]
    elif skill == "etl-pipeline":
        args += [command]
        if len(inputs) != 1:
            raise ValueError("ETL requires exactly one input")
        if command == "ingest":
            args += db + ["--package", str(inputs[0])]
        else:
            args += ["--input", str(inputs[0]), "--output", str(primary)]
    elif skill == "data-lineage-tracker":
        args += [command] + db + ["--output", str(primary)]
    elif skill == "dwg-to-excel":
        args += [command]
        if command == "ingest":
            if len(inputs) != 1:
                raise ValueError("CAD ingestion requires one actual mapped XLSX export")
            args += [str(inputs[0])]
        args += ["--output", str(primary)]
    else:
        if skill == "data-quality-check":
            if not inputs:
                raise ValueError("Quality check requires supplied evidence packages")
        elif len(inputs) != 1:
            raise ValueError("Extraction adapter needs exactly one input")
        args += [str(p) for p in inputs] + ["--output", str(primary)]
    for name, value in options.items():
        if name in PATH_OPTIONS:
            value = str(reference(memory, value))
        if type(value) is bool:
            if value:
                args.append("--" + name)
        else:
            for item in value if isinstance(value, list) else [value]:
                args += ["--" + name, str(item)]
    return args, primary, inputs


def execute(args, attempt, timeout):
    # No shell; bounded logs on disk, not in model context. Timeout never deletes partial evidence.
    stdout, stderr = attempt / "stdout.json", attempt / "stderr.txt"
    with stdout.open("x", encoding="utf-8") as out, stderr.open("x", encoding="utf-8") as err:
        process = subprocess.Popen(args, stdout=out, stderr=err, shell=False, cwd=str(attempt))
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            raise
    if code:
        raise ValueError(f"Child command exited {code}; inspect {stderr} and retained output")
    return stdout
