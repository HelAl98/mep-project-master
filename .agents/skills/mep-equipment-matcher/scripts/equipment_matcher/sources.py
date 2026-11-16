"""Explicit source adapters; no native DWG conversion or source mutation."""
from contextlib import contextmanager
import copy
import csv
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from .common import dump, helper, key, read_json, sha, tag


PRICE = re.compile(r"^(?:(?:unit|total|extended|net|gross)[ _-]+)?(?:price|rate|amount|cost|currency)(?:$|[ _(\[])", re.IGNORECASE)


def safe_cells(raw):
    return {k: v for k, v in raw.items() if not PRICE.search(str(k))}


def check_size(path, cfg):
    if path.stat().st_size > cfg["max_json_bytes"]:
        raise ValueError("Input exceeds configured byte limit; partition explicitly")
    if path.suffix.lower() == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > cfg["max_zip_uncompressed_bytes"]:
                raise ValueError("Office archive exceeds configured uncompressed size limit")


@contextmanager
def source_copy(db, file):
    """Helpers requiring a suffix receive an isolated copy of verified archived bytes."""
    archived = db.archived_path(file)
    with tempfile.TemporaryDirectory(prefix="mep-equipment-") as temporary:
        path = Path(temporary) / ("source." + file["extension"])
        shutil.copyfile(archived, path)
        yield path
        if sha(path) != file["sha256"]:
            raise ValueError("Working source copy changed during extraction")


def validate_mapping(mapping):
    if not isinstance(mapping, dict) or not isinstance(mapping.get("columns"), dict) or not mapping["columns"]:
        raise ValueError("Explicit nonempty columns mapping is required")
    header = mapping.get("header_row", 1)
    if isinstance(header, bool) or not isinstance(header, int) or header < 1:
        raise ValueError("header_row must be an actual one-based row")
    permitted = {"tag", "description", "category", "discipline", "system", "building", "floor", "room", "room_name", "quantity", "quantity_unit", "item_number", "section", "drawing_number", "revision", "schedule_reference", "equipment_type", "identity_kind", "relation_type", "related_tag", "controller_tag", "control_panel_tag", "spec_section", "scope"}
    if set(mapping["columns"]) - permitted:
        raise ValueError("Unsupported column fields; price fields are not supported")
    used = list(mapping["columns"].values())
    for parameter in mapping.get("parameters", []):
        if not parameter.get("name") or not parameter.get("value_column"):
            raise ValueError("Parameter mapping requires name and value_column")
        used += [parameter["value_column"]]
        if parameter.get("unit_column"):
            used += [parameter["unit_column"]]
        if parameter.get("fixed_unit") and not parameter.get("unit_basis"):
            raise ValueError("A fixed parameter unit requires an explicit unit_basis")
    if any(PRICE.search(str(column)) for column in used):
        raise ValueError("Pricing columns are outside this skill")
    return header, used


def mapped_row(raw, source, mapping):
    data = {field: raw.get(column) for field, column in mapping["columns"].items()}
    constants = mapping.get("constants", {})
    if not isinstance(constants, dict):
        raise ValueError("mapping.constants must be an object")
    if any(k not in {"discipline", "system", "building", "floor", "scope", "category", "identity_kind", "schedule_reference"} for k in constants):
        raise ValueError("Unsupported mapped constant")
    for field, value in constants.items():
        if data.get(field) not in (None, "", value):
            raise ValueError(f"Mapped constant conflicts with row value: {field}")
        data[field] = value
    data["parameters"] = []
    for item in mapping.get("parameters", []):
        data["parameters"].append({"name": item["name"], "value": raw.get(item["value_column"]),
            "unit": raw.get(item["unit_column"]) if item.get("unit_column") else item.get("fixed_unit"),
            "original_column": item["value_column"], "unit_column": item.get("unit_column"), "unit_basis": item.get("unit_basis")})
    data["context_provenance"] = {field: {"method": "explicit_mapping_constant", "value": value} for field, value in constants.items()}
    formula_fields = [k for k, v in data.items() if isinstance(v, str) and v.startswith("=")]
    for field in formula_fields:
        data[field] = None
    source.update(columns=mapping["columns"], parameter_columns=mapping.get("parameters", []))
    return {"kind": "equipment", "raw_text": dump(safe_cells(raw)), "raw_cells": safe_cells(raw), "source": source,
            "data": data, "review": {"status": "unreviewed", "issues": ["FORMULA_NOT_EVALUATED:" + f for f in formula_fields]}}


def table_rows(rows, mapping, cfg, source_base):
    header_row, required = validate_mapping(mapping)
    result, headers = [], None
    for row_number, cells in enumerate(rows, 1):
        if row_number < header_row:
            continue
        if headers is None:
            headers = [str(value).strip() if value is not None else "" for value in cells]
            nonempty = [h for h in headers if h]
            if len(nonempty) != len(set(nonempty)) or any(headers.count(h) != 1 for h in required):
                raise ValueError("Ambiguous or missing mapped headers")
            continue
        if not any(v not in (None, "") for v in cells):
            continue
        if len(result) >= cfg["max_records"]:
            raise ValueError("Row limit reached; import refused rather than silently truncated")
        raw = {name: value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
               for name, value in zip(headers, cells) if name}
        result.append(mapped_row(raw, {**source_base, "row": row_number}, mapping))
    if headers is None:
        raise ValueError("Mapped header row absent")
    return result


def import_schedule(db, file_id, mapping, role, cfg, slot=None, cad=False):
    file = db.file(file_id)
    slot = slot or role + ":" + str(mapping.get("sheet", mapping.get("table_id", "CSV")))
    manifest = {"adapter": "cad-export" if cad else "mapped-schedule", "mapping": mapping}
    cached = db.cached_import(file, slot, role, manifest, cfg)
    if cached:
        return cached
    with source_copy(db, file) as path:
        check_size(path, cfg)
        if cad:
            if file["extension"] != "xlsx":
                raise ValueError("CAD export adapter requires actual mapped XLSX")
            # Preflight bounded rows/ZIP before invoking the existing exporter adapter.
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            try:
                sheet = book[mapping["sheet"]]
                for count, unused in enumerate(sheet.iter_rows(), 1):
                    if count > cfg["max_records"] + mapping.get("header_row", 1):
                        raise ValueError("CAD export row limit exceeded")
            finally:
                book.close()
            package = helper(str(db.skills), "dwg-to-excel", "extract_dwg.py").ingest_export(path, mapping)
            records = [r for r in package["records"] if r["kind"] == "equipment"]
            for record in records:
                raw = json.loads(record["raw_text"])
                for field in ("description", "category", "building", "floor", "room", "system", "scope"):
                    column = mapping["columns"].get(field)
                    if column:
                        value = raw.get(column)
                        record["data"][field] = None if isinstance(value, str) and value.startswith("=") else value
                record["raw_text"] = dump(safe_cells(raw))
            issues = list(package["issues"])
            issues.append({"code": "CAD_EXPORT_NOT_NATIVE_DWG", "message": "The XLSX is the actual source; no DWG metadata transfer or conversion is asserted."})
        elif file["extension"] in ("xlsx", "csv"):
            validate_mapping(mapping)
            if file["extension"] == "xlsx":
                from openpyxl import load_workbook
                book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
                try:
                    if mapping.get("sheet") not in book.sheetnames:
                        raise ValueError("An explicit existing worksheet is required")
                    records = table_rows(book[mapping["sheet"]].iter_rows(values_only=True), mapping, cfg,
                                         {"sheet": mapping["sheet"], "method": "openpyxl-explicit-equipment-map/1"})
                finally:
                    book.close()
            else:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    records = table_rows(csv.reader(stream), mapping, cfg, {"sheet": "CSV", "method": "csv-explicit-equipment-map/1"})
            issues = []
        elif file["extension"] == "pdf":
            if path.stat().st_size > cfg["max_pdf_bytes"]:
                raise ValueError("PDF byte limit exceeded; supply bounded stored extraction")
            package = helper(str(db.skills), "pdf-to-structured", "extract_pdf.py").extract_pdf(path)
            records = pdf_tables(package, mapping, cfg)
            issues = package["issues"]
        else:
            raise ValueError("Schedule intake supports registered XLSX/CSV/PDF; use import-json or import-sql for structured evidence")
    return db.import_records(file, slot, role, manifest, records, issues, cfg)


def pdf_tables(package, mapping, cfg):
    validate_mapping(mapping)
    table_id, page = mapping.get("table_id"), mapping.get("pdf_page")
    if not table_id or isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("PDF mapping requires actual pdf_page and table_id")
    rows = [r for r in package["records"] if r["kind"] == "table_row" and r["source"].get("table_id") == table_id and r["source"].get("pdf_page") == page]
    rows.sort(key=lambda r: r["source"]["row"])
    header_number = mapping.get("header_row", 1)
    header = next((r for r in rows if r["source"]["row"] == header_number), None)
    if header is None:
        raise ValueError("Specified PDF table/header is absent")
    headers = [str(v).strip() if v is not None else "" for v in header["data"]["cells"]]
    required = validate_mapping(mapping)[1]
    if any(headers.count(h) != 1 for h in required) or len(set(h for h in headers if h)) != len([h for h in headers if h]):
        raise ValueError("Ambiguous or missing mapped PDF headers")
    result = []
    for row in rows:
        if row["source"]["row"] <= header_number:
            continue
        if len(result) >= cfg["max_records"]:
            raise ValueError("PDF table row limit exceeded")
        record = mapped_row(dict(zip(headers, row["data"]["cells"])), dict(row["source"]), mapping)
        record["source"]["method"] = "existing-pdf-table-explicit-equipment-map/1"
        result.append(record)
    return result


def drawing_records(db, package, cfg):
    derived = helper(str(db.skills), "drawing-analyzer", "analyze_drawing.py").analyze_drawing(package)
    records = [r for r in derived["records"] if r["kind"] == "equipment"]
    seen = {(r["source"]["pdf_page"], tag(r["data"].get("tag"), cfg)) for r in records}
    # Extend the existing helper's naming subset; added line candidates never inherit nearby rooms.
    for index, record in enumerate(package["records"]):
        if record["kind"] != "line":
            continue
        text = record["raw_text"][:cfg["max_regex_text"]]
        for pattern in cfg["tag_patterns"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                identity = (record["source"]["pdf_page"], tag(match.group(0), cfg))
                if identity in seen:
                    continue
                seen.add(identity)
                records.append({"kind": "equipment", "raw_text": record["raw_text"],
                    "source": {**record["source"], "method": "configured-line-tag-candidate/1", "input_record_index": index,
                               "bbox_scope": "whole source line, not equipment position"},
                    "data": {"tag": match.group(0), "match_span": list(match.span()), "occurrence_only": True,
                             "quantity": None, "floor": None, "room": None}, "review": {"status": "unreviewed", "issues": []}})
    issues = list(derived["issues"])
    for record in records:
        index = record["source"].get("input_record_index")
        if isinstance(index, int) and 0 <= index < len(package["records"]):
            original_id = package["records"][index].get("core_record_id")
            if original_id:
                record["core_record_id"] = original_id
                record["source"]["upstream_core_record_id"] = original_id
    if any(len(r.get("raw_text", "")) > cfg["max_regex_text"] for r in package["records"] if r["kind"] == "line"):
        issues.append({"code": "LINE_TAG_SEARCH_LIMIT", "message": "Some line tails were not searched; extraction is partial."})
    return records, issues


def sql_package(db, file, run_id=None):
    original = (Path(db.documents()["project"]["root"]) / file["relative_path"]).resolve()
    versions = [dict(r) for r in db.conn.execute("SELECT * FROM versions WHERE sha256=?", (file["sha256"],))
                if Path(r["source_path"]).resolve() == original or r["id"] == file["version_id"]]
    ids = {v["id"] for v in versions}
    runs = [dict(r) for r in db.conn.execute("SELECT * FROM runs") if r["version_id"] in ids]
    if run_id:
        runs = [r for r in runs if r["id"] == run_id]
    if len(runs) != 1:
        raise ValueError("Select exactly one existing extraction run with --run-id; unrelated/historical outputs are not combined")
    run = runs[0]
    records = []
    for row in db.conn.execute("SELECT r.* FROM records r JOIN run_records x ON x.record_id=r.id WHERE x.run_id=? ORDER BY r.id", (run["id"],)):
        record = json.loads(row["payload_json"])
        record["core_record_id"] = row["id"]
        records.append(record)
    issues = json.loads(run["issues_json"])
    if isinstance(issues, dict):
        issues = issues.get("extraction_issues", []) + issues.get("ingestion_issues", [])
    return {"schema_version": "mep-evidence/1", "document": json.loads(run["document_json"]), "records": records, "issues": issues}, run["id"]


def import_package(db, file_id, package, cfg, role, slot="structured", manifest=None):
    file = db.file(file_id)
    if package.get("document", {}).get("sha256") != file["sha256"]:
        raise ValueError("Structured evidence must reference the exact registered source SHA-256")
    db.archived_path(file)
    if package.get("schema_version") not in ("mep-evidence/1", "mep-equipment-observations/1"):
        raise ValueError("Unsupported evidence schema")
    manifest = manifest or {"adapter": "structured-package", "package_hash": key(package)}
    cached = db.cached_import(file, slot, role, manifest, cfg)
    if cached:
        return cached
    records = []
    for record in package.get("records", []):
        if record.get("kind") == "equipment" or (role == "specification" and record.get("kind") in ("specification", "paragraph", "specification_clause")):
            if role == "specification":
                record = copy.deepcopy(record)
                record.setdefault("data", {}).setdefault("description", record.get("raw_text"))
                record["data"]["identity_kind"] = "reference"
                record["data"]["spec_section"] = record.get("source", {}).get("spec_section")
                explicit_tags = list(dict.fromkeys(m.group(0) for pattern in cfg["tag_patterns"]
                    for m in re.finditer(pattern, record.get("raw_text", "")[:cfg["max_regex_text"]], re.IGNORECASE)))
                if explicit_tags and not record["data"].get("tag"):
                    for literal in explicit_tags:
                        item = copy.deepcopy(record)
                        item["data"].update(tag=literal, tag_evidence="literal_specification_fragment")
                        records.append(item)
                    continue
            records.append(record)
    if not records and role == "drawing":
        records, issues = drawing_records(db, package, cfg)
    else:
        issues = package.get("issues", [])
    if not records:
        issues = [*issues, {"code": "NO_EQUIPMENT_RECORDS", "message": "No usable equipment observations; completeness is unverified."}]
    if file["extension"] == "pdf":
        from pypdf import PdfReader
        page_count = len(PdfReader(db.archived_path(file)).pages)
        if any(isinstance(r.get("source", {}).get("pdf_page"), bool) or not isinstance(r.get("source", {}).get("pdf_page"), int) or not 1 <= r["source"]["pdf_page"] <= page_count for r in records):
            raise ValueError("Structured PDF source page is absent or outside actual source bounds")
    return db.import_records(file, slot, role, manifest, records, issues, cfg)


def extract(db, cfg, file_id=None, run_id=None):
    files = [db.file(file_id)] if file_id else db.documents()["files"]
    results = []
    for file in files:
        if not file_id and (file["extension"] not in ("pdf", "dwg", "dxf") or "drawing" not in str(file["metadata"].get("document_type", "")).lower()):
            continue
        try:
            try:
                package, selected_run = sql_package(db, file, run_id)
            except ValueError as error:
                existing = db.conn.execute("SELECT 1 FROM runs x JOIN versions v ON v.id=x.version_id WHERE v.sha256=? LIMIT 1", (file["sha256"],)).fetchone()
                if existing or run_id:
                    raise error
                package = None
            if package:
                result = import_package(db, file["file_id"], package, cfg, "drawing", "drawing", {"adapter": "existing-sql", "run_id": selected_run})
            elif file["extension"] == "pdf":
                cached = db.cached_import(file, "drawing", "drawing", {"adapter": "native-pdf-drawing"}, cfg)
                if cached:
                    results.append({"file_id": file["file_id"], **cached})
                    continue
                path = db.archived_path(file)
                if path.stat().st_size > cfg["max_pdf_bytes"]:
                    raise ValueError("PDF exceeds byte limit; provide a bounded existing extraction")
                package = helper(str(db.skills), "pdf-to-structured", "extract_pdf.py").extract_pdf(path)
                records, issues = drawing_records(db, package, cfg)
                if not records:
                    issues.append({"code": "NO_TAG_EVIDENCE", "message": "No recognized tags; this is not proof of absent equipment."})
                result = db.import_records(file, "drawing", "drawing", {"adapter": "native-pdf-drawing"}, records, issues, cfg)
            elif file["extension"] == "dxf":
                cached = db.cached_import(file, "drawing", "drawing", {"adapter": "dxf-insert-attributes"}, cfg)
                if cached:
                    results.append({"file_id": file["file_id"], **cached})
                    continue
                result = dxf_import(db, file, cfg)
            else:
                result = db.import_records(file, "drawing", "drawing", {"adapter": "native-dwg-unavailable"}, [],
                    [{"code": "DWG_EXTRACTION_PENDING", "message": "Native DWG extraction unavailable; import an actual mapped XLSX export separately."}], cfg)
            results.append({"file_id": file["file_id"], **result})
        except Exception as error:
            result = db.import_records(file, "drawing", "drawing", {"adapter": "extraction-error"}, [],
                [{"code": "SOURCE_UNPROCESSED", "message": str(error)}], cfg)
            results.append({"file_id": file["file_id"], **result, "error": str(error)})
    return results


def dxf_import(db, file, cfg):
    import ezdxf  # Optional; this library does not read native DWG.
    path = db.archived_path(file)
    drawing = ezdxf.readfile(path)
    records = []
    for layout in drawing.layouts:
        for insert in layout.query("INSERT"):
            attributes = {attribute.dxf.tag: attribute.dxf.text for attribute in insert.attribs}
            matches = [(name, text) for name, text in attributes.items() if any(re.fullmatch(pattern, str(text), re.IGNORECASE) for pattern in cfg["tag_patterns"])]
            for attribute_name, text in matches:
                if len(records) >= cfg["max_records"]:
                    raise ValueError("DXF attribute record limit exceeded")
                records.append({"kind": "equipment", "raw_text": str(text),
                    "source": {"method": "ezdxf-insert-attribute-candidate/1", "handle": insert.dxf.handle,
                               "layer": insert.dxf.layer, "layout": layout.name, "attribute": attribute_name,
                               "coordinates": list(insert.dxf.insert), "coordinate_units_code": drawing.units},
                    "data": {"tag": text, "block": insert.dxf.name, "attributes": attributes, "occurrence_only": True},
                    "review": {"status": "unreviewed", "issues": []}})
    return db.import_records(file, "drawing", "drawing", {"adapter": "dxf-insert-attributes"}, records,
        [{"code": "DXF_ATTRIBUTE_CANDIDATES_ONLY", "message": "XREF traversal, graphic recognition and physical location inference are not performed."}], cfg)
