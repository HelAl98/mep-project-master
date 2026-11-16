"""Export stored registry snapshots without reopening any source documents.

The JSON summary is also the lossless snapshot companion to the readable XLSX.
No source string is interpreted as a spreadsheet formula or a hyperlink.
"""
from __future__ import annotations

import json
import math
import ntpath
from pathlib import Path
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


METADATA_FIELDS = (
    "document_number", "title", "revision", "revision_date", "issue_status",
    "discipline", "document_type", "system", "building", "floor", "scale", "sheet_number",
)
MARKER = ".mep-registry-output.json"
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)


def _validate_json(value: Any, location: str = "snapshot") -> None:
    """Reject non-JSON objects rather than silently coercing keys or NaN."""
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            # Lone surrogates cannot be written to the UTF-8 companion files.
            value.encode("utf-8")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location} contains a non-string object key")
            _validate_json(key, location)
            _validate_json(item, f"{location}.{key}")
        return
    raise ValueError(f"{location} is not a JSON value")


def _validate_snapshot(snapshot: Any) -> None:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    _validate_json(snapshot)
    for key in ("project", "summary", "scan"):
        if not isinstance(snapshot.get(key), dict):
            raise ValueError(f"snapshot.{key} must be an object")
    for key in ("id", "root"):
        if not isinstance(snapshot["project"].get(key), str) or not snapshot["project"][key]:
            raise ValueError(f"snapshot.project.{key} must be a nonempty string")
    if not isinstance(snapshot.get("generated_at"), str):
        raise ValueError("snapshot.generated_at must be a string")
    for key in ("files", "sheets", "relationships", "issues", "observations", "reviews"):
        if not isinstance(snapshot.get(key), list) or any(not isinstance(item, dict) for item in snapshot[key]):
            raise ValueError(f"snapshot.{key} must be an array of objects")
    if "revisions" in snapshot and (not isinstance(snapshot["revisions"], list)
            or any(not isinstance(item, dict) for item in snapshot["revisions"])):
        raise ValueError("snapshot.revisions must be an array of objects")
    required = {
        "files": ("file_id", "version_id", "analysis_id", "relative_path", "metadata", "provenance"),
        "sheets": ("sheet_id", "file_id", "relative_path", "metadata", "provenance"),
        "relationships": ("relationship_id", "left", "right", "verification_status"),
        "issues": ("issue_id",), "observations": ("observation_id",), "reviews": (),
    }
    for collection, fields in required.items():
        for record in snapshot[collection]:
            for field in fields:
                if field not in record:
                    raise ValueError(f"snapshot.{collection} record lacks {field}")
            for field in ("metadata", "provenance", "source", "left", "right", "evidence"):
                if field in record and not isinstance(record[field], dict):
                    raise ValueError(f"snapshot.{collection}.{field} must be an object")


def _actual_path(project: dict, record: dict) -> str | None:
    for field in ("actual_file_path", "absolute_path", "path"):
        if record.get(field) is not None:
            return record[field]
    relative = record.get("relative_path")
    if relative is None:
        return None
    root = project["root"]
    if ntpath.splitdrive(root)[0] or "\\" in root:
        return ntpath.join(root, relative)
    return str(Path(root) / relative)


def _excel_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = _json(value)
    # Excel rounds long integers; literal text preserves their original digits.
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2 ** 53:
        value = str(value)
    if isinstance(value, str):
        value = _ILLEGAL_XML.sub(lambda match: f"\\u{ord(match.group()):04x}", value)
        if len(value) > 32767:
            note = " [truncated; full value in registry_summary.json]"
            value = value[:32767 - len(note)] + note
    return value


def _write_sheet(workbook: Workbook, title: str, columns: list[str], records: list[dict]) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append(columns)
    for record in records:
        for column, key in enumerate(columns, 1):
            value = _excel_value(record.get(key))
            cell = sheet.cell(sheet.max_row if column > 1 else sheet.max_row + 1, column, value)
            # Explicit string type is essential: openpyxl otherwise promotes =... to formulas.
            if isinstance(value, str):
                cell.data_type = "s"
                cell.number_format = "@"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    sheet.row_dimensions[1].height = 30
    for cell in sheet[1]:
        cell.font = Font(name="Calibri", size=11, color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="24465B")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for index, key in enumerate(columns, 1):
        width = 60 if key.endswith("_json") else 44 if "path" in key or key in ("title", "message", "reason") else 24
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        sheet.row_dimensions[row[0].row].height = 46
        for cell in row:
            cell.font = Font(name="Calibri", size=11, color="20313D")


def _write_workbook(snapshot: dict, path: Path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    file_columns = ["file_id", "version_id", "analysis_id", "actual_file_path", "relative_path", "filename",
        "extension", "classification_category", "size", "sha256", "modified_at", "registration_status", "registry_status", "sheet_count",
        *METADATA_FIELDS, "provenance_json", "record_json"]
    sheet_columns = ["sheet_id", "file_id", "version_id", "analysis_id", "actual_file_path", "relative_path",
        "pdf_page", "registry_status", *METADATA_FIELDS, "provenance_json", "record_json"]
    for name, key, columns in (("Files", "files", file_columns), ("DrawingSheets", "sheets", sheet_columns)):
        records = []
        for record in snapshot[key]:
            records.append({**record, **{field: record["metadata"].get(field) for field in METADATA_FIELDS},
                "actual_file_path": _actual_path(snapshot["project"], record),
                "provenance_json": record["provenance"], "record_json": record})
        _write_sheet(workbook, name, columns, records)
    specs = (
        ("Issues", "issues", ["issue_id", "code", "message", "severity", "status", "file_id", "analysis_id",
            "relative_path", "pdf_page", "source_json", "record_json"]),
        ("Relationships", "relationships", ["relationship_id", "type", "confidence", "verification_status",
            "left_json", "right_json", "evidence_json", "record_json"]),
        ("Observations", "observations", ["observation_id", "file_id", "sheet_id", "field", "value",
            "evidence_class", "confidence", "review_status", "source_json", "record_json"]),
        ("ReviewHistory", "reviews", ["review_id", "target_type", "target_id", "decision", "actor", "reason",
            "created_at", "value_json", "record_json"]),
    )
    for name, key, columns in specs:
        records = []
        for record in snapshot[key]:
            row = {**record, "record_json": record}
            for column in columns:
                if column.endswith("_json") and column != "record_json":
                    original = column.removesuffix("_json")
                    if original in record:
                        row[column] = record[original]
            records.append(row)
        _write_sheet(workbook, name, columns, records)
    workbook.properties.title = "MEP Document Registry"
    workbook.properties.subject = str(snapshot["project"].get("name") or snapshot["project"]["id"])
    workbook.properties.creator = "MEP Document Registry"
    workbook.properties.description = "Stored snapshot export. Full source records and provenance: registry_summary.json."
    try:
        workbook.save(path)
    finally:
        workbook.close()


def _markdown(value: Any) -> str:
    if value is None:
        return ""
    text = _json(value) if isinstance(value, (dict, list)) else str(value)
    # Numeric entities neutralize table separators, code delimiters and inline HTML.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("|", "&#124;").replace("`", "&#96;").replace("\\", "&#92;")
    for character in "[]*_!#":
        text = text.replace(character, f"&#{ord(character)};")
    return text.replace("\r\n", "&#10;").replace("\r", "&#10;").replace("\n", "&#10;")


def _relationships_markdown(snapshot: dict) -> str:
    lines = ["# Document relationships", "", "Project: " + _markdown(snapshot["project"].get("name")
        or snapshot["project"]["id"]), "Generated: " + _markdown(snapshot["generated_at"]), "",
        "Verification status is retained from the stored snapshot. Proposed relationships require review.", "",
        "| Relationship ID | Type | Left source | Right source | Confidence | Verification status | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for relationship in snapshot["relationships"]:
        fields = (relationship.get("relationship_id"), relationship.get("type"), relationship["left"],
            relationship["right"], relationship.get("confidence"), relationship["verification_status"],
            relationship.get("evidence"))
        lines.append("| " + " | ".join(_markdown(field) for field in fields) + " |")
    return "\n".join(lines) + "\n"


def export_snapshot(snapshot: dict, output_dir: str | Path) -> dict[str, str]:
    """Write a new dedicated directory; refuse any existing path.

    ``snapshot`` must be authoritative stored data, not parsed source files.
    Validation and JSON serialization complete before directory creation. On an
    I/O failure the new directory remains marked incomplete and must stay excluded
    from ingestion. Nothing is deleted and a failed export cannot report success.
    """
    _validate_snapshot(snapshot)
    texts = {
        "document_relationships.json": _json(snapshot["relationships"]) + "\n",
        "issues_for_review.json": _json(snapshot["issues"]) + "\n",
        "registry_summary.json": _json(snapshot) + "\n",
        "document_relationships.md": _relationships_markdown(snapshot),
    }
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    marker = {"schema": "mep-registry-output/1", "project_id": snapshot["project"]["id"],
        "generated_at": snapshot["generated_at"], "status": "incomplete"}
    marker_path = output / MARKER
    with marker_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_json(marker) + "\n")
    for name, contents in texts.items():
        with (output / name).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
    _write_workbook(snapshot, output / "document_register.xlsx")
    marker["status"] = "complete"
    temporary_marker = output / (MARKER + ".tmp")
    with temporary_marker.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_json(marker) + "\n")
    temporary_marker.replace(marker_path)
    return {name: str(output / name) for name in (*texts, "document_register.xlsx", MARKER)}
