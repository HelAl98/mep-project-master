"""Database-snapshot exports, literal spreadsheet cells and lossless JSON companions."""
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
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", lambda m: "\\u%04x" % ord(m.group()), str(value))
    return text if len(text) <= 32767 else text[:32600] + " [TRUNCATED FOR EXCEL; full value in equipment_summary.json]"


def master_rows(snapshot):
    occurrences = {o["id"]: o for o in snapshot["occurrences"]}
    rows, mapping = [], []
    for cluster in snapshot["instance_clusters"]:
        sources = [occurrences[i] for i in cluster["occurrence_ids"]]
        def distinct(field):
            values = {dump(o.get(field)) for o in sources if o.get(field) is not None}
            return [json.loads(v) for v in sorted(values)] or None
        types = [e["id"] for e in snapshot["entities"] if e["kind"] == "type" and e["status"] == "confirmed" and set(cluster["occurrence_ids"]).intersection(e["occurrence_ids"])]
        rows.append({"equipment_id": cluster["cluster_id"], "original_tags": distinct("tag"),
            "normalized_tags": distinct("normalized_tag"), "category": distinct("category"), "discipline": distinct("discipline"),
            "system": distinct("system"), "building": distinct("building"), "floor": distinct("floor"), "room": distinct("room"),
            "confirmed_type_ids": types or None, "technical_parameter_observations": [{"occurrence_id": o["id"], "parameters": o["parameters"]} for o in sources],
            "quantity_context": [{"occurrence_id": o["id"], "role": o["role"], "quantity": o.get("quantity"), "unit": o.get("quantity_unit"), "scope": o.get("scope")} for o in sources],
            "source_references": [o["source"] for o in sources], "verification_status": cluster["status"],
            "physical_quantity": 1 if cluster["status"] == "verified_instance" else None})
        for occurrence in sources:
            links = [m for m in snapshot["matches"] if occurrence["id"] in (m["left_id"], m["right_id"])]
            mapping.append({"equipment_id": cluster["cluster_id"], "occurrence_id": occurrence["id"], "role": occurrence["role"],
                "source": occurrence["source"], "match_ids_and_statuses": [{"id": m["id"], "status": m["status"]} for m in links]})
    mapped = {r["occurrence_id"] for r in mapping}
    for occurrence in occurrences.values():
        if occurrence["id"] not in mapped:
            mapping.append({"equipment_id": None, "occurrence_id": occurrence["id"], "role": occurrence["role"], "source": occurrence["source"],
                "match_ids_and_statuses": [{"id": m["id"], "status": m["status"]} for m in snapshot["matches"] if occurrence["id"] in (m["left_id"], m["right_id"])]})
    return rows, mapping


def export(snapshot, output):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.utils import get_column_letter
    directory = Path(output).expanduser().resolve()
    if directory.exists():
        raise ValueError("Export requires a new directory; existing output is never overwritten")
    directory.mkdir(parents=True, exist_ok=False)
    # Registry-compatible marker also protects incomplete outputs from later ingestion.
    write_json(directory / ".mep-registry-output.json", {"producer": "mep-equipment-matcher", "started_at": now(), "completion_marker": "equipment-export-complete.json"})
    master, mapping = master_rows(snapshot)
    review = {"matching_status": snapshot["matching_status"], "matches": snapshot["matches"], "relationships": snapshot["relationships"],
              "unmatched_occurrence_ids": snapshot["unmatched"], "issues": snapshot["issues"], "reviews": snapshot["reviews"]}
    write_json(directory / "equipment_summary.json", {**snapshot, "equipment_master_register": master, "equipment_source_mapping": mapping})
    write_json(directory / "equipment_matching_review.json", review)
    book = Workbook(write_only=True)
    tables = [("EquipmentMaster", master, ["equipment_id", "original_tags", "normalized_tags", "category", "system", "verification_status"]),
              ("SourceMapping", mapping, ["equipment_id", "occurrence_id", "role", "source", "match_ids_and_statuses"]),
              ("Occurrences", snapshot["occurrences"], ["id", "tag", "normalized_tag", "role", "source"]),
              ("Matches", snapshot["matches"], ["id", "left_id", "right_id", "kind", "status", "evidence"]),
              ("ReviewIssues", snapshot["issues"], ["id", "code", "kind", "status", "evidence"]),
              ("Associations", snapshot["relationships"], ["id", "kind", "status", "evidence"]),
              ("TypesAndGroups", snapshot["entities"], ["id", "kind", "status", "basis", "occurrence_ids"]),
              ("Quantities", snapshot["quantities"], ["category", "scope", "source_quantities", "verified_unique_instances"]),
              ("ReviewHistory", snapshot["reviews"], ["id", "target_kind", "target_id", "decision", "actor", "reason"])]
    for name, rows, defaults in tables:
        headers = list(dict.fromkeys(defaults + [k for row in rows for k in row if k != "sequence"]))
        sheet = book.create_sheet(name)
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, 1):
            sheet.column_dimensions[get_column_letter(index)].width = min(60, max(18, len(header) + 3))
        header_cells = []
        for header in headers:
            cell = WriteOnlyCell(sheet, value=header)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            header_cells.append(cell)
        sheet.append(header_cells)
        for row in rows:
            cells = []
            for header in headers:
                value = literal(row.get(header))
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"  # A leading '=' is evidence text, never a formula.
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cells.append(cell)
            sheet.append(cells)
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    path = directory / "equipment_master_register.xlsx"
    with path.open("xb") as stream:
        book.save(stream)
    write_json(directory / "equipment-export-complete.json", {"completed_at": now(), "summary": snapshot["summary"], "status": "complete"})
    return {"output": str(directory), "files": [str(p) for p in directory.iterdir() if not p.name.startswith(".")], "summary": snapshot["summary"]}
