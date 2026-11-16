"""Engineering workbooks with literal source cells; no evaluated input formulas."""
from pathlib import Path

from .common import dump


def workbook(path, tables, metadata, cfg, literal):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook()
    book.remove(book.active)
    book.properties.title = metadata["title"]
    colors = {"READY_FOR_EXPORT": "E2F0D9", "BLOCKED_BY_CONFLICTS": "FCE4D6", "PENDING_ENGINEERING_REVIEW": "FFF2CC", "DRAFT_INCOMPLETE": "FFF2CC", "SUPERSEDED": "D9D9D9"}
    for base_name, rows, defaults in tables:
        chunks = [rows[i:i + cfg["max_excel_rows"] - 6] for i in range(0, len(rows), max(1, cfg["max_excel_rows"] - 6))] or [[]]
        for chunk_index, chunk in enumerate(chunks, 1):
            name = base_name[:25] + ("_" + str(chunk_index) if len(chunks) > 1 else "")
            sheet = book.create_sheet(name[:31])
            headers = list(dict.fromkeys(defaults + [k for row in chunk for k in row]))
            sheet.cell(1, 1, metadata["title"]).font = Font(size=15, bold=True, color=cfg["accent_color"])
            for row_number, field in enumerate(("project", "package_id", "version", "status"), 2):
                sheet.cell(row_number, 1, field.replace("_", " ").title())
                cell = sheet.cell(row_number, 2, literal(metadata.get(field)))
                if isinstance(cell.value, str):
                    cell.data_type = "s"
            start = 7
            for column, header in enumerate(headers, 1):
                cell = sheet.cell(start, column, header)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor=cfg["accent_color"])
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                sheet.column_dimensions[get_column_letter(column)].width = 65 if any(w in header.lower() for w in ("text", "requirement", "source", "parameter")) else min(45, max(16, len(header) + 3))
            for row_number, row in enumerate(chunk, start + 1):
                for column, header in enumerate(headers, 1):
                    value = literal(row.get(header))
                    cell = sheet.cell(row_number, column, value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    if header == "Relative File Link" and cfg["source_links"] and isinstance(value, str) and value.startswith("./"):
                        cell.hyperlink = value
                        cell.font = Font(color="0563C1", underline="single")
                    if header.lower().endswith("status") and str(value) in colors:
                        cell.fill = PatternFill("solid", fgColor=colors[str(value)])
            sheet.freeze_panes = "A8"
            sheet.auto_filter.ref = f"A7:{get_column_letter(len(headers))}{max(7, len(chunk) + 7)}"
            sheet.print_title_rows = "1:7"
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
            sheet.page_setup.orientation = "landscape"
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
            sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
            sheet.oddFooter.center.text = "Page &P of &N"
            sheet.oddHeader.right.text = str(metadata["status"])
    with Path(path).open("xb") as stream:
        book.save(stream)


def register_rows(groups, cfg):
    result = []
    for index, group in enumerate(groups, 1):
        row = {"Item": index, "Category": group["category"], "Verified Type ID": group["verified_type_id"],
               "Equipment IDs": [t["id"] for t in group["targets"]], "Original Tags": sorted({v for t in group["targets"] for v in t["tags"]}),
               "Normalized Tags": sorted({v for t in group["targets"] for v in t["normalized_tags"]}),
               "Description": sorted({o["description"] for t in group["targets"] for o in t["occurrences"] if o.get("description")}),
               "System": group["system"], "Building": group["building"], "Floor": sorted({v for t in group["targets"] for v in t["floors"]}),
               "Room / Location": sorted({o["room"] for t in group["targets"] for o in t["occurrences"] if o.get("room")}),
               "Verified Instance Quantity": group["quantity"]["verified_instance_quantity"],
               "Schedule Quantities": group["quantity"]["schedule_quantities"], "BOQ Quantities": group["quantity"]["boq_quantities"],
               "Final Reviewed Quantity": group["quantity"]["final_quantity"], "Quantity Reconciliation Status": group["quantity"]["quantity_reconciliation_status"],
               "Technical Review Status": group["readiness"]["status"], "Outstanding Reasons": group["readiness"]["reasons"]}
        actual = {name for values in group["parameters"].values() for name in values}
        fields = cfg["category_columns"].get(group["category"], [n for n in cfg["parameter_order"] if n in actual] + sorted(actual - set(cfg["parameter_order"])))
        for name in fields:
            row[name] = [{"equipment_id": equipment_id, "observations": values.get(name, [])} for equipment_id, values in group["parameters"].items()]
        for role, title in (("drawing", "Drawing References"), ("schedule", "Schedule References"), ("boq", "BOQ References")):
            row[title] = [o["source"] for t in group["targets"] for o in t["occurrences"] if o["role"] == role]
        result.append(row)
    return result
