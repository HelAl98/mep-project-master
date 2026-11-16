"""Independent acceptance tests: synthetic documents only, never real project data."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
SKILLS_ROOT = next(p / '.agents/skills' for p in HERE.parents
                  if (p / '.agents/skills/etl-pipeline/scripts/mep_store.py').is_file())
try:
    from mep_registry.db import Registry
    from mep_registry.scan import scan_project
except ModuleNotFoundError as exc:
    if exc.name not in {"mep_registry", "mep_registry.db", "mep_registry.scan"}:
        raise
    Registry = scan_project = None


class RegistryAcceptance(unittest.TestCase):
    """Each fixture is deliberately labeled synthetic and lives below tests/."""

    def setUp(self):
        self.assertIsNotNone(Registry, "New registry implementation is not present")
        self.assertIsNotNone(scan_project, "New scanner implementation is not present")
        self.temp = tempfile.TemporaryDirectory(prefix="_registry_acceptance_", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "Synthetic Project with spaces"
        self.root.mkdir()
        self.db = self.base / "shared engineering.sqlite"
        self.project_id = "synthetic-project-alpha"

    def pdf(self, relative, pages=None):
        from reportlab.pdfgen.canvas import Canvas
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas = Canvas(str(path), pagesize=(612, 792), invariant=1)
        for lines in pages or [self.labels()]:
            for n, line in enumerate(lines):
                canvas.drawString(40, 750 - 18 * n, line)
            canvas.showPage()
        canvas.save()
        return path

    @staticmethod
    def labels(number="SYN-M-101", revision="A", title="Synthetic ventilation layout", sheet="1"):
        return [
            "SYNTHETIC ACCEPTANCE FIXTURE - NOT PROJECT DATA",
            "DRAWING NUMBER: " + number,
            "TITLE: " + title,
            "REVISION: " + revision,
            "DISCIPLINE: HVAC",
            "DOCUMENT TYPE: Drawing",
            "SHEET NUMBER: " + sheet,
            "SCALE: 1:100",
        ]

    def scan(self, root=None, project_id=None, config=None):
        return scan_project(root or self.root, db_path=self.db,
                            project_id=project_id or self.project_id,
                            config=config, skills_root=SKILLS_ROOT)

    def registry(self):
        result = Registry(self.db, skills_root=SKILLS_ROOT)
        self.addCleanup(result.close)
        return result

    @staticmethod
    def hashes(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    @staticmethod
    def file(snapshot, relative):
        return next(f for f in snapshot["files"] if f["relative_path"].replace("\\", "/") == relative)

    def observation(self, snapshot, field, file_id=None):
        return next(o for o in snapshot["observations"]
                    if o["field"] == field and o.get("value") is not None
                    and (file_id is None or o["file_id"] == file_id))

    def test_01_recurses_and_classifies_mixed_documents_without_changing_sources(self):
        self.pdf("Mechanical/Drawings/SYN-M-101.pdf")
        from docx import Document
        doc = Document()
        doc.add_paragraph("SYNTHETIC ACCEPTANCE FIXTURE - NOT PROJECT DATA")
        doc.add_paragraph("TITLE: Synthetic mechanical specification")
        doc.add_paragraph("DOCUMENT TYPE: Specification")
        doc.save(self.root / "Synthetic specification.docx")
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(["SYNTHETIC ACCEPTANCE FIXTURE", "Not project data"])
        book.active.append(["TITLE", "Synthetic equipment schedule"])
        book.save(self.root / "Synthetic schedule.xlsx")
        before = self.hashes(self.root)
        result = self.scan()
        self.assertEqual({f["extension"] for f in result["files"]}, {"pdf", "docx", "xlsx"})
        self.assertEqual(result["summary"]["file_count"], 3)
        drawing = self.file(result, "Mechanical/Drawings/SYN-M-101.pdf")
        self.assertEqual(drawing["metadata"]["document_number"], "SYN-M-101")
        self.assertEqual(drawing["metadata"]["discipline"], "HVAC")
        self.assertEqual(drawing["metadata"]["title"], "Synthetic ventilation layout")
        self.assertEqual(drawing["registry_status"], "unreviewed")
        self.assertEqual(before, self.hashes(self.root))

    def test_02_unchanged_rescan_reuses_document_evidence_and_analysis(self):
        self.pdf("SYN-M-101.pdf")
        first = self.scan()
        second = self.scan()
        for collection, id_key in [("files", "file_id"), ("sheets", "sheet_id"),
                                   ("observations", "observation_id"), ("revisions", "revision_id")]:
            self.assertEqual({r[id_key] for r in first[collection]},
                             {r[id_key] for r in second[collection]}, collection)
        self.assertEqual(first["files"][0]["analysis_id"], second["files"][0]["analysis_id"])
        self.assertEqual(first["files"][0]["version_id"], second["files"][0]["version_id"])
        self.assertEqual(second["summary"]["processed_files"], 0)
        self.assertEqual(second["summary"]["unchanged_files"], 1)
        self.assertNotEqual(first["scan"]["run_id"], second["scan"]["run_id"])

    def test_03_two_named_revisions_remain_unapproved(self):
        self.pdf("SYN-M-101_Rev-A.pdf", [self.labels(revision="A")])
        self.pdf("SYN-M-101_Rev-B.pdf", [self.labels(revision="B")])
        result = self.scan(config={"revision_order": ["A", "B"]})
        self.assertEqual({f["metadata"]["revision"] for f in result["files"]}, {"A", "B"})
        self.assertGreaterEqual(len(result["revisions"]), 2)
        self.assertTrue(all(r["verification_status"] == "unreviewed" for r in result["revisions"]))
        self.assertFalse(result["reviews"])

    def test_04_new_bytes_preserve_old_revision_and_observation_history(self):
        self.pdf("SYN-M-101.pdf", [self.labels(revision="A")])
        first = self.scan()
        self.pdf("SYN-M-101.pdf", [self.labels(revision="B", title="Synthetic revised layout")])
        current = self.scan()
        self.assertEqual(len(current["files"]), 1)
        self.assertEqual(current["files"][0]["file_id"], first["files"][0]["file_id"])
        self.assertNotEqual(current["files"][0]["version_id"], first["files"][0]["version_id"])
        self.assertEqual(current["files"][0]["metadata"]["revision"], "B")
        history = self.registry().snapshot(self.project_id, history=True)
        historical_ids = {o["observation_id"] for o in history["observations"]}
        self.assertTrue({o["observation_id"] for o in first["observations"]}.issubset(historical_ids))
        self.assertTrue({r["revision_id"] for r in first["revisions"]}.issubset(
            {r["revision_id"] for r in history["revisions"]}))

    def test_05_multisheet_pdf_keeps_independent_page_metadata_and_real_bounds(self):
        self.pdf("Combined synthetic drawings.pdf", [
            self.labels("SYN-M-101", "A", "Synthetic page one", "1"),
            self.labels("SYN-E-201", "C", "Synthetic page two", "2"),
        ])
        result = self.scan()
        sheets = sorted(result["sheets"], key=lambda s: s["pdf_page"])
        self.assertEqual([s["pdf_page"] for s in sheets], [1, 2])
        self.assertEqual([s["metadata"]["document_number"] for s in sheets], ["SYN-M-101", "SYN-E-201"])
        self.assertEqual([s["metadata"]["revision"] for s in sheets], ["A", "C"])
        self.assertIsNone(result["files"][0]["metadata"]["document_number"])
        self.assertIsNone(result["files"][0]["metadata"]["revision"])
        for sheet in sheets:
            for provenance in sheet["provenance"].values():
                if provenance.get("evidence_class") != "content_extracted":
                    continue
                source = provenance["source"]
                self.assertEqual(source["pdf_page"], sheet["pdf_page"])
                if source.get("bbox") is not None:
                    x0, y0, x1, y1 = source["bbox"]
                    self.assertTrue(0 <= x0 <= x1 <= 612)
                    self.assertTrue(0 <= y0 <= y1 <= 792)

    def test_06_missing_titleblock_data_remains_null_and_needs_review(self):
        self.pdf("Drawings/unknown.pdf", [["SYNTHETIC DRAWING", "SHEET NUMBER: 1"]])
        result = self.scan(config={"classification_rules": [{
            "id": "synthetic-drawing-folder", "target": "relative_path", "pattern": "Drawings/",
            "fields": {"document_type": "drawing"},
        }]})
        item = result["files"][0]
        for field in ["document_number", "title", "revision", "discipline"]:
            self.assertIsNone(item["metadata"][field], field)
        self.assertTrue(any(i["file_id"] == item["file_id"] and i["status"] == "open"
                            for i in result["issues"]))

    def test_07_similar_dwg_pdf_pair_is_a_proposal_never_auto_confirmation(self):
        self.pdf("SYN-M-101_Rev-A.pdf")
        (self.root / "SYN-M-101_Rev-A.dwg").write_bytes(b"SYNTHETIC DWG PLACEHOLDER; NOT A REAL CAD FILE")
        result = self.scan()
        files = {f["file_id"]: f for f in result["files"]}
        matches = [r for r in result["relationships"]
                   if r["left"].get("id") in files and r["right"].get("id") in files
                   and {files[r["left"]["id"]]["extension"],
                        files[r["right"]["id"]]["extension"]} == {"dwg", "pdf"}]
        self.assertTrue(matches, "Filename resemblance should be a reviewable candidate")
        self.assertTrue(all(r["verification_status"] == "proposed" for r in matches))
        self.assertFalse(result["reviews"])

    def test_08_unreadable_dwg_still_registers_as_pending_without_fabricated_metadata(self):
        path = self.root / "SYN-unknown.dwg"
        path.write_bytes(b"SYNTHETIC DWG PLACEHOLDER")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.scan()
        item = result["files"][0]
        self.assertEqual(item["registration_status"], "registered_metadata_extraction_pending")
        self.assertEqual(item["sha256"], digest)
        self.assertIsNone(item["metadata"]["document_number"])
        self.assertEqual(item["sheet_count"], 0)
        self.assertTrue(result["issues"])
        self.assertFalse([o for o in result["observations"] if o["evidence_class"] == "content_extracted"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_09_duplicate_bytes_at_different_paths_keep_distinct_stable_traceability(self):
        source = self.pdf("one/SYN-M-101.pdf")
        other = self.root / "two" / "SYN-M-101.pdf"
        other.parent.mkdir()
        shutil.copyfile(source, other)
        first = self.scan()
        self.assertEqual(len(first["files"]), 2)
        self.assertEqual(len({f["file_id"] for f in first["files"]}), 2)
        self.assertEqual(len({f["sha256"] for f in first["files"]}), 1)
        for item in first["files"]:
            actual = self.root / item["relative_path"]
            self.assertEqual(hashlib.sha256(actual.read_bytes()).hexdigest(), item["sha256"])
            self.assertTrue(item["version_id"])
        second = self.scan()
        self.assertEqual({(f["relative_path"], f["file_id"]) for f in first["files"]},
                         {(f["relative_path"], f["file_id"]) for f in second["files"]})

    def test_10_corrupt_pdf_does_not_prevent_valid_document_registration(self):
        (self.root / "broken synthetic.pdf").write_bytes(b"%PDF-1.7\nSYNTHETIC CORRUPT FIXTURE")
        self.pdf("valid synthetic.pdf")
        result = self.scan()
        self.assertEqual(len(result["files"]), 2)
        broken = self.file(result, "broken synthetic.pdf")
        self.assertIn(broken["registration_status"], ["error", "registered_with_issues"])
        self.assertTrue(any(i["file_id"] == broken["file_id"] for i in result["issues"]))
        self.assertEqual(self.file(result, "valid synthetic.pdf")["metadata"]["document_number"], "SYN-M-101")

    def test_11_review_actor_reason_and_decision_persist_after_reopening(self):
        self.pdf("SYN-M-101.pdf")
        initial = self.scan()
        revision = initial["revisions"][0]
        registry = self.registry()
        registry.review(self.project_id, "revision", revision["revision_id"], "approve_applicability",
                        "Synthetic Acceptance Engineer", "Synthetic fixture applicability reviewed")
        reopened = self.registry().snapshot(self.project_id)
        self.assertEqual(len(reopened["reviews"]), 1)
        event = reopened["reviews"][0]
        self.assertEqual(event["actor"], "Synthetic Acceptance Engineer")
        self.assertEqual(event["reason"], "Synthetic fixture applicability reviewed")
        self.assertEqual(event["decision"], "approve_applicability")
        self.assertEqual(next(r for r in reopened["revisions"] if r["revision_id"] == revision["revision_id"])
                         ["verification_status"], "applicable")

    def test_12_correction_changes_projection_but_preserves_literal_evidence_and_source_bytes(self):
        self.pdf("SYN-M-101.pdf")
        before = self.hashes(self.root)
        initial = self.scan()
        obs = self.observation(initial, "title")
        registry = self.registry()
        registry.review(self.project_id, "observation", obs["observation_id"], "correct_metadata",
                        "Synthetic Acceptance Engineer", "Synthetic correction exercise",
                        value="Synthetic reviewed title")
        current = registry.snapshot(self.project_id)
        self.assertEqual(current["files"][0]["metadata"]["title"], "Synthetic reviewed title")
        retained = next(o for o in registry.snapshot(self.project_id, history=True)["observations"]
                        if o["observation_id"] == obs["observation_id"])
        for field in ["value", "source", "field", "evidence_class", "confidence"]:
            self.assertEqual(retained[field], obs[field], field)
        self.assertEqual(before, self.hashes(self.root))

    def test_13_changed_hash_does_not_inherit_prior_metadata_correction_or_approval(self):
        self.pdf("SYN-M-101.pdf")
        first = self.scan()
        registry = self.registry()
        obs = self.observation(first, "title")
        revision = first["revisions"][0]
        registry.review(self.project_id, "observation", obs["observation_id"], "correct_metadata",
                        "Synthetic Acceptance Engineer", "Synthetic old-byte correction", value="Old reviewed title")
        registry.review(self.project_id, "revision", revision["revision_id"], "approve_applicability",
                        "Synthetic Acceptance Engineer", "Synthetic old-byte approval")
        self.pdf("SYN-M-101.pdf", [self.labels(revision="B", title="New synthetic source title")])
        current = self.scan()
        self.assertEqual(current["files"][0]["metadata"]["title"], "New synthetic source title")
        self.assertNotEqual(current["files"][0]["sha256"], first["files"][0]["sha256"])
        self.assertTrue(all(r["verification_status"] == "unreviewed" for r in current["revisions"]))
        history = registry.snapshot(self.project_id, history=True)
        self.assertEqual(len(history["reviews"]), 2)
        self.assertIn(obs["observation_id"], {o["observation_id"] for o in history["observations"]})

    def test_14_explicit_projects_share_storage_without_cross_project_snapshots_or_search(self):
        self.pdf("alpha.pdf", [self.labels(title="Synthetic Alpha ConfidentialMarker")])
        alpha = self.scan()
        beta_root = self.base / "Synthetic Beta"
        beta_root.mkdir()
        (beta_root / "beta.dwg").write_bytes(b"SYNTHETIC BETA DWG PLACEHOLDER")
        beta = self.scan(root=beta_root, project_id="synthetic-project-beta")
        registry = self.registry()
        self.assertEqual({f["file_id"] for f in registry.snapshot(self.project_id)["files"]},
                         {f["file_id"] for f in alpha["files"]})
        self.assertTrue({f["file_id"] for f in alpha["files"]}.isdisjoint(
            {f["file_id"] for f in beta["files"]}))
        self.assertTrue(registry.search(self.project_id, "ConfidentialMarker"))
        self.assertFalse(registry.search("synthetic-project-beta", "ConfidentialMarker"))
        foreign_revision = alpha["revisions"][0]["revision_id"]
        with self.assertRaises(ValueError):
            registry.review("synthetic-project-beta", "revision", foreign_revision, "approve_applicability",
                            "Synthetic Acceptance Engineer", "Must reject cross-project target")
        self.assertFalse(registry.snapshot("synthetic-project-beta")["reviews"])

    def test_15_invalid_review_targets_decisions_and_empty_actor_cannot_append_events(self):
        self.pdf("SYN-M-101.pdf")
        snapshot = self.scan()
        registry = self.registry()
        target = snapshot["files"][0]["file_id"]
        invalid = [
            ("file", "does-not-exist", "confirm_identity", "Synthetic Engineer", "Unknown target"),
            ("revision", target, "approve_applicability", "Synthetic Engineer", "Wrong target kind"),
            ("file", target, "confirm_relationship", "Synthetic Engineer", "Incompatible decision"),
            ("file", target, "confirm_identity", "", "Missing actor"),
            ("file", target, "confirm_identity", "   ", "Blank actor"),
            ("file", target, "confirm_identity", "Synthetic Engineer", ""),
        ]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                registry.review(self.project_id, *args)
        self.assertFalse(registry.snapshot(self.project_id)["reviews"])

    def test_16_existing_core_store_opens_before_and_after_without_rewriting_existing_evidence(self):
        sys.path.insert(0, str(SKILLS_ROOT / "etl-pipeline" / "scripts"))
        from mep_store import Store, document_info
        original = self.base / "synthetic_existing_core.txt"
        original.write_text("SYNTHETIC ORIGINAL CORE RECORD", encoding="utf-8")
        store = Store(self.db)
        package = {"schema_version": "mep-evidence/1", "document": document_info(original,
                   {"document_id": "SYN-EXISTING-CORE", "revision": "A"}),
                   "records": [{"kind": "synthetic_metadata", "raw_text": "SYNTHETIC ORIGINAL CORE RECORD",
                                "source": {"method": "synthetic-acceptance-fixture", "row": 1},
                                "data": {"synthetic": True},
                                "review": {"status": "unreviewed", "issues": []}}], "issues": []}
        ingestion = store.ingest(package)
        core_tables = ["records", "runs", "run_records", "reviews", "activations", "evidence_fts"]
        before = {name: [tuple(r) for r in store.conn.execute("SELECT * FROM " + name)] for name in core_tables}
        version_before = tuple(store.conn.execute("SELECT * FROM versions WHERE id=?",
                                                  (ingestion["version_id"],)).fetchone())
        store.close()
        self.pdf("SYN-M-101.pdf")
        self.scan()
        reopened = Store(self.db)
        try:
            self.assertEqual(reopened.conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(tuple(reopened.conn.execute("SELECT * FROM versions WHERE id=?",
                                                        (ingestion["version_id"],)).fetchone()), version_before)
            for name in core_tables:
                self.assertEqual([tuple(r) for r in reopened.conn.execute("SELECT * FROM " + name)], before[name], name)
            self.assertEqual(Path(ingestion["archive_path"]).read_bytes(), original.read_bytes())
            self.assertTrue(reopened.search("SYNTHETIC ORIGINAL CORE RECORD"))
        finally:
            reopened.close()

    def test_17_filename_rules_preserve_inferred_class_and_unreviewed_status(self):
        path = self.root / "SYN-HVAC-unknown.dwg"
        path.write_bytes(b"SYNTHETIC DWG PLACEHOLDER")
        result = self.scan(config={"classification_rules": [{
            "id": "synthetic-hvac-name", "target": "filename", "pattern": "SYN-HVAC-",
            "fields": {"discipline": "HVAC", "document_type": "drawing"},
        }]})
        item = result["files"][0]
        self.assertEqual(item["metadata"]["discipline"], "HVAC")
        self.assertEqual(item["provenance"]["discipline"]["evidence_class"], "filename_derived")
        self.assertEqual(item["provenance"]["discipline"]["review_status"], "unreviewed")
        self.assertIsNone(item["metadata"]["revision"])
        self.assertFalse(result["reviews"])

    def test_18_marked_generated_output_and_explicit_exclusions_are_not_ingested(self):
        self.pdf("source.pdf")
        self.pdf("export copy/copied.pdf")
        (self.root / "export copy" / ".mep-registry-output.json").write_text(
            json.dumps({"project_id": self.project_id, "generated_output": True}), encoding="utf-8")
        self.pdf("archive/excluded.pdf")
        result = self.scan(config={"exclude_globs": ["archive/**"]})
        self.assertEqual([f["relative_path"].replace("\\", "/") for f in result["files"]], ["source.pdf"])
        self.assertEqual(self.scan(config={"exclude_globs": ["archive/**"]})["summary"]["file_count"], 1)

    def test_19_confirmed_relationship_requires_new_review_after_a_source_changes(self):
        self.pdf("SYN-M-101.pdf")
        (self.root / "SYN-M-101.dwg").write_bytes(b"SYNTHETIC DWG PLACEHOLDER")
        first = self.scan()
        relationship = next(r for r in first["relationships"] if r["type"] == "representation_match")
        registry = self.registry()
        registry.review(self.project_id, "relationship", relationship["relationship_id"], "confirm_relationship",
                        "Synthetic Acceptance Engineer", "Synthetic pair reviewed for this source version")
        reviewed = registry.snapshot(self.project_id)
        self.assertEqual(next(r for r in reviewed["relationships"]
                              if r["relationship_id"] == relationship["relationship_id"])
                         ["verification_status"], "confirmed")
        self.pdf("SYN-M-101.pdf", [self.labels(revision="B")])
        changed = self.scan()
        self.assertFalse([r for r in changed["relationships"] if r["verification_status"] == "confirmed"])
        history = registry.snapshot(self.project_id, history=True)
        self.assertEqual(len(history["reviews"]), 1)
        self.assertIn(relationship["relationship_id"], {r["relationship_id"] for r in history["relationships"]})

    def test_20_file_archive_preserves_exact_bytes_and_file_versions_do_not_claim_sheet_revision(self):
        source = self.pdf("Combined synthetic drawings.pdf", [
            self.labels(revision="A", sheet="1"), self.labels(revision="C", sheet="2")])
        original = source.read_bytes()
        result = self.scan()
        item = result["files"][0]
        registry = self.registry()
        row = registry.conn.execute("SELECT archive_path,sha256,revision FROM versions WHERE id=?",
                                    (item["version_id"],)).fetchone()
        self.assertEqual(Path(row[0]).read_bytes(), original)
        self.assertEqual(row[1], hashlib.sha256(original).hexdigest())
        self.assertIsNone(row[2], "A file-byte version cannot represent multiple sheet revisions")
        self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
