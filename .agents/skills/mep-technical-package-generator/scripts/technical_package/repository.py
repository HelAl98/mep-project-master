"""Read-only facade over inspected upstream projections; no constructors/migrations."""
import importlib
import json
from pathlib import Path
import sqlite3
import sys

from .common import key, sha


DEPENDENCIES = {"mep-document-registry": "scripts/mep_registry/db.py",
                "mep-equipment-matcher": "scripts/equipment_matcher/storage.py",
                "mep-cross-document-reviewer": "scripts/technical_review/actions.py"}


def locate(explicit=None):
    for parent in ([Path(explicit)] if explicit else Path(__file__).resolve().parents):
        for root in (parent, parent / ".agents/skills"):
            if all((root / skill / path).is_file() for skill, path in DEPENDENCIES.items()):
                return root.resolve()
    raise ValueError("Essential Registry/Matcher/Reviewer interface missing; supply --skills-root. Missing skills are not rebuilt.")


class Repository:
    def __init__(self, path, project, reviewer_config=None, skills=None):
        self.path = Path(path).expanduser().resolve(strict=True)
        self.project = project
        self.skills = locate(skills)
        for name in DEPENDENCIES:
            directory = str(self.skills / name / "scripts")
            if directory not in sys.path:
                sys.path.insert(0, directory)
        registry_db = importlib.import_module("mep_registry.db")
        registry_common = importlib.import_module("mep_registry.common")
        equipment_db = importlib.import_module("equipment_matcher.storage")
        review_store = importlib.import_module("technical_review.storage")
        review_common = importlib.import_module("technical_review.common")
        self.actions = importlib.import_module("technical_review.actions")
        self.export_helpers = importlib.import_module("technical_review.exports")
        self.conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=30)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA query_only=ON")
            self.conn.execute("BEGIN")
            if self.conn.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise ValueError("Requires existing core schema 2")
            for table in ("registry_migrations", "eq_migrations", "tr_migrations"):
                if [r[0] for r in self.conn.execute(f"SELECT version FROM {table}")] != [1]:
                    raise ValueError(f"Requires existing {table} version 1; upstream processing is not performed here")
            row = self.conn.execute("SELECT * FROM registry_projects WHERE id=?", (project,)).fetchone()
            if not row:
                raise ValueError("Unknown registered project")
            self.project_row = dict(row)
            # Registry.snapshot's only evidence-creation boundary is overridden. Never call its initializer.
            class ReadRegistry(registry_db.Registry):
                def __init__(self, conn):
                    self.conn = conn
                def _revision_rows(self, project_id, items, reviews):
                    identities = set()
                    for item in items:
                        metadata = item["metadata"]
                        if metadata.get("document_number") or metadata.get("revision"):
                            provenance = {f: item["provenance"].get(f) for f in ("document_number", "revision", "revision_date", "issue_status")}
                            identities.add(registry_common.key(item.get("sheet_id") or item["file_id"], item["analysis_id"], metadata.get("document_number"), metadata.get("revision"), metadata.get("revision_date"), metadata.get("issue_status"), provenance))
                    return identities
                def transaction(self):
                    raise RuntimeError("Package generation cannot write registry evidence")
                def _insert(self, *args, **kwargs):
                    raise RuntimeError("Package generation cannot insert registry evidence")
            class ReadEquipment(equipment_db.Database):
                def __init__(self, conn, path, root):
                    self.conn, self.path, self.skills, self.project_id = conn, path, root, project
                    self.registry = ReadRegistry(conn)
                def documents(self):
                    return self.registry.snapshot(project)
                def transaction(self):
                    raise RuntimeError("Package generation cannot write equipment evidence")
                def insert(self, *args, **kwargs):
                    raise RuntimeError("Package generation cannot insert equipment evidence")
            class ReadTechnical(review_store.Store):
                def __init__(self, conn, path, root, cfg):
                    self.conn, self.path, self.skills, self.project, self.cfg = conn, path, root, project, cfg
                    self.ec = importlib.import_module("equipment_matcher.common")
                    self.em = importlib.import_module("equipment_matcher.matching")
                    self.es = importlib.import_module("equipment_matcher.sources")
                    self.legacy = ReadEquipment(conn, path, root)
                def transaction(self):
                    raise RuntimeError("Package generation is strictly read-only")
                def insert(self, *args, **kwargs):
                    raise RuntimeError("Package generation cannot create reviews or requirements")
            self.view = ReadTechnical(self.conn, self.path, self.skills, review_common.configuration(reviewer_config))
        except BaseException:
            self.close()
            raise

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.rollback()
            self.conn.close()
            self.conn = None

    def record(self, category=None, tag=None, entity_id=None):
        # This is a projection of stored reviews; no index/map/compare/match action is invoked.
        return self.actions.snapshot(self.view, entity_id=entity_id, tag=tag, category=category, history=True)

    def upstream(self):
        return self.view.upstream()

    def code_signature(self):
        own = Path(__file__).resolve().parent.parent
        return key(self.view.signature(), [(str(p.relative_to(own)), sha(p)) for p in sorted(own.rglob("*.py"))])

    def project_state(self):
        # Stable source-state receipt excludes generated timestamps and unchanged rescan run IDs.
        heads = [dict(r) for r in self.view.legacy.registry._current(self.project)]
        heads = [{k: row.get(k) for k in ("file_id", "version_id", "analysis_id", "status", "sha256", "observed_path")} for row in heads]
        for head in heads:
            if head["status"] not in ("missing", "excluded", "error"):
                head["status"] = "present"
        reviews = self.view.legacy.rows("eq_reviews")
        registry_reviews = self.view.legacy.registry._reviews(self.project)
        return {"project_id": self.project, "heads": heads, "eq_review_ids": [r["id"] for r in reviews],
                "registry_review_ids": [r["id"] for r in registry_reviews],
                "imports": [r["id"] for r in self.view.legacy.rows("eq_imports")],
                "requirement_imports": [r["id"] for r in self.view.rows("tr_imports")],
                "interpretations": [r["id"] for r in self.view.rows("tr_interpretations")],
                "comparison_runs": [r["id"] for r in self.view.rows("tr_runs")]}
