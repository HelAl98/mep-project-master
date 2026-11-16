"""Incremental native/structured requirement indexing with immutable original fragments."""
import copy
import json
from pathlib import Path
import re
import zipfile

from .common import classify, dump, interpreted_patterns, key, now, read_json


def source_context(file, record):
    source = copy.deepcopy(record.get("source", {}))
    data = record.get("data", {})
    page = source.get("pdf_page")
    sheet = next((s for s in file["sheets"] if s["pdf_page"] == page), None)
    metadata = (sheet or file)["metadata"]
    source.update(file_id=file["file_id"], version_id=file["version_id"], analysis_id=file["analysis_id"],
        registry_sheet_id=sheet["sheet_id"] if sheet else None, relative_path=file["relative_path"], filename=file["filename"],
        original_path=file.get("original_path"), sha256=file["sha256"], document_id=metadata.get("document_number"), document_revision=metadata.get("revision"))
    fragments = data.get("fragments") or [{"raw_text": record["raw_text"], **copy.deepcopy(record.get("source", {}))}]
    source["fragments"] = fragments
    pages = sorted({f["pdf_page"] for f in fragments if type(f.get("pdf_page")) is int})
    source["pdf_pages"] = pages
    source["pdf_page_span"] = {"first": pages[0], "last": pages[-1], "actual_pages": pages,
                               "continuation_status": "candidate" if len(pages) > 1 else "single_page"} if pages else None
    context = {"section": source.get("spec_section"), "section_title": data.get("section_title"), "part": data.get("part"),
               "article": data.get("article"), "clause": source.get("clause"), "discipline": data.get("discipline", metadata.get("discipline")),
               "system": data.get("system", metadata.get("system")), "scope": data.get("scope"), "categories": data.get("categories", []),
               "equipment_types": data.get("equipment_types", []), "equipment_tags": data.get("equipment_tags", []),
               "upstream_data": {k: v for k, v in data.items() if k not in ("fragments", "line_fragments")}, "context_provenance": (sheet or file).get("provenance", {})}
    return source, context


def native_text_records(lines, method, locator):
    result, pending = [], []
    section = section_title = part = article = clause = None
    def flush():
        if not pending:
            return
        result.append({"kind": "specification", "raw_text": "".join(text for unused, text in pending),
            "source": {"method": method, **locator(pending[0][0], pending[-1][0]), "spec_section": section, "clause": clause},
            "data": {"part": part, "article": article, "section_title": section_title}, "review": {"status": "unreviewed", "issues": []}})
        pending.clear()
    for index, text in lines:
        stripped = text.strip()
        heading = re.match(r"^(?:#{1,6}\s*)?SECTION\s+([0-9][0-9 ]*[0-9])(?:\s*[-:]\s*|\s+)?(.*)$", stripped, re.I)
        part_match = re.match(r"^PART\s+(\d+)\b", stripped, re.I)
        article_match = re.match(r"^(\d+\.\d+)\b", stripped)
        item = re.match(r"^([A-Z])\.\s", stripped)
        if heading or part_match or article_match or item:
            flush()
            if heading:
                section, section_title = heading.group(1).strip(), heading.group(2) or None
                part = article = clause = None
            elif part_match:
                part = part_match.group(1)
                article = clause = None
            elif article_match:
                article = clause = article_match.group(1)
            else:
                clause = (article + "." if article else "") + item.group(1)
        if not stripped:
            flush()
        else:
            pending.append((index, text))
    flush()
    return result


def docx_records(path, cfg):
    from docx import Document
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > cfg["max_zip_bytes"]:
            raise ValueError("DOCX archive exceeds resource limit")
    document = Document(path)
    body = [(index, value) for index, paragraph in enumerate(document.paragraphs, 1) for value in (paragraph.text, "")]
    result = native_text_records(body, "python-docx-paragraph/1", lambda first, last: {"paragraph": first, "paragraph_end": last})
    for table_index, table in enumerate(document.tables, 1):
        for row_index, row in enumerate(table.rows, 1):
            for cell_index, cell in enumerate(row.cells, 1):
                for paragraph_index, paragraph in enumerate(cell.paragraphs, 1):
                    if paragraph.text.strip():
                        result.append({"kind": "specification", "raw_text": paragraph.text,
                            "source": {"method": "python-docx-table-cell/1", "table": table_index, "row": row_index, "cell": cell_index, "paragraph": paragraph_index},
                            "data": {}, "review": {"status": "unreviewed", "issues": []}})
    return result, [{"code": "DOCX_LAYOUT_SCOPE", "message": "Body paragraphs and tables only; headers/footers/text boxes/comments are not certified covered. No PDF pages were assigned."}]


def prepared_records(store, package, file):
    if package.get("document", {}).get("sha256") != file["sha256"]:
        raise ValueError("Evidence does not match exact registered source bytes")
    if package.get("schema_version") not in ("mep-evidence/1", "mep-requirements/1"):
        raise ValueError("Unsupported requirements evidence schema")
    records = package.get("records")
    if not isinstance(records, list) or not isinstance(package.get("issues", []), list):
        raise ValueError("Structured evidence requires records/issues arrays")
    if len(records) > store.cfg["max_records"]:
        raise ValueError("Structured source exceeds record limit")
    existing = [r for r in records if r.get("kind") in ("specification", "requirement", "paragraph", "specification_clause")]
    if not existing and file["extension"] == "pdf":
        ordered = sorted(records, key=lambda r: (r.get("source", {}).get("pdf_page", 0), r.get("source", {}).get("line_index", 0)))
        package = {**package, "records": ordered}
        extracted = store.ec.helper(str(store.skills), "specification-extractor", "extract_specifications.py").extract_specifications(package)
        existing = extracted["records"]
        issues = extracted["issues"]
        for record in existing:
            ids = [ordered[i].get("core_record_id") for i in record["source"].get("input_record_indexes", [])]
            record["source"]["upstream_core_record_ids"] = [i for i in ids if i]
    else:
        issues = package.get("issues", [])
    # A continuation remains multiple exact fragments; group only by upstream evidence IDs.
    result, seen = [], set()
    section_titles = {}
    for record in existing:
        heading = re.match(r"^SECTION\s+([0-9][0-9 ]*[0-9])\s*[-:]?\s*(.*)$", record.get("raw_text", "").strip(), re.I)
        if heading and heading.group(2):
            section_titles[heading.group(1).strip()] = heading.group(2)
    for raw in existing:
        record = copy.deepcopy(raw)
        if not isinstance(record.get("raw_text"), str) or not isinstance(record.get("source"), dict):
            raise ValueError("Requirements need original raw_text and source object")
        record.setdefault("data", {})
        section = record["source"].get("spec_section")
        if section in section_titles:
            record["data"].setdefault("section_title", section_titles[section])
        clause = record["source"].get("clause")
        article = re.match(r"^(\d+\.\d+)", clause or "")
        if article:
            record["data"].setdefault("article", article.group(1))
        group = record["data"].get("clause_group")
        fragments = record["data"].get("fragments")
        if group and fragments:
            identity = key(group, fragments)
            if identity in seen:
                continue
            seen.add(identity)
            record["raw_text"] = "\n".join(f["raw_text"] for f in fragments)
        result.append(record)
    if file["extension"] == "pdf":
        from pypdf import PdfReader
        page_count = len(PdfReader(store.legacy.archived_path(file)).pages)
        for record in result:
            fragments = record["data"].get("fragments") or [record["source"]]
            for fragment in fragments:
                page = fragment.get("pdf_page")
                if type(page) is not int or not 1 <= page <= page_count:
                    raise ValueError("PDF fragment page absent/outside actual source bounds")
    return result, issues


def index_file(store, file_id, mode="auto", run_id=None, input_json=None, slot="specification"):
    file = store.legacy.file(file_id)
    file["original_path"] = str(Path(store.legacy.documents()["project"]["root"]) / file["relative_path"])
    manifest = {"mode": mode, "run_id": run_id, "input_hash": store.ec.sha(Path(input_json)) if input_json else None,
                "configuration": store.cfg, "implementation": store.signature()}
    package = None
    if input_json:
        path = Path(input_json).resolve(strict=True)
        if path.stat().st_size > store.cfg["max_source_bytes"]:
            raise ValueError("Structured evidence exceeds byte limit")
        package = read_json(path)
    elif mode in ("auto", "sql"):
        try:
            package, selected = store.es.sql_package(store.legacy, file, run_id)
            manifest["selected_run"] = selected
        except ValueError:
            runs_exist = store.conn.execute("SELECT 1 FROM runs x JOIN versions v ON v.id=x.version_id WHERE v.sha256=? LIMIT 1", (file["sha256"],)).fetchone()
            if mode == "sql" or run_id or runs_exist:
                raise
    latest = store.conn.execute("SELECT id,manifest_json FROM tr_imports WHERE project_id=? AND file_id=? AND analysis_id=? AND slot=? ORDER BY rowid DESC LIMIT 1", (store.project, file_id, file["analysis_id"], slot)).fetchone()
    if latest and json.loads(latest["manifest_json"]) == manifest:
        return {"import_id": latest["id"], "unchanged": True, "requirements": 0}
    if package:
        records, issues = prepared_records(store, package, file)
        extraction = "selected_structured_records"
    else:
        path = store.legacy.archived_path(file)
        if path.stat().st_size > store.cfg["max_source_bytes"]:
            raise ValueError("Source exceeds byte limit; provide bounded structured extraction")
        if file["extension"] == "pdf":
            package = store.ec.helper(str(store.skills), "pdf-to-structured", "extract_pdf.py").extract_pdf(path)
            records, issues = prepared_records(store, package, file)
            extraction = "native_pdf_fragments"
        elif file["extension"] in ("txt", "md", "markdown"):
            lines = list(enumerate(path.read_text(encoding="utf-8-sig").splitlines(keepends=True), 1))
            records = native_text_records(lines, "utf8-lines-paragraphs/1", lambda first, last: {"line_start": first, "line_end": last})
            issues, extraction = [], "native_text_paragraphs"
        elif file["extension"] == "docx":
            records, issues = docx_records(path, store.cfg)
            extraction = "docx_body_and_tables"
        else:
            raise ValueError("Specification indexing supports PDF/DOCX/TXT/Markdown or structured evidence")
    if len(records) > store.cfg["max_records"]:
        raise ValueError("Requirement limit exceeded; no truncated import is accepted")
    if not records:
        issues = [*issues, {"code": "NO_REQUIREMENT_EVIDENCE", "message": "No extracted requirements; completeness is not established."}]
    if any(len(r["raw_text"]) > store.cfg["max_text_match"] for r in records):
        issues = [*issues, {"code": "INTERPRETATION_SEARCH_LIMIT", "message": "Original text is retained in full; configured numeric-pattern search covered only a bounded prefix."}]
    coverage = {"extraction": extraction, "technical_completeness": "unverified", "record_count": len(records), "issues": issues}
    identity = key(store.project, file_id, file["analysis_id"], slot, manifest, records, issues)
    with store.transaction():
        inserted = store.insert("tr_imports", {"id": identity, "project_id": store.project, "file_id": file_id,
            "version_id": file["version_id"], "analysis_id": file["analysis_id"], "slot": slot,
            "manifest_json": dump(manifest), "coverage_json": dump(coverage), "issues_json": dump(issues), "created_at": now()})
        if inserted:
            for index, record in enumerate(records):
                source, context = source_context(file, record)
                original_method_available = bool(source.get("method"))
                if not source.get("method"):
                    source["method"] = "supplied_structured_evidence_unverified"
                reliable = original_method_available and bool(source.get("pdf_pages") or source.get("line_start") or source.get("paragraph") or source.get("row"))
                for mapping in store.cfg["section_mappings"]:
                    if re.search(mapping["section_pattern"], str(context.get("section") or "")):
                        context.setdefault("mapping_candidates", []).append(mapping)
                        for field, value in mapping.get("fields", {}).items():
                            if field not in ("discipline", "system", "scope", "categories", "equipment_types", "equipment_tags"):
                                raise ValueError("Unsupported section-context mapping field")
                            if context.get(field) in (None, "", []):
                                context[field] = value
                for field, aliases in (("discipline", store.cfg["discipline_aliases"]), ("system", store.cfg["system_aliases"])):
                    context["original_" + field] = context.get(field)
                    context[field] = aliases.get(context.get(field), context.get(field))
                classifications = classify(record["raw_text"], store.cfg)
                for mapping in context.get("mapping_candidates", []):
                    for topic in mapping.get("topics", []):
                        classifications.append({"category": mapping.get("technical_category", "Unclassified"), "topic": topic,
                            "literal": None, "span": None, "method": "section_mapping_candidate", "basis": mapping.get("basis")})
                rid = key(identity, index, record)
                core_id = record.get("core_record_id")
                if core_id and not store.conn.execute("SELECT 1 FROM records r JOIN versions v ON v.id=r.version_id WHERE r.id=? AND v.sha256=?", (core_id, file["sha256"])).fetchone():
                    raise ValueError("Core requirement source does not match registered bytes")
                store.insert("tr_requirements", {"id": rid, "project_id": store.project, "import_id": identity,
                    "core_record_id": core_id, "original_text": record["raw_text"], "source_json": dump(source), "context_json": dump(context),
                    "classification_json": dump(classifications),
                    "interpretations_json": "[]",
                    "reference_status": "source_reference_available" if reliable else "source_reference_incomplete", "created_at": now()})
                supplied_interpretations = record.get("data", {}).get("interpretations", [])
                if not isinstance(supplied_interpretations, list):
                    raise ValueError("Structured interpretations must be an array")
                for parsed in interpreted_patterns(record["raw_text"], store.cfg) + supplied_interpretations:
                    if not isinstance(parsed, dict) or not parsed.get("parameter") or parsed.get("operator") not in ("eq", "min", "max", "range", "contains") or "value" not in parsed:
                        raise ValueError("Structured interpretations need explicit parameter/operator/value")
                    store.insert("tr_interpretations", {"id": key(rid, parsed), "project_id": store.project, "requirement_id": rid,
                        "payload_json": dump(parsed), "method": "configured_literal_pattern" if parsed.get("pattern_id") else "supplied_structured_candidate", "review_id": None, "created_at": now()})
                store.conn.execute("INSERT INTO tr_fts(project_id,requirement_id,text) VALUES(?,?,?)", (store.project, rid, record["raw_text"] + "\n" + dump(context)))
    return {"import_id": identity, "unchanged": not inserted, "requirements": len(records) if inserted else 0, "coverage": coverage}


def index(store, file_id=None, **options):
    files = [store.legacy.file(file_id)] if file_id else [f for f in store.legacy.documents()["files"] if "specification" in str(f["metadata"].get("document_type", "")).casefold()]
    if not file_id and (options.get("input_json") or options.get("run_id")):
        raise ValueError("An explicit file ID is needed for selected structured evidence")
    results = []
    for file in files:
        try:
            results.append({"file_id": file["file_id"], **index_file(store, file["file_id"], **options)})
        except Exception as error:
            identity = key(store.project, file["analysis_id"], options, str(error), store.cfg, store.signature())
            with store.transaction():
                store.insert("tr_imports", {"id": identity, "project_id": store.project, "file_id": file["file_id"],
                    "version_id": file["version_id"], "analysis_id": file["analysis_id"], "slot": options.get("slot", "specification"),
                    "manifest_json": dump({"error": str(error), "options": options}),
                    "coverage_json": dump({"extraction": "unprocessed", "technical_completeness": "unverified", "record_count": 0}),
                    "issues_json": dump([{"code": "SPECIFICATION_UNPROCESSED", "message": str(error)}]), "created_at": now()})
            results.append({"file_id": file["file_id"], "import_id": identity, "error": str(error)})
    return results
