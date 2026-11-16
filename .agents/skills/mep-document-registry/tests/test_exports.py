"""Export boundary tests; all records are explicitly synthetic fixtures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mep_registry.exports import export_snapshot


def fixture():
    metadata = {key: None for key in (
        "document_number", "title", "revision", "revision_date", "issue_status",
        "discipline", "document_type", "system", "building", "floor", "scale", "sheet_number")}
    metadata.update(document_number="SYNTHETIC-M-01", issue_status="For review")
    provenance = {"document_number": {"observation_id": "obs-fixture", "evidence_class": "content_extracted",
        "confidence": "high", "review_status": "unreviewed", "source": {"pdf_page": 1, "bbox": [1, 2, 3, 4]}}}
    return {
        "project": {"id": "synthetic-export-test", "root": "C:\\Synthetic Input", "name": "Synthetic export fixture"},
        "generated_at": "2026-10-27T00:00:00Z",
        "files": [{"file_id": "file-fixture", "version_id": "version-fixture", "analysis_id": "analysis-fixture",
            "relative_path": "M\\drawing.pdf", "filename": "drawing.pdf", "extension": "pdf", "size": 10,
            "sha256": "a" * 64, "modified_at": None, "registration_status": "registered",
            "metadata": metadata, "provenance": provenance, "registry_status": "unreviewed", "sheet_count": 2}],
        "sheets": [{"sheet_id": "sheet-1", "file_id": "file-fixture", "version_id": "version-fixture",
            "analysis_id": "analysis-fixture", "relative_path": "M\\drawing.pdf", "pdf_page": 1,
            "metadata": {"sheet_number": "M-01", "revision": "A"}, "provenance": provenance, "registry_status": "unreviewed"},
            {"sheet_id": "sheet-2", "file_id": "file-fixture", "version_id": "version-fixture",
            "analysis_id": "analysis-fixture", "relative_path": "M\\drawing.pdf", "pdf_page": 2,
            "metadata": {"sheet_number": "M-02", "revision": "B"}, "provenance": {}, "registry_status": "unreviewed"}],
        "relationships": [{"relationship_id": "rel-fixture", "type": "representation_match",
            "left": {"kind": "file", "id": "file-fixture", "relative_path": "M\\drawing.pdf", "pdf_page": None},
            "right": {"kind": "sheet", "id": "sheet-1", "relative_path": "M\\drawing.pdf", "pdf_page": 1},
            "evidence": {"rule_id": "synthetic-name-rule", "bbox": [1, 2, 3, 4]},
            "confidence": "low", "verification_status": "proposed"}],
        "issues": [{"issue_id": "issue-fixture", "code": "MISSING_METADATA", "message": "Synthetic issue",
            "severity": "review", "status": "open", "file_id": "file-fixture", "analysis_id": "analysis-fixture",
            "relative_path": "M\\drawing.pdf", "pdf_page": None, "source": {"cad_handle": "F00", "coordinates": [1, 2]}}],
        "observations": [{"observation_id": "obs-fixture", "file_id": "file-fixture", "sheet_id": None,
            "field": "document_number", "value": "SYNTHETIC-M-01", "evidence_class": "content_extracted",
            "confidence": "high", "source": {"pdf_page": 1, "bbox": [1, 2, 3, 4]}, "review_status": "unreviewed"}],
        "reviews": [{"review_id": "review-fixture", "actor": "Synthetic Reviewer", "decision": "reopen_issue",
            "reason": "Synthetic test only", "target_type": "issue", "target_id": "issue-fixture"}],
        "summary": {"file_count": 1, "sheet_count": 2, "processed_files": 1, "unchanged_files": 0,
            "errors": 0, "classified_documents": 0, "review_requirements": 1},
        "scan": {"run_id": "scan-fixture", "status": "completed", "counters": {}}}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="export-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "new-output"

    def test_exports_all_artifacts_without_mutating_snapshot(self):
        snapshot = fixture()
        before = copy.deepcopy(snapshot)
        result = export_snapshot(snapshot, self.output)
        names = {"document_register.xlsx", "document_relationships.md", "document_relationships.json",
            "issues_for_review.json", "registry_summary.json", ".mep-registry-output.json"}
        self.assertEqual({path.name for path in self.output.iterdir()}, names)
        self.assertTrue(result)
        self.assertEqual(snapshot, before)
        self.assertEqual(json.loads((self.output / ".mep-registry-output.json").read_text(encoding="utf-8"))["status"], "complete")
        self.assertEqual(json.loads((self.output / "document_relationships.json").read_text(encoding="utf-8")), before["relationships"])
        self.assertEqual(json.loads((self.output / "issues_for_review.json").read_text(encoding="utf-8")), before["issues"])
        saved = json.loads((self.output / "registry_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["files"][0]["provenance"]["document_number"]["source"]["bbox"], [1, 2, 3, 4])
        workbook = load_workbook(self.output / "document_register.xlsx")
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["Files", "DrawingSheets", "Issues", "Relationships", "Observations", "ReviewHistory"])
        rows = list(workbook["Files"].values)
        file_row = dict(zip(rows[0], rows[1]))
        self.assertEqual(file_row["issue_status"], "For review")
        self.assertEqual(file_row["registry_status"], "unreviewed")
        self.assertIsNone(file_row["revision"])
        self.assertEqual(file_row["actual_file_path"], "C:\\Synthetic Input\\M\\drawing.pdf")
        sheets = list(workbook["DrawingSheets"].values)
        self.assertEqual(dict(zip(sheets[0], sheets[2]))["revision"], "B")
        relationships = list(workbook["Relationships"].values)
        self.assertEqual(dict(zip(relationships[0], relationships[1]))["verification_status"], "proposed")
        for sheet in workbook:
            self.assertEqual(sheet.freeze_panes, "A2")
            self.assertTrue(sheet.auto_filter.ref)

    def test_untrusted_strings_remain_literal_and_no_external_links(self):
        snapshot = fixture()
        hostile = ["=1+1", "+SUM(A1)", "-1+2", "@SUM(A1)", "=HYPERLINK(\"https://invalid\",\"x\")", "\u4e2d\u6587\u0645\u0644\u0641.pdf", "\t=CMD()"]
        snapshot["files"] = []
        for index, name in enumerate(hostile):
            record = copy.deepcopy(fixture()["files"][0])
            record.update(file_id=str(index), filename=name, relative_path=name)
            record["metadata"]["title"] = name
            snapshot["files"].append(record)
        export_snapshot(snapshot, self.output)
        workbook = load_workbook(self.output / "document_register.xlsx", data_only=False)
        self.addCleanup(workbook.close)
        headers = [cell.value for cell in workbook["Files"][1]]
        for row, name in zip(list(workbook["Files"].iter_rows())[1:], hostile):
            for field in ("filename", "relative_path", "title"):
                cell = row[headers.index(field)]
                self.assertEqual(cell.value, name)
                self.assertEqual(cell.data_type, "s")
                self.assertIsNone(cell.hyperlink)
        with ZipFile(self.output / "document_register.xlsx") as archive:
            self.assertFalse(any("externallink" in name.lower() or "vbaproject" in name.lower() for name in archive.namelist()))

    def test_markdown_escapes_source_structure_and_retains_proposal_status(self):
        snapshot = fixture()
        snapshot["relationships"][0]["left"]["relative_path"] = "pipe|`tick`\n<script>alert(1)</script>[click](https://invalid).pdf"
        export_snapshot(snapshot, self.output)
        text = (self.output / "document_relationships.md").read_text(encoding="utf-8")
        self.assertNotIn("<script>", text)
        self.assertIn("proposed", text)
        self.assertNotIn("pipe|`tick`", text)
        self.assertNotIn("[click](", text)
        self.assertEqual(len([line for line in text.splitlines() if line.startswith("|")]), 3)

    def test_collision_preserves_existing_file_or_directory(self):
        for existing_file in (False, True):
            with self.subTest(existing_file=existing_file):
                target = Path(self.temp.name) / str(existing_file)
                if existing_file:
                    target.write_text("original", encoding="utf-8")
                else:
                    target.mkdir()
                    (target / "keep.txt").write_text("original", encoding="utf-8")
                with self.assertRaises(FileExistsError):
                    export_snapshot(fixture(), target)
                kept = target if existing_file else target / "keep.txt"
                self.assertEqual(kept.read_text(encoding="utf-8"), "original")

    def test_invalid_snapshot_never_creates_output(self):
        invalid = [None, {}, {**fixture(), "files": {}}, {**fixture(), "sheets": [None]},
            {**fixture(), "summary": {"errors": float("nan")}},
            {**fixture(), "relationships": [{"relationship_id": "broken", "left": []}]}]
        for snapshot in invalid:
            with self.subTest(snapshot_type=type(snapshot).__name__):
                with self.assertRaises((ValueError, TypeError)):
                    export_snapshot(snapshot, self.output)
                self.assertFalse(self.output.exists())

    def test_empty_snapshot_does_not_invent_rows(self):
        snapshot = fixture()
        for key in ("files", "sheets", "issues", "relationships", "observations", "reviews"):
            snapshot[key] = []
        export_snapshot(snapshot, self.output)
        workbook = load_workbook(self.output / "document_register.xlsx")
        self.addCleanup(workbook.close)
        self.assertTrue(all(sheet.max_row == 1 for sheet in workbook))
        self.assertEqual(json.loads((self.output / "issues_for_review.json").read_text(encoding="utf-8")), [])

    def test_write_failure_leaves_incomplete_exclusion_marker(self):
        # Workbook serialization is the actual I/O boundary; simulate its disk failure.
        with patch("openpyxl.workbook.workbook.Workbook.save", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                export_snapshot(fixture(), self.output)
        marker = json.loads((self.output / ".mep-registry-output.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "incomplete")
        with self.assertRaises(FileExistsError):
            export_snapshot(fixture(), self.output)

    def test_large_values_and_xml_controls_have_lossless_json_companion(self):
        snapshot = fixture()
        original = "SYNTHETIC\x00" + "\u957f" * 33000
        snapshot["files"][0]["metadata"]["title"] = original
        snapshot["revisions"] = [{"revision_id": "synthetic-revision", "verification_status": "unreviewed"}]
        export_snapshot(snapshot, self.output)
        saved = json.loads((self.output / "registry_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["files"][0]["metadata"]["title"], original)
        self.assertEqual(saved["revisions"][0]["revision_id"], "synthetic-revision")
        workbook = load_workbook(self.output / "document_register.xlsx")
        self.addCleanup(workbook.close)
        headers = [cell.value for cell in workbook["Files"][1]]
        title = workbook["Files"].cell(2, headers.index("title") + 1).value
        self.assertLessEqual(len(title), 32767)
        self.assertIn("\\u0000", title)
        self.assertIn("registry_summary.json", title)


if __name__ == "__main__":
    unittest.main()
