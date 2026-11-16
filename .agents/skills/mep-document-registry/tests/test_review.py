"""Forward regressions from independent review; synthetic local sources only."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
SKILLS = next(p / ".agents/skills" for p in HERE.parents
              if (p / ".agents/skills/etl-pipeline/scripts/mep_store.py").is_file())
from mep_registry.db import Registry
from mep_registry.scan import scan_project


class ForwardReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="_review_synthetic_", dir=HERE)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "Synthetic review project"
        self.root.mkdir()
        self.db = self.base / "engineering.sqlite"
        self.pid = "synthetic-forward-review"

    def source(self, name="Synthetic source.txt", text=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "SYNTHETIC REVIEW FIXTURE\nDOCUMENT NUMBER: SYN-101\nREVISION: A\nTITLE: Synthetic review source\n", encoding="utf-8")
        return path

    def scan(self, config=None):
        return scan_project(self.root, self.db, self.pid, config, SKILLS)

    def registry(self):
        registry = Registry(self.db, skills_root=SKILLS)
        self.addCleanup(registry.close)
        return registry

    def test_repeated_missing_scans_do_not_duplicate_the_same_open_review_issue(self):
        source = self.source()
        self.scan()
        source.unlink()
        first = self.scan()
        second = self.scan()
        initial = [i for i in first["issues"] if i["code"] == "SOURCE_NOT_PRESENT"]
        repeated = [i for i in second["issues"] if i["code"] == "SOURCE_NOT_PRESENT"]
        self.assertEqual(len(initial), 1)
        self.assertEqual(len(repeated), 1,
                         "Unchanged absent state must not create another actionable issue per scan")

    def test_excluded_relationship_cannot_be_newly_confirmed(self):
        original = self.source("one.txt")
        shutil.copyfile(original, self.root / "two.txt")
        initial = self.scan()
        relationship = next(r for r in initial["relationships"] if r["type"] == "duplicate_content")
        excluded = self.scan({"exclude_globs": ["*.txt"]})
        self.assertEqual(excluded["files"], [])
        old = next(r for r in excluded["relationships"]
                   if r["relationship_id"] == relationship["relationship_id"])
        self.assertEqual(old["verification_status"], "invalidated")
        with self.assertRaises(ValueError, msg="Excluded evidence is not current review evidence"):
            self.registry().review(self.pid, "relationship", relationship["relationship_id"],
                                   "confirm_relationship", "Synthetic Review Engineer",
                                   "Synthetic excluded-source check")

    def test_generated_output_under_root_is_excluded_after_real_export(self):
        from mep_registry.exports import export_snapshot
        self.source()
        initial = self.scan()
        output = self.root / "Synthetic generated register"
        export_snapshot(initial, output)
        result = self.scan()
        self.assertEqual([f["relative_path"] for f in result["files"]], ["Synthetic source.txt"])
        self.assertEqual(result["summary"]["unchanged_files"], 1)

    def test_disappeared_source_keeps_archived_exact_bytes_and_observations(self):
        source = self.source()
        expected = source.read_bytes()
        initial = self.scan()
        version = initial["files"][0]["version_id"]
        source.unlink()
        absent = self.scan()
        self.assertEqual(absent["files"], [])
        registry = self.registry()
        archive = registry.conn.execute("select archive_path from versions where id=?", (version,)).fetchone()[0]
        self.assertEqual(Path(archive).read_bytes(), expected)
        historical = registry.snapshot(self.pid, history=True)
        self.assertEqual({o["observation_id"] for o in initial["observations"]},
                         {o["observation_id"] for o in historical["observations"]})

    def test_actual_review_identifiers_and_targets_are_visible_in_excel_history(self):
        from mep_registry.exports import export_snapshot
        from openpyxl import load_workbook
        self.source()
        initial = self.scan()
        file_id = initial["files"][0]["file_id"]
        registry = self.registry()
        review = registry.review(self.pid, "file", file_id, "confirm_identity",
                                 "Synthetic Review Engineer", "Synthetic identity review")
        output = self.base / "Synthetic reviewed export"
        export_snapshot(registry.snapshot(self.pid), output)
        workbook = load_workbook(output / "document_register.xlsx", read_only=True)
        try:
            rows = list(workbook["ReviewHistory"].values)
            actual = dict(zip(rows[0], rows[1]))
            self.assertEqual(actual["review_id"], review["review_id"])
            self.assertEqual(actual["target_type"], "file")
            self.assertEqual(actual["target_id"], file_id)
        finally:
            workbook.close()

    def test_page_content_classification_does_not_leak_to_later_unrelated_pages(self):
        from reportlab.pdfgen.canvas import Canvas
        source = self.root / "Synthetic mixed package.pdf"
        canvas = Canvas(str(source), invariant=1)
        canvas.drawString(40, 750, "SYNTHETIC DRAWING PAGE CLASSIFICATION TOKEN")
        canvas.showPage()
        canvas.drawString(40, 750, "SYNTHETIC SPECIFICATION APPENDIX")
        canvas.drawString(40, 730, "DOCUMENT TYPE: Specification")
        canvas.showPage()
        canvas.save()
        result = self.scan({"classification_rules": [{
            "id": "synthetic-first-page-only", "target": "content",
            "pattern": "DRAWING PAGE CLASSIFICATION TOKEN", "fields": {"document_type": "Drawing"}
        }]})
        self.assertEqual([s["pdf_page"] for s in result["sheets"]], [1],
                         "A rule matched on page 1 must not classify a specification appendix as a drawing")


if __name__ == "__main__":
    unittest.main()
