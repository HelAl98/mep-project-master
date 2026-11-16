"""Equipment-specific append-only storage and current-source projections."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .common import alias, category, config, decimal, dump, implementation_signature, key, now, parameter, sha, skills_root, tag


class Database:
    def __init__(self, path, project_id, root=None):
        self.path = Path(path).expanduser().resolve(strict=True)
        self.skills = skills_root(root)
        self.project_id = project_id
        # A missing/unrelated database must never be created by the matcher.
        probe = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            if probe.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise ValueError("Requires existing engineering schema version 2")
            if [r[0] for r in probe.execute("SELECT version FROM registry_migrations")] != [1]:
                raise ValueError("Requires document registry migration 1")
            if not probe.execute("SELECT 1 FROM registry_projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("Unknown registered project ID")
        finally:
            probe.close()
        registry_scripts = str(self.skills / "mep-document-registry/scripts")
        if registry_scripts not in sys.path:
            sys.path.insert(0, registry_scripts)
        from mep_registry.db import Registry
        self.registry = Registry(self.path, skills_root=self.skills)
        self.conn = self.registry.conn
        try:
            exists = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='eq_migrations'").fetchone()
            if exists:
                if [r[0] for r in self.conn.execute("SELECT version FROM eq_migrations")] != [1]:
                    raise ValueError("Unsupported equipment migration; refusing automatic replacement")
            else:
                sql = (Path(__file__).resolve().parent.parent / "migrations/001_equipment.sql").read_text(encoding="utf-8")
                try:
                    self.conn.executescript("BEGIN IMMEDIATE;\n" + sql)
                    self.conn.execute("INSERT INTO eq_migrations VALUES(1,?)", (now(),))
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
            self.conn.execute("BEGIN IMMEDIATE")
            for table in ("eq_migrations", "eq_categories", "eq_imports", "eq_occurrences", "eq_parameters", "eq_entities",
                          "eq_entity_sources", "eq_runs", "eq_results", "eq_matches", "eq_relationships", "eq_issues", "eq_reviews"):
                pk = "version" if table == "eq_migrations" else "run_id" if table == "eq_results" else "id"
                for operation in ("UPDATE", "DELETE"):
                    self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable equipment evidence'); END")
                self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {pk}=NEW.{pk}) BEGIN SELECT RAISE(ABORT,'Immutable equipment key'); END")
            self.conn.commit()
        except BaseException:
            self.registry.close()
            raise

    def close(self):
        self.registry.close()

    @contextmanager
    def transaction(self):
        if self.conn.in_transaction:
            raise RuntimeError("Unexpected nested equipment transaction")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def rows(self, table):
        allowed = {"eq_imports", "eq_occurrences", "eq_parameters", "eq_entities", "eq_entity_sources", "eq_runs", "eq_matches", "eq_relationships", "eq_issues", "eq_reviews", "eq_categories"}
        if table not in allowed:
            raise ValueError("Unknown equipment table")
        return [dict(r) for r in self.conn.execute(f"SELECT rowid AS sequence,* FROM {table} WHERE project_id=? ORDER BY rowid", (self.project_id,))]

    def insert(self, table, values):
        # Callers use fixed internal names only. No SQL identifiers from source content.
        if self.conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (values["id"],)).fetchone():
            return False
        self.conn.execute(f"INSERT INTO {table}({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values()))
        return True

    def documents(self):
        result = self.registry.snapshot(self.project_id)
        self.conn.commit()  # Existing snapshot may append registry revision derivations.
        return result

    def file(self, file_id):
        snapshot = self.documents()
        item = next((f for f in snapshot["files"] if f["file_id"] == file_id), None)
        if not item:
            raise ValueError("File is not current/present in this project; register/rescan first")
        item = dict(item)
        item["sheets"] = [s for s in snapshot["sheets"] if s["file_id"] == file_id]
        return item

    def archived_path(self, file):
        path = Path(file["archive_path"])
        if not path.is_absolute():
            path = self.path.parent / path
        if not path.is_file() or sha(path) != file["sha256"]:
            raise ValueError("Registered evidence archive missing or SHA-256 mismatch")
        return path

    def import_records(self, file, slot, role, manifest, records, issues, cfg):
        if role not in {"drawing", "schedule", "boq", "electrical", "bms", "register", "specification"}:
            raise ValueError("Unsupported source role")
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError("A stable import slot is required")
        if len(records) > cfg["max_records"]:
            raise ValueError("Record limit exceeded; use explicit smaller source partitions")
        manifest = {**manifest, "implementation_signature": implementation_signature(self.skills)}
        signature = key("equipment-import/1", file["analysis_id"], manifest, records, issues, cfg)
        identity = key(self.project_id, file["file_id"], slot, signature)
        if self.conn.execute("SELECT 1 FROM eq_imports WHERE id=?", (identity,)).fetchone():
            return {"import_id": identity, "unchanged": True, "occurrences": 0}
        with self.transaction():
            self.insert("eq_imports", {"id": identity, "project_id": self.project_id, "file_id": file["file_id"],
                        "version_id": file["version_id"], "analysis_id": file["analysis_id"], "slot": slot,
                        "signature": signature, "role": role, "status": "partial" if issues else "processed",
                        "manifest_json": dump({**manifest, "config": cfg}), "issues_json": dump(issues), "created_at": now()})
            for index, record in enumerate(records):
                self._occurrence(identity, file, role, index, record, cfg)
        return {"import_id": identity, "unchanged": False, "occurrences": len(records), "issues": issues}

    def cached_import(self, file, slot, role, manifest, cfg):
        row = self.conn.execute("SELECT id,manifest_json,status FROM eq_imports WHERE project_id=? AND file_id=? AND analysis_id=? AND slot=? AND role=? ORDER BY rowid DESC LIMIT 1",
            (self.project_id, file["file_id"], file["analysis_id"], slot, role)).fetchone()
        expected = {**manifest, "config": cfg, "implementation_signature": implementation_signature(self.skills)}
        if row and json.loads(row["manifest_json"]) == expected and row["status"] in ("processed", "partial"):
            return {"import_id": row["id"], "unchanged": True, "extraction_reused": True, "occurrences": 0}
        return None

    def _occurrence(self, import_id, file, role, index, record, cfg):
        data = dict(record.get("data", {}))
        source = dict(record.get("source", {}))
        if not source.get("method"):
            raise ValueError("Every occurrence requires source.method")
        page = source.get("pdf_page")
        for field in ("pdf_page", "row"):
            value = source.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f"{field} must be an actual one-based index")
        if file["extension"] == "pdf" and page is None:
            raise ValueError("PDF occurrences require actual page evidence")
        sheet = next((s for s in file["sheets"] if s["pdf_page"] == page), None)
        context = sheet or file
        data["context_provenance"] = dict(data.get("context_provenance", {}))
        for field in ("discipline", "system", "building", "floor", "drawing_number", "revision"):
            registry_field = "document_number" if field == "drawing_number" else field
            if data.get(field) in (None, "") and context["metadata"].get(registry_field) is not None:
                data[field] = context["metadata"][registry_field]
                data["context_provenance"][field] = context["provenance"].get(registry_field)
        original_tag = data.get("tag")
        normalized = tag(original_tag, cfg)
        cat, method = category(data.get("category"), normalized, data.get("description"), cfg)
        inferred_category = category(None, normalized, None, cfg)[0]
        if data.get("category") and inferred_category and cat != inferred_category:
            data["classification_conflict"] = {"explicit_category": cat, "tag_prefix_candidate": inferred_category}
        category_id = None
        if cat:
            category_id = key(self.project_id, "category", cat)
            definition = next((c for c in cfg["categories"] if c["id"] == cat), {"id": cat})
            self.insert("eq_categories", {"id": category_id, "project_id": self.project_id, "name": cat,
                                         "config_json": dump(definition), "created_at": now()})
            if data.get("discipline") is None and definition.get("discipline"):
                data["discipline"] = definition["discipline"]
                data["context_provenance"]["discipline"] = {"method": "category_config_inference"}
        data.update(normalized_tag=normalized, category=cat, category_method=method, role=role)
        if isinstance(data.get("scope"), (dict, list)):
            data["scope_original"] = data["scope"]
            data["scope"] = dump(data["scope"])
        for field in ("category", "system", "building", "floor", "room", "discipline", "description"):
            if isinstance(data.get(field), (dict, list, bool)):
                raise ValueError(f"Equipment {field} must be a scalar or null")
        for field in ("discipline", "building", "floor"):
            data[field] = alias(data.get(field), cfg.get(field + "_aliases", {}))
        kind = data.get("identity_kind") or ("group" if role == "boq" else "reference" if role in ("electrical", "bms", "specification") else "instance")
        if kind not in ("instance", "type", "group", "reference"):
            raise ValueError("identity_kind must be instance/type/group/reference")
        if not normalized and kind == "instance":
            kind = "reference"
        declared = decimal(data.get("quantity"))
        if kind == "instance" and declared is not None and declared != 1:
            kind = "group"
            data["identity_warning"] = "A non-unit declared quantity does not identify a single physical instance"
        data["identity_kind"] = kind
        source.update(file_id=file["file_id"], version_id=file["version_id"], analysis_id=file["analysis_id"],
                      document_id=file["metadata"].get("document_number"), relative_path=file["relative_path"],
                      sha256=file["sha256"], registry_sheet_id=sheet["sheet_id"] if sheet else None,
                      document_revision=data.get("revision"), drawing_number=data.get("drawing_number"),
                      drawing_sheet=sheet["metadata"].get("sheet_number") if sheet else None)
        occurrence_id = key(self.project_id, import_id, index, record)
        core_record = record.get("core_record_id")
        if core_record and not self.conn.execute("SELECT 1 FROM records r JOIN versions v ON v.id=r.version_id WHERE r.id=? AND v.sha256=?", (core_record, file["sha256"])).fetchone():
            raise ValueError("Core record does not refer to this registered source hash")
        self.insert("eq_occurrences", {"id": occurrence_id, "project_id": self.project_id, "import_id": import_id,
            "sheet_id": sheet["sheet_id"] if sheet else None, "core_record_id": core_record,
            "original_tag": str(original_tag) if original_tag is not None else None, "normalized_tag": normalized,
            "category_id": category_id, "identity_kind": kind, "source_json": dump(source),
            "raw_json": dump(record), "data_json": dump(data), "created_at": now()})
        for number, raw in enumerate(data.get("parameters", [])):
            normalized_parameter = parameter(raw, cfg)
            self.insert("eq_parameters", {"id": key(occurrence_id, number, raw), "project_id": self.project_id,
                "occurrence_id": occurrence_id, "name": normalized_parameter["name"],
                "payload_json": dump(normalized_parameter), "created_at": now()})
        if kind in ("instance", "type", "group"):
            self.entity(kind, {"occurrence_id": occurrence_id, "candidate_only": True}, [occurrence_id])
        text = " ".join(str(data.get(f) or "") for f in ("tag", "normalized_tag", "description", "category", "discipline", "system", "building", "floor", "room"))
        self.conn.execute("INSERT INTO eq_fts(project_id,occurrence_id,text) VALUES(?,?,?)", (self.project_id, occurrence_id, text))

    def entity(self, kind, basis, occurrence_ids):
        identity = key(self.project_id, kind, basis, sorted(occurrence_ids))
        self.insert("eq_entities", {"id": identity, "project_id": self.project_id, "kind": kind,
                                   "basis_json": dump(basis), "created_at": now()})
        for occurrence_id in sorted(set(occurrence_ids)):
            self.insert("eq_entity_sources", {"id": key(identity, occurrence_id), "project_id": self.project_id,
                "entity_id": identity, "occurrence_id": occurrence_id})
        return identity

    def current(self, history=False):
        registry = self.documents()
        files = {f["file_id"]: f for f in registry["files"]}
        latest = {}
        imports = self.rows("eq_imports")
        for row in imports:
            if row["file_id"] in files and row["analysis_id"] == files[row["file_id"]]["analysis_id"]:
                latest[(row["file_id"], row["slot"])] = row["id"]
        current_ids = set(latest.values())
        reviews = self.rows("eq_reviews")
        import_by_id = {i["id"]: i for i in imports}
        raw_occurrences = self.rows("eq_occurrences")
        occurrence_imports = {o["id"]: o["import_id"] for o in raw_occurrences}
        corrections = {r["target_id"]: r for r in reviews if r["target_kind"] in ("occurrence", "parameter") and r["decision"] == "correct"}
        correction_values = {}
        for event in reviews:
            if event["target_kind"] in ("occurrence", "parameter") and event["decision"] == "correct":
                correction_values.setdefault(event["target_id"], {}).update(json.loads(event["value_json"]))
        parameters = {}
        for row in self.rows("eq_parameters"):
            payload = json.loads(row["payload_json"])
            payload.update(id=row["id"], original_payload=json.loads(row["payload_json"]), verification_status="unreviewed")
            if row["id"] in corrections:
                change = corrections[row["id"]]
                cfg = json.loads(import_by_id[occurrence_imports[row["occurrence_id"]]]["manifest_json"])["config"]
                payload = {**payload, **parameter({"name": row["name"], "value": payload["original"].get("value"), "unit": payload["original"].get("unit"), **correction_values[row["id"]]}, cfg), "review_id": change["id"], "verification_status": "reviewed_correction"}
            approval = next((r for r in reversed(reviews) if r["target_kind"] == "parameter" and r["target_id"] == row["id"]), None)
            if approval and approval["decision"] == "approve_value":
                payload.update(verification_status="approved", review_id=approval["id"])
            parameters.setdefault(row["occurrence_id"], []).append(payload)
        occurrences = []
        for row in raw_occurrences:
            is_current = row["import_id"] in current_ids
            if not history and not is_current:
                continue
            data = json.loads(row["data_json"])
            data["original_data"] = json.loads(row["data_json"])
            if row["id"] in corrections:
                data.update(correction_values[row["id"]])
                data["correction_review_id"] = corrections[row["id"]]["id"]
                if "category" in correction_values[row["id"]]:
                    data["category_method"] = "engineering_review"
            data["verification_status"] = "reviewed_correction" if row["id"] in corrections else "unreviewed"
            data.update(id=row["id"], import_id=row["import_id"], source=json.loads(row["source_json"]),
                        raw=json.loads(row["raw_json"]), is_current=is_current, parameters=parameters.get(row["id"], []))
            data["normalized_tag"] = tag(data.get("tag"), json.loads(import_by_id[row["import_id"]]["manifest_json"])["config"])
            applicable = [r for r in registry["revisions"] if r["analysis_id"] == data["source"]["analysis_id"] and r.get("sheet_id") == data["source"].get("registry_sheet_id")]
            data["revision_status"] = applicable[-1]["verification_status"] if applicable else "unreviewed"
            occurrences.append(data)
        return {"project": registry["project"], "registry": registry, "imports": imports,
                "current_import_ids": sorted(current_ids), "occurrences": occurrences, "reviews": reviews}

    def basis(self, state, cfg):
        return key("equipment-match/1", implementation_signature(self.skills), cfg, state["current_import_ids"],
                   [(f["file_id"], f["analysis_id"], f["metadata"], f["provenance"]) for f in state["registry"]["files"]],
                   state["registry"]["revisions"],
                   [(r["id"], r["value_json"]) for r in state["reviews"] if r["decision"] == "correct"])

    def run_for(self, state, cfg):
        basis = self.basis(state, cfg)
        row = self.conn.execute("SELECT r.* FROM eq_runs r JOIN eq_results x ON x.run_id=r.id WHERE r.project_id=? AND r.basis_hash=? AND x.status='complete' ORDER BY r.rowid DESC LIMIT 1", (self.project_id, basis)).fetchone()
        return dict(row) if row else None

    def target_basis(self, kind, target, state, cfg):
        if kind in ("match", "relationship", "issue"):
            run = self.run_for(state, cfg)
            table = {"match": "eq_matches", "relationship": "eq_relationships", "issue": "eq_issues"}[kind]
            row = self.conn.execute(f"SELECT run_id FROM {table} WHERE project_id=? AND id=?", (self.project_id, target)).fetchone()
            if not run or not row or row[0] != run["id"]:
                raise ValueError("Target is stale/not in this project; run match and review current proposals")
            return run["basis_hash"]
        occurrences = {o["id"]: o for o in state["occurrences"]}
        if kind == "occurrence" and target in occurrences:
            return key(occurrences[target])
        if kind == "parameter":
            found = [(o, p) for o in occurrences.values() for p in o["parameters"] if p["id"] == target]
            if found:
                return key(found[0])
        if kind == "entity":
            row = self.conn.execute("SELECT * FROM eq_entities WHERE project_id=? AND id=?", (self.project_id, target)).fetchone()
            sources = [r[0] for r in self.conn.execute("SELECT occurrence_id FROM eq_entity_sources WHERE project_id=? AND entity_id=?", (self.project_id, target))]
            if row and sources and all(s in occurrences and occurrences[s]["revision_status"] != "superseded" for s in sources):
                fingerprints = json.loads(row["basis_json"]).get("source_fingerprints", {})
                if any(oid not in occurrences or key(occurrences[oid]) != fingerprint for oid, fingerprint in fingerprints.items()):
                    raise ValueError("Stale type/group proposal; regenerate grouping from current observations")
                return key(dict(row), [occurrences[s] for s in sorted(sources)])
        raise ValueError("Unknown, historical, superseded or foreign-project review target")

    def review(self, kind, target, decision, actor, reason, value, cfg):
        if not actor.strip() or not reason.strip():
            raise ValueError("Actual reviewer and decision reason required")
        allowed = {"match": {"confirm", "reject"}, "relationship": {"confirm", "reject"},
                   "issue": {"confirm_discrepancy", "resolve", "not_applicable", "reopen"},
                   "occurrence": {"correct"}, "parameter": {"correct", "approve_value", "reject_value"},
                   "entity": {"confirm_instance", "confirm_type", "confirm_group", "reject"}}
        if decision not in allowed.get(kind, set()):
            raise ValueError("Invalid target/decision combination")
        if decision != "correct" and value is not None:
            raise ValueError("Only a correction accepts --value-json")
        if decision == "correct":
            permitted = {"value", "unit"} if kind == "parameter" else {"tag", "category", "discipline", "system", "building", "floor", "room", "description", "scope"}
            if not isinstance(value, dict) or not value or set(value) - permitted or any(isinstance(v, (dict, list, bool)) for v in value.values()):
                raise ValueError("Correction requires an object of supported scalar fields")
        state = self.current()
        basis = self.target_basis(kind, target, state, cfg)
        if kind == "entity" and decision != "reject":
            entity_row = self.conn.execute("SELECT kind,basis_json FROM eq_entities WHERE id=?", (target,)).fetchone()
            entity = entity_row[0]
            if decision != "confirm_" + entity:
                raise ValueError("Decision must correspond to the entity kind")
            if entity == "type" and not json.loads(entity_row[1]).get("material_configuration_complete"):
                raise ValueError("Type needs complete configured material parameters; propose groups after supplying the missing evidence")
        if kind == "match" and decision == "confirm":
            row = self.conn.execute("SELECT evidence_json FROM eq_matches WHERE id=?", (target,)).fetchone()
            if json.loads(row[0]).get("blocking_conflicts"):
                raise ValueError("Correct conflicting identity/parameters first; rerun matching")
        with self.transaction():
            identity = uuid.uuid4().hex
            self.insert("eq_reviews", {"id": identity, "project_id": self.project_id, "target_kind": kind,
                "target_id": target, "decision": decision, "actor": actor.strip(), "reason": reason.strip(),
                "value_json": dump(value), "basis_hash": basis, "created_at": now()})
            if decision == "correct" and kind == "occurrence":
                self.conn.execute("INSERT INTO eq_fts(project_id,occurrence_id,text) VALUES(?,?,?)", (self.project_id, target, " ".join(str(v) for v in value.values() if v is not None)))
        return {"review_id": identity, "decision": decision, "target_id": target}
