"""Stored-record matrices and strictly filtered approved downstream requirements."""
import json
from pathlib import Path
import re

from .common import dump, now


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def literal(value):
    if isinstance(value, (dict, list, tuple)):
        value = dump(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", lambda m: "\\u%04x" % ord(m.group()), str(value))
    return text if len(text) <= 32767 else text[:32600] + " [Excel display truncated; complete original in technical_records.json]"


def matrix(record):
    targets = {t["id"]: t for t in record["targets"]}
    requirements = {r["id"]: r for r in record["requirements"]}
    result = []
    for link in record["applicability"]:
        req, target = requirements[link["requirement_id"]], targets[link["entity_id"]]
        result.append({"equipment_id": target["id"], "equipment_tags": target["tags"], "equipment_category": target["categories"],
            "equipment_kind": target["kind"], "equipment_type": target["equipment_types"], "system": target["systems"],
            "requirement_id": req["id"], "technical_classification": req["classification"], "original_requirement_text": req["original_text"],
            "normalized_interpretations": req["interpretations"], "applicability": link["status"], "applicability_id": link["id"],
            "applicability_evidence": link["evidence"], "discipline": req["context"].get("discipline"),
            "source_document": req["source"], "section": req["context"].get("section"), "section_title": req["context"].get("section_title"),
            "part": req["context"].get("part"), "article": req["context"].get("article"), "clause": req["context"].get("clause"),
            "document_revision_status": req["revision_status"], "verification_status": req["verification_status"], "reference_status": req["reference_status"]})
    return result


def approved(record, require_complete=False):
    targets = {t["id"]: t for t in record["targets"]}
    completeness = {c["entity_id"]: c["all_applicable_requirements_verified_and_approved"] for c in record["completeness"]}
    if require_complete and (not targets or not all(completeness.get(t, False) for t in targets)):
        raise ValueError("Equipment review coverage is incomplete; no complete approved package can be claimed")
    result, withheld = [], []
    for row in matrix(record):
        reasons = []
        if record["comparison_status"] != "current":
            reasons.append("technical_comparison_not_current")
        if any(c["entity_id"] == row["equipment_id"] for c in record["approved_interpretation_conflicts"]):
            reasons.append("contradictory_current_approved_values_require_review")
        if targets[row["equipment_id"]]["identity_status"] != "confirmed":
            reasons.append("equipment_identity_unconfirmed")
        if row["applicability"] != "confirmed_applicability":
            reasons.append("applicability_unconfirmed_or_excluded")
        if row["verification_status"] != "approve_requirement":
            reasons.append("original_requirement_not_reviewed_and_approved")
        if row["document_revision_status"] != "applicable":
            reasons.append("document_revision_not_selected_applicable")
        if row["reference_status"] != "source_reference_available":
            reasons.append("source_reference_incomplete")
        if any(i.get("verification_status") not in ("approve_interpretation", "reject_interpretation") for i in row["normalized_interpretations"]):
            reasons.append("interpretation_unreviewed")
        if reasons:
            withheld.append({"equipment_id": row["equipment_id"], "requirement_id": row["requirement_id"], "reasons": reasons})
        else:
            row["normalized_interpretations"] = [i for i in row["normalized_interpretations"] if i["verification_status"] == "approve_interpretation"]
            row["complete_equipment_review"] = completeness.get(row["equipment_id"], False)
            result.append(row)
    return {"schema_version": "mep-approved-requirements/1", "project": record["project"], "foundation_hash": record["foundation_hash"],
        "generated_at": now(), "requirements": result, "withheld": withheld, "approved_values": [v for v in record["approved_values"] if v["is_current"]],
        "completeness": record["completeness"], "decisions": record["decisions"], "decision_sources": record["decision_sources"],
        "scope": "Approved current evidence only; partial exports do not certify full specification coverage. No RFQ documents or equipment folders are generated."}


def export(record, output, approved_only=False, require_complete=False):
    directory = Path(output).expanduser().resolve()
    if directory.exists():
        raise ValueError("Output must be a new directory; existing reports are never overwritten")
    payload = approved(record, require_complete) if approved_only else record
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / ".mep-registry-output.json", {"producer": "mep-cross-document-reviewer", "started_at": now(), "completion_marker": "technical-export-complete.json"})
    if approved_only:
        write_json(directory / "approved_requirements.json", payload)
    else:
        write_json(directory / "technical_records.json", record)
        write_json(directory / "engineering_conflict_register.json", {"comparison_status": record["comparison_status"], "cases": record["cases"], "decisions": record["decisions"], "supporting_references": record["decision_sources"]})
        write_json(directory / "technical_review_coverage.json", {"coverage": record["coverage"], "completeness": record["completeness"], "summary": record["summary"]})
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        book = Workbook(write_only=True)
        book.properties.title = str(record["report_settings"].get("title", "MEP Technical Document Review"))
        tables = [("RequirementsMatrix", matrix(record), ["equipment_id", "requirement_id", "original_requirement_text", "applicability", "source_document"]),
                  ("Comparisons", record["comparisons"], ["entity_id", "parameter", "outcome", "evidence"]),
                  ("ConflictRegister", record["cases"], ["id", "entity_id", "type", "status", "evidence", "review_id"]),
                  ("ReviewCoverage", record["coverage"], ["entity_id", "category", "status", "available", "successfully_processed", "matched", "reviewed", "approved"]),
                  ("ApprovedValues", record["approved_values"], ["id", "entity_id", "status", "payload", "review_id"]),
                  ("ReviewHistory", record["decisions"], ["id", "target_kind", "target_id", "decision", "actor", "reason", "created_at"]),
                  ("DecisionSources", record["decision_sources"], ["review_id", "references_json", "previous_status_json"])]
        for name, rows, first in tables:
            headers = list(dict.fromkeys(first + [k for r in rows for k in r if k != "sequence"]))
            sheet = book.create_sheet(name)
            sheet.freeze_panes = "A2"
            for index, header in enumerate(headers, 1):
                sheet.column_dimensions[get_column_letter(index)].width = min(65, max(20, len(header) + 3))
            def cells(values, header=False):
                result = []
                for value in values:
                    value = literal(value)
                    cell = WriteOnlyCell(sheet, value=value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
                    if header:
                        cell.font = Font(bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor="17365D")
                    result.append(cell)
                return result
            sheet.append(cells(headers, True))
            for row in rows:
                sheet.append(cells([row.get(h) for h in headers]))
            sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
        with (directory / "technical_review_matrices.xlsx").open("xb") as stream:
            book.save(stream)
    write_json(directory / "technical-export-complete.json", {"completed_at": now(), "approved_only": approved_only, "source_comparison_status": record["comparison_status"]})
    return {"output": str(directory), "files": [str(p) for p in directory.iterdir() if not p.name.startswith(".")], "source_comparison_status": record["comparison_status"]}
