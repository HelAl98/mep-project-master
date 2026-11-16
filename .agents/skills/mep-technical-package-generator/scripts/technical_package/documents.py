"""Professional Word utilities; exact original clauses, blank supplier responses."""
from pathlib import Path
import re

from .common import dump


DRAFT = "INTERNAL DRAFT \u2014 NOT APPROVED FOR ISSUE"


def text(value):
    if value is None:
        return "Not established in reviewed database"
    value = dump(value) if isinstance(value, (dict, list, tuple)) else str(value)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        raise ValueError("Source contains XML-forbidden control characters; original remains in JSON. Resolve representation before Word export.")
    return value


def document(metadata, cfg, rfq=False):
    from docx import Document
    from docx.shared import Inches, Mm, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = cfg["font"], Pt(cfg["font_size"])
    normal.paragraph_format.space_after = Pt(6)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        doc.styles[name].font.name = cfg["font"]
        doc.styles[name].font.color.rgb = RGBColor.from_string(cfg["accent_color"])
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.7)
        section.left_margin = section.right_margin = Inches(.7)
        section.page_width, section.page_height = (Mm(210), Mm(297)) if cfg["page_size"] == "A4" else (Inches(8.5), Inches(11))
        section.header.paragraphs[0].text = text(metadata["project"]) + " | " + metadata["category"]
        footer = section.footer.paragraphs[0]
        footer.add_run("RFQ DRAFT | " if rfq else "")
        footer.add_run(metadata["status"] + " | Page ")
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)
    doc.add_heading(metadata["title"], 0)
    if rfq or metadata["status"] != "READY_FOR_EXPORT":
        paragraph = doc.add_paragraph()
        paragraph.add_run(DRAFT).bold = True
    doc.add_paragraph("Project: " + text(metadata["project"]))
    doc.add_paragraph("Package: " + metadata["package_id"] + " | Version: " + metadata["version"])
    doc.add_paragraph("Technical readiness: " + metadata["status"])
    if cfg["rtl"]:
        for paragraph in doc.paragraphs:
            prop = paragraph._p.get_or_add_pPr()
            prop.append(OxmlElement("w:bidi"))
    return doc


def table(doc, headers, rows):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.autofit = False
    available = doc.sections[-1].page_width - doc.sections[-1].left_margin - doc.sections[-1].right_margin
    weights = [3 if "Requirement" in h and "ID" not in h or "Evidence" in h else 2 if "Reference" in h or "Parameters" in h else 1 for h in headers]
    for column, weight in zip(t.columns, weights):
        column.width = int(available * weight / sum(weights))
    for index, header in enumerate(headers):
        t.rows[0].cells[index].text = header
        for run in t.rows[0].cells[index].paragraphs[0].runs:
            run.bold = True
    props = t.rows[0]._tr.get_or_add_trPr()
    repeated = OxmlElement("w:tblHeader")
    props.append(repeated)
    for row in rows:
        cells = t.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = "" if value == "" else text(value)
    return t


def requirement(doc, row, number):
    doc.add_heading(f"{number}. Requirement {row['requirement_id']}", 2)
    doc.add_paragraph("Scope: " + text(row["equipment_ids"]) + " | Applicability: " + row["applicability"] + " | Review: " + row["verification_status"])
    # Original binding wording is never replaced with a generated summary.
    doc.add_paragraph(text(row["original_requirement_text"]))
    source = row["source_document"]
    doc.add_paragraph("Source: " + text({"document": source.get("filename", source.get("relative_path")), "path": source.get("relative_path"),
        "revision": source.get("document_revision"), "physical_pdf_pages": source.get("pdf_pages", source.get("pdf_page")),
        "printed_page": source.get("printed_page"), "section": row.get("section"), "part": row.get("part"), "article": row.get("article"),
        "clause": row.get("clause"), "paragraph": source.get("paragraph"), "line_start": source.get("line_start"),
        "fragments": [{k: v for k, v in fragment.items() if k != "raw_text"} for fragment in source.get("fragments", [])]}))


def specifications(path, metadata, groups, requirements, cfg):
    doc = document(metadata, cfg)
    doc.add_heading("Equipment Scope", 1)
    table(doc, ["Group / Type", "Equipment", "System / Location", "Quantity / Status"],
          [[g["verified_type_id"] or "Unverified type \u2014 separate review group", [t["tags"] for t in g["targets"]],
            [g["system"], g["building"]], [g["quantity"]["final_quantity"], g["readiness"]["status"]]] for g in groups])
    excluded = [r for r in requirements if r["applicability"] == "not_applicable"]
    requirements = [r for r in requirements if r["applicability"] != "not_applicable"]
    assigned = set()
    for heading in cfg["specification_sections"]:
        rows = [r for r in requirements if r["document_section"] == heading]
        if not rows:
            continue
        doc.add_heading(heading, 1)
        for row in rows:
            requirement(doc, row, len(assigned) + 1)
            assigned.add(row["requirement_id"])
    remainder = [r for r in requirements if r["requirement_id"] not in assigned]
    if remainder:
        doc.add_heading("Other Documented Applicable Requirements", 1)
        for row in remainder:
            requirement(doc, row, len(assigned) + 1)
            assigned.add(row["requirement_id"])
    if not requirements:
        doc.add_paragraph("No approved applicable requirement text is available in the selected database scope.")
    if excluded:
        doc.add_heading("Recorded Exclusions \u2014 Outside the Confirmed Supply Scope", 1)
        for index, row in enumerate(excluded, 1):
            requirement(doc, row, index)
    with Path(path).open("xb") as stream:
        doc.save(stream)


def rfq(path, metadata, groups, requirements, cfg, template):
    doc = document({**metadata, "title": template["title"]}, cfg, rfq=True)
    table(doc, ["Field", "Value"], [["Project", metadata["project"]], ["RFQ Reference", "[TO BE ASSIGNED]"],
          ["Equipment Category", metadata["category"]], ["Document Version", metadata["version"]], ["Issue Date", "[TO BE ASSIGNED]"]])
    doc.add_heading("Equipment Schedule", 1)
    table(doc, ["Type / Equipment", "Reviewed Quantity", "Technical Parameters / Units", "Status"],
          [[[g["verified_type_id"], [t["tags"] for t in g["targets"]]], g["quantity"]["final_quantity"],
            {eid: {name: [p for p in values if p["approved"]] for name, values in parameters.items()} for eid, parameters in g["parameters"].items()}, g["readiness"]["status"]] for g in groups])
    requirements = [r for r in requirements if r["applicability"] != "not_applicable"]
    for group in groups:
        doc.add_heading("Technical Parameters: " + group["group_id"], 2)
        table(doc, ["Equipment / Parameter", "Approved Value / Unit", "Original Evidence"],
              [[equipment + " / " + name, [{"value": p["normalized_value"] if p["normalized_value"] is not None else p["original_value"], "unit": p["normalized_unit"] or p["original_unit"]} for p in values if p["approved"]], values]
               for equipment, parameters in group["parameters"].items() for name, values in parameters.items()])
    doc.add_heading("Technical Requirements and Scope of Supply", 1)
    for index, row in enumerate(requirements, 1):
        requirement(doc, row, index)
    doc.add_heading("Technical Submission Requirements", 1)
    for row in requirements:
        if any(c["category"] == "Documentation" for c in row["technical_classification"]):
            doc.add_paragraph(row["original_requirement_text"])
            doc.add_paragraph("Reference: " + row["requirement_id"])
    doc.add_heading("Commercial Quotation Response \u2014 Blank Supplier Fields", 1)
    table(doc, ["Requested Field", "Supplier Response"], [[field, ""] for field in template["commercial_fields"]])
    doc.add_heading("Technical Deviations and Clarifications", 1)
    table(doc, ["Requirement / Item", "Deviation", "Clarification", "Supporting Reference"], [["", "", "", ""]])
    from docx.enum.section import WD_SECTION, WD_ORIENT
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    doc.add_heading("Technical Compliance Matrix", 1)
    table(doc, ["Requirement ID", "Equipment Scope", "Exact Requirement", "Source Reference", "Compliance Response", "Offered Specification", "Deviation", "Datasheet Ref"],
          [[r["requirement_id"], r["equipment_ids"], r["original_requirement_text"], r["source_document"], "", "", "", ""] for r in requirements])
    doc.add_paragraph(template["draft_notice"])
    with Path(path).open("xb") as stream:
        doc.save(stream)
