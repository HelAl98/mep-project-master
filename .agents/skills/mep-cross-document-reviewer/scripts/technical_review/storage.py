"""Compatibility with existing entities and shared generic review history."""
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .common import dump, key, now


def locate(explicit=None):
    for parent in ([Path(explicit)] if explicit else Path(__file__).resolve().parents):
        for root in (parent, parent / ".agents/skills"):
            if (root / "mep-equipment-matcher/scripts/equipment_matcher/storage.py").is_file():
                return root.resolve()
    raise ValueError("Existing project skills not found; supply --skills-root")


class Store:
    def __init__(self, path, project, cfg, skills=None):
        self.path = Path(path).expanduser().resolve(strict=True)
        self.skills = locate(skills)
        self.project = project
        self.cfg = cfg
        probe = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            if probe.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise ValueError("Requires existing core schema 2")
            for table in ("registry_migrations", "eq_migrations"):
                if [r[0] for r in probe.execute(f"SELECT version FROM {table}")] != [1]:
                    raise ValueError(f"Requires existing {table} version 1; run upstream intake first")
            if not probe.execute("SELECT 1 FROM registry_projects WHERE id=?", (project,)).fetchone():
                raise ValueError("Unknown registered project")
        finally:
            probe.close()
        for skill in ("mep-equipment-matcher", "mep-document-registry"):
            folder = str(self.skills / skill / "scripts")
            if folder not in sys.path:
                sys.path.insert(0, folder)
        self.ec = importlib.import_module("equipment_matcher.common")
        self.em = importlib.import_module("equipment_matcher.matching")
        self.es = importlib.import_module("equipment_matcher.sources")
        self.legacy = importlib.import_module("equipment_matcher.storage").Database(self.path, project, self.skills)
        self.conn = self.legacy.conn
        try:
            exists = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='tr_migrations'").fetchone()
            if exists:
                if [r[0] for r in self.conn.execute("SELECT version FROM tr_migrations")] != [1]:
                    raise ValueError("Unsupported technical migration; refusing automatic replacement")
            else:
                sql = (Path(__file__).resolve().parent.parent / "migrations/001_technical_review.sql").read_text(encoding="utf-8")
                try:
                    self.conn.executescript("BEGIN IMMEDIATE;\n" + sql)
                    self.conn.execute("INSERT INTO tr_migrations VALUES(1,?)", (now(),))
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
            with self.transaction():
                for table in ("tr_migrations", "tr_imports", "tr_requirements", "tr_interpretations", "tr_links", "tr_mapping_runs", "tr_runs",
                              "tr_comparisons", "tr_cases", "tr_coverage_scopes", "tr_results", "tr_approved_values", "tr_decision_evidence"):
                    pk = "version" if table == "tr_migrations" else "run_id" if table == "tr_results" else "id"
                    for operation in ("UPDATE", "DELETE"):
                        self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable technical evidence'); END")
                    self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {pk}=NEW.{pk}) BEGIN SELECT RAISE(ABORT,'Immutable technical key'); END")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.legacy.close()

    def transaction(self):
        return self.legacy.transaction()

    def insert(self, table, values):
        return self.legacy.insert(table, values)

    def rows(self, table):
        allowed = {"tr_imports", "tr_requirements", "tr_interpretations", "tr_links", "tr_mapping_runs", "tr_runs", "tr_comparisons", "tr_cases", "tr_coverage_scopes", "tr_approved_values", "tr_decision_evidence"}
        if table not in allowed:
            raise ValueError("Unknown technical table")
        return [dict(r) for r in self.conn.execute(f"SELECT rowid AS sequence,* FROM {table} WHERE project_id=? ORDER BY rowid", (self.project,))]

    def signature(self):
        own = Path(__file__).resolve().parent.parent
        paths = sorted(own.rglob("*.py")) + sorted((own / "migrations").glob("*.sql"))
        paths += [self.skills / skill / "scripts" / script for skill, script in (
            ("specification-extractor", "extract_specifications.py"), ("pdf-to-structured", "extract_pdf.py"))]
        return key(self.ec.implementation_signature(self.skills), [(p.name, self.ec.sha(p)) for p in paths])

    def upstream(self):
        raw = self.legacy.current()
        configs = {dump(json.loads(i["manifest_json"])["config"]) for i in raw["imports"] if i["id"] in raw["current_import_ids"]}
        equipment_cfg = self.ec.config(self.cfg["equipment_config"]) if self.cfg["equipment_config"] else json.loads(next(iter(configs))) if len(configs) == 1 else self.ec.default_config()
        equipment = self.em.snapshot(self.legacy, equipment_cfg)
        equipment["mixed_import_configurations"] = len(configs) > 1
        raw["equipment"] = equipment
        raw["equipment_config"] = equipment_cfg
        return raw

    def targets(self, upstream):
        snapshot = upstream["equipment"]
        occurrences = {o["id"]: o for o in snapshot["occurrences"] if o["revision_status"] != "superseded"}
        entities = [e for e in snapshot["entities"] if e["status"] not in ("rejected", "invalidated")]
        clusters = {oid: c for c in snapshot["instance_clusters"] for oid in c["occurrence_ids"]}
        representatives = {}
        for entity in sorted(entities, key=lambda e: (e["status"] != "confirmed", e["id"])):
            if entity["kind"] == "instance":
                cluster = next((clusters[o] for o in entity["occurrence_ids"] if o in clusters), None)
                if cluster:
                    representatives.setdefault(cluster["cluster_id"], entity["id"])
        targets = []
        for entity in entities:
            ids = list(entity["occurrence_ids"])
            aliases = []
            if entity["kind"] == "instance":
                cluster = next((clusters[o] for o in ids if o in clusters), None)
                if cluster:
                    if representatives[cluster["cluster_id"]] != entity["id"]:
                        continue
                    ids = list(cluster["occurrence_ids"])
                    aliases = [e["id"] for e in entities if e["kind"] == "instance" and set(e["occurrence_ids"]).intersection(ids)]
            source_rows = [occurrences[i] for i in ids if i in occurrences]
            if not source_rows:
                continue
            peer_ids = set()
            for match in snapshot["matches"]:
                if match["status"] in ("possible", "probable") and set(ids).intersection((match["left_id"], match["right_id"])):
                    peer_ids.update((match["left_id"], match["right_id"]))
            result = {"id": entity["id"], "kind": entity["kind"], "identity_status": entity["status"], "aliases": aliases,
                      "occurrence_ids": ids, "candidate_occurrence_ids": sorted(peer_ids - set(ids)), "occurrences": source_rows}
            for field in ("normalized_tag", "tag", "category", "discipline", "system", "building", "floor", "scope", "equipment_type"):
                plural = "categories" if field == "category" else field + "s"
                result[plural] = list(dict.fromkeys(str(o[field]) for o in source_rows if o.get(field) is not None))
            for plural, mapping in (("categories", self.cfg["equipment_aliases"]), ("disciplines", self.cfg["discipline_aliases"]), ("systems", self.cfg["system_aliases"])):
                result["original_" + plural] = list(result[plural])
                result[plural] = list(dict.fromkeys(mapping.get(v, v) for v in result[plural]))
            result["equipment_types"] += [e["id"] for e in entities if e["kind"] == "type" and e["status"] == "confirmed" and set(e["occurrence_ids"]).intersection(ids)]
            if entity["kind"] == "type" and entity["id"] not in result["equipment_types"]:
                result["equipment_types"].append(entity["id"])
            targets.append(result)
        return targets

    def requirements(self, upstream, history=False, ids=None):
        current_files = {f["file_id"]: f for f in upstream["registry"]["files"]}
        latest = {}
        imports = self.rows("tr_imports")
        for row in imports:
            if row["file_id"] in current_files and row["analysis_id"] == current_files[row["file_id"]]["analysis_id"]:
                latest[(row["file_id"], row["slot"])] = row["id"]
        active = set(latest.values())
        decisions = self.legacy.rows("eq_reviews")
        interpretations = self.rows("tr_interpretations")
        result = []
        if ids is None:
            raw_rows = self.rows("tr_requirements")
        else:
            raw_rows = []
            ordered_ids = sorted(set(ids))
            for start in range(0, len(ordered_ids), 400):
                batch = ordered_ids[start:start + 400]
                raw_rows.extend(dict(r) for r in self.conn.execute(f"SELECT * FROM tr_requirements WHERE project_id=? AND id IN ({','.join('?' for _ in batch)})", [self.project] + batch))
        for row in raw_rows:
            current = row["import_id"] in active
            if not history and not current:
                continue
            item = {**row, "source": json.loads(row["source_json"]), "context": json.loads(row["context_json"]),
                    "classification": json.loads(row["classification_json"]), "interpretations": json.loads(row["interpretations_json"]), "is_current": current}
            item["revision_status"] = self.revision_status(item["source"], upstream)
            events = [r for r in decisions if r["target_kind"] == "technical_requirement" and r["target_id"] == row["id"]]
            item["verification_status"] = events[-1]["decision"] if events and current else "unreviewed" if current else "invalidated"
            item["review_id"] = events[-1]["id"] if events else None
            for interpretation in interpretations:
                if interpretation["requirement_id"] == row["id"]:
                    approval = [r for r in decisions if r["target_kind"] == "technical_interpretation" and r["target_id"] == interpretation["id"]]
                    item["interpretations"].append({**json.loads(interpretation["payload_json"]), "id": interpretation["id"],
                        "method": interpretation["method"], "verification_status": approval[-1]["decision"] if approval else "unreviewed",
                        "review_id": approval[-1]["id"] if approval else interpretation["review_id"]})
            result.append(item)
        return result, imports, active

    def catalog(self, upstream):
        files = {f["file_id"]: f for f in upstream["registry"]["files"]}
        latest = {}
        imports = self.rows("tr_imports")
        by_import = {i["id"]: i for i in imports}
        for row in imports:
            if row["file_id"] in files and files[row["file_id"]]["analysis_id"] == row["analysis_id"]:
                latest[(row["file_id"], row["slot"])] = row["id"]
        active = set(latest.values())
        rows = [dict(r) for r in self.conn.execute("SELECT id,import_id,context_json,classification_json,reference_status FROM tr_requirements WHERE project_id=?", (self.project,)) if r["import_id"] in active]
        for row in rows:
            row.update(context=json.loads(row.pop("context_json")), classification=json.loads(row.pop("classification_json")), file_id=by_import[row["import_id"]]["file_id"], analysis_id=by_import[row["import_id"]]["analysis_id"])
        return rows, imports, active

    def revision_status(self, source, upstream):
        revisions = [r for r in upstream["registry"]["revisions"] if r["analysis_id"] == source.get("analysis_id") and r.get("sheet_id") == source.get("registry_sheet_id")]
        return revisions[-1]["verification_status"] if revisions else "unreviewed"

    def foundation(self, upstream, requirements, active):
        return key(self.signature(), self.cfg, sorted(active),
            [(f["file_id"], f["analysis_id"], f["metadata"], f["provenance"]) for f in upstream["registry"]["files"]],
            upstream["registry"]["revisions"], upstream["equipment"]["occurrences"], upstream["equipment"]["matches"],
            upstream["equipment"]["entities"], sorted(r["id"] for r in requirements),
            [(r["id"], r["payload_json"]) for r in self.rows("tr_interpretations") if r["requirement_id"] in {q["id"] for q in requirements}])

    def event_status(self, kind, target, basis, default="unreviewed"):
        rows = [r for r in self.legacy.rows("eq_reviews") if r["target_kind"] == kind and r["target_id"] == target and r["basis_hash"] == basis]
        return (rows[-1]["decision"], rows[-1]["id"]) if rows else (default, None)

    def references(self, supplied, upstream, requirements):
        if not isinstance(supplied, list) or not supplied:
            raise ValueError("At least one actual supporting source reference is required")
        files = {f["file_id"]: f for f in upstream["registry"]["files"]}
        reqs = {r["id"]: r for r in requirements}
        occs = {o["id"]: o for o in upstream["equipment"]["occurrences"]}
        result = []
        for reference in supplied:
            if not isinstance(reference, dict):
                raise ValueError("Each source reference must be an object")
            if reference.get("requirement_id") in reqs:
                self.legacy.archived_path(files[reqs[reference["requirement_id"]]["source"]["file_id"]])
                result.append({**reference, "source": reqs[reference["requirement_id"]]["source"]})
            elif reference.get("occurrence_id") in occs:
                self.legacy.archived_path(files[occs[reference["occurrence_id"]]["source"]["file_id"]])
                result.append({**reference, "source": occs[reference["occurrence_id"]]["source"]})
            elif reference.get("file_id") in files:
                file = files[reference["file_id"]]
                if reference.get("analysis_id", file["analysis_id"]) != file["analysis_id"]:
                    raise ValueError("Supporting document reference is historical/stale")
                page = reference.get("pdf_page")
                if page is not None:
                    if type(page) is not int or page < 1 or file["extension"] != "pdf":
                        raise ValueError("Invalid supporting PDF page")
                    from pypdf import PdfReader
                    if page > len(PdfReader(self.legacy.archived_path(file)).pages):
                        raise ValueError("Supporting page exceeds actual archived PDF")
                result.append({**reference, "analysis_id": file["analysis_id"], "sha256": file["sha256"], "relative_path": file["relative_path"]})
            else:
                raise ValueError("Register the actual supporting clarification/document first; unknown project references are refused")
        return result

    def append_decision(self, kind, target, decision, actor, reason, value, basis, refs, previous):
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Actual reviewer identity and rationale are required")
        identity = uuid.uuid4().hex
        self.insert("eq_reviews", {"id": identity, "project_id": self.project, "target_kind": kind, "target_id": target,
            "decision": decision, "actor": actor.strip(), "reason": reason.strip(), "value_json": dump(value), "basis_hash": basis, "created_at": now()})
        self.insert("tr_decision_evidence", {"id": key(identity, "support"), "project_id": self.project, "review_id": identity,
            "references_json": dump(refs), "previous_status_json": dump(previous), "created_at": now()})
        return identity
