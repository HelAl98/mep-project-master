"""Exclusive, versioned outputs with readiness gates and no engineering database writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from urllib.parse import quote

from .common import dump, key, now, read_json, safe_name, sha, write_json
from .documents import DRAFT, rfq, specifications
from .planning import plans
from .spreadsheets import register_rows, workbook


COMPONENTS = {"register", "specifications", "matrix", "review", "rfq", "sources"}


def template(cfg):
    path = Path(cfg["rfq_template"]).expanduser().resolve(strict=True) if cfg["rfq_template"] else Path(__file__).resolve().parents[2] / "assets/templates/rfq.json"
    value = read_json(path)
    mandatory = {"Unit Price", "Total Price", "Currency", "Delivery Period", "Quotation Validity", "Warranty", "Payment Terms", "Applicable Taxes", "Exclusions and Deviations"}
    if not isinstance(value, dict) or not isinstance(value.get("commercial_fields"), list) or not mandatory <= set(value["commercial_fields"]):
        raise ValueError("RFQ template must preserve all blank requested commercial response fields")
    if value.get("draft_notice") != DRAFT or not value.get("title"):
        raise ValueError("RFQ template cannot remove the internal-draft/non-issue label")
    return value, sha(path)


def requirement_rows(repo, record, groups, cfg):
    ids = {t["id"] for g in groups for t in g["targets"]}
    # A type can carry additional reviewed requirements; retain its explicit scope.
    ids.update(g["verified_type_id"] for g in groups if g["verified_type_id"])
    raw = [r for r in repo.export_helpers.matrix(record) if r["equipment_id"] in ids]
    grouped = {}
    for row in raw:
        identity = (row["requirement_id"], row["applicability"], row["verification_status"])
        general = any(l["requirement_id"] == row["requirement_id"] and l["entity_id"] == row["equipment_id"] and l["level"] in ("project", "discipline") for l in record["applicability"])
        technical_categories = [c["category"] for c in row["technical_classification"]]
        section = "General Requirements" if general else next((cfg["section_routes"][c] for c in technical_categories if c in cfg["section_routes"]), "Other Documented Applicable Requirements")
        discipline = str(row.get("discipline") or "").casefold()
        if not general and "Documentation" not in technical_categories:
            if "bms" in discipline or "control" in discipline:
                section = "BMS and Controls"
            elif any(word in discipline for word in ("electrical", "power", "lighting", "elv", "low current")):
                section = "Electrical Requirements"
        item = grouped.setdefault(identity, {**row, "equipment_ids": [], "equipment_tags": [], "document_section": section})
        item["equipment_ids"].append(row["equipment_id"])
        item["equipment_tags"].extend(row["equipment_tags"])
    for item in grouped.values():
        item["equipment_ids"] = sorted(set(item["equipment_ids"]))
        item["equipment_tags"] = sorted(set(item["equipment_tags"]))
    return list(grouped.values())


def source_rows(record, groups, requirements, project_root, output_dir, cfg):
    rows = []
    for requirement in requirements:
        source = requirement["source_document"]
        rows.append({"Requirement ID": requirement["requirement_id"], "Equipment IDs": requirement["equipment_ids"],
            "Original Document": source.get("filename"), "Relative File Path": source.get("relative_path"), "Document ID": source.get("document_id"),
            "File Hash": source.get("sha256"), "Revision": source.get("document_revision"), "Drawing Number": source.get("drawing_number"),
            "PDF Pages": source.get("pdf_pages", source.get("pdf_page")), "Printed Page": source.get("printed_page"),
            "Section": requirement.get("section"), "Part": requirement.get("part"), "Article": requirement.get("article"), "Clause": requirement.get("clause"),
            "Review Status": requirement["verification_status"], "Source Detail": source})
    for group in groups:
        for target in group["targets"]:
            for occurrence in target["occurrences"]:
                source = occurrence["source"]
                rows.append({"Requirement ID": None, "Equipment IDs": [target["id"]], "Original Document": Path(source.get("relative_path", "")).name,
                    "Relative File Path": source.get("relative_path"), "Document ID": source.get("document_id"), "File Hash": source.get("sha256"),
                    "Revision": source.get("document_revision"), "Drawing Number": source.get("drawing_number"), "PDF Pages": source.get("pdf_page"),
                    "Worksheet": source.get("sheet"), "Row": source.get("row"), "CAD Handle": source.get("handle"), "Review Status": occurrence["verification_status"], "Source Detail": source})
        for total in group["quantity"]["boq_quantities"] + group["quantity"]["schedule_quantities"]:
            for item in total["rows"]:
                source = item["source"]
                rows.append({"Equipment IDs": [t["id"] for t in group["targets"]], "Source Role": total["role"],
                    "Relative File Path": source.get("relative_path"), "File Hash": source.get("sha256"), "Revision": source.get("document_revision"),
                    "PDF Pages": source.get("pdf_page"), "Worksheet": source.get("sheet"), "Row": source.get("row"), "Source Detail": source})
    for row in rows:
        relative = row.get("Relative File Path")
        if not cfg["source_links"] or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            continue
        actual = (project_root / relative).resolve()
        if not actual.is_relative_to(project_root) or actual.suffix.lower() not in (".pdf", ".dwg", ".dxf", ".xlsx", ".csv", ".docx", ".txt", ".md"):
            continue
        try:
            row["Relative File Link"] = "./" + quote(os.path.relpath(actual, output_dir).replace("\\", "/"), safe="/.-_")
        except ValueError:
            row["Relative File Link"] = None
    return rows


def package_status(groups):
    statuses = {g["readiness"]["status"] for g in groups}
    for status in ("BLOCKED_BY_CONFLICTS", "SUPERSEDED", "DRAFT_INCOMPLETE", "PENDING_ENGINEERING_REVIEW"):
        if status in statuses:
            return status
    return "READY_FOR_EXPORT" if groups else "DRAFT_INCOMPLETE"


def output_root(path, repo):
    root = Path(path).expanduser().resolve()
    project = Path(repo.project_row["root_path"]).resolve()
    if root == project or project.is_relative_to(root) or root == repo.path.parent:
        raise ValueError("Use a dedicated output subdirectory, never a source root/ancestor or the database directory itself")
    marker = root / ".mep-registry-output.json"
    if root.exists():
        if not marker.is_file() or read_json(marker).get("producer") != "mep-technical-package-generator":
            raise ValueError("Existing output root is not a dedicated package-generator directory")
    else:
        root.mkdir(parents=True, exist_ok=False)
        write_json(marker, {"producer": "mep-technical-package-generator", "created_at": now(), "kind": "generated_output_exclusion"})
    return root


@contextmanager
def lock(root):
    path = root / ".package-generation.lock"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(dump({"pid": os.getpid(), "started_at": now()}))
    except FileExistsError:
        raise ValueError("Output root is locked by another/incomplete process; inspect the lock before manual recovery") from None
    try:
        yield
    finally:
        path.unlink()  # Only this process's exact exclusive lock; no recursive cleanup.


def validate_manifest(path):
    manifest = read_json(path)
    if manifest.get("schema_version") != "mep-package-manifest/1":
        raise ValueError("Unsupported package manifest")
    problems = []
    for output in manifest.get("outputs", []):
        file = (path.parent / output["name"]).resolve()
        if not file.is_relative_to(path.parent.resolve()) or not file.is_file() or sha(file) != output["sha256"]:
            problems.append(output["name"])
    return manifest, problems


def generate(repo, record, cfg, output, mode="draft", components=None, categories=None):
    if mode not in ("draft", "approved"):
        raise ValueError("Generation mode must be draft/approved")
    components = set(components or COMPONENTS)
    if not components <= COMPONENTS or not components:
        raise ValueError("Unknown output components")
    all_groups = plans(repo, record, cfg, categories)
    if not all_groups:
        raise ValueError("No upstream equipment groups exist for this selection; no empty category folders are created")
    by_category = {}
    for group in all_groups:
        by_category.setdefault(group["category"], []).append(group)
    if mode == "approved" and any(g["readiness"]["status"] != "READY_FOR_EXPORT" for g in all_groups):
        raise ValueError("Final technical package blocked: inspect readiness/issues; use draft mode for internal review")
    rfq_template, template_hash = template(cfg)
    receipt = repo.project_state()
    snapshot_id = key(receipt)
    root = output_root(output, repo)
    results = []
    with lock(root):
        for category, groups in sorted(by_category.items()):
            discipline_values = sorted({g["discipline"] or "UNCLASSIFIED" for g in groups})
            discipline = discipline_values[0] if len(discipline_values) == 1 else "MULTIDISCIPLINE"
            entity_ids = sorted(t["id"] for g in groups for t in g["targets"])
            package_id = key(repo.project, category, entity_ids)
            version = key(snapshot_id, cfg, repo.code_signature(), template_hash, mode, sorted(components), package_id)
            category_root = root / safe_name(discipline) / (safe_name(cfg["category_titles"].get(category, category)) + "_" + key(category)[:8])
            candidate = (category_root / ("V_" + version[:16])).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError("Resolved output escaped dedicated root")
            attempt = 1
            while candidate.exists():
                existing = candidate / "Package_Manifest.json"
                if existing.is_file():
                    previous, damaged = validate_manifest(existing)
                    if previous["version_id"] == version and not damaged and previous["generation_status"] == "completed":
                        results.append({"package_id": package_id, "version_id": version, "directory": str(candidate), "unchanged": True, "status": previous["technical_readiness"]})
                        break
                    if previous["version_id"] == version:
                        raise ValueError("Existing completed package is damaged; preserve it and investigate before regeneration")
                    raise ValueError("Version directory collision; refusing overwrite")
                attempt += 1
                candidate = (category_root / ("V_" + version[:16] + f"_attempt_{attempt}")).resolve()
                if not candidate.is_relative_to(root):
                    raise ValueError("Attempt path escaped output root")
            else:
                names = [cfg["file_names"][c] for c in components] + ["Package_Manifest.json", "Package_Data.json", "Generation_State.json"]
                if any(len(str(candidate / name)) > cfg["max_path_length"] for name in names):
                    raise ValueError("Configured Windows path budget exceeded; choose a shorter output root/names")
                candidate.mkdir(parents=True, exist_ok=False)
                write_json(candidate / "Generation_State.json", {"generation_status": "started", "package_id": package_id, "version_id": version, "started_at": now()})
                status = package_status(groups)
                metadata = {"project": record["project"]["name"], "category": category, "package_id": package_id, "version": version[:16],
                    "status": status if mode == "approved" else status + " | INTERNAL DRAFT", "title": cfg["category_titles"].get(category, category) + " Technical Package"}
                requirements = requirement_rows(repo, record, groups, cfg)
                if mode == "approved":
                    approved_ids = {(r["equipment_id"], r["requirement_id"]) for r in repo.export_helpers.approved(record)["requirements"]}
                    if any(r["applicability"] != "not_applicable" and any((eid, r["requirement_id"]) not in approved_ids for eid in r["equipment_ids"]) for r in requirements):
                        raise ValueError("Upstream approved-requirement filter withheld a selected clause; approved output blocked")
                sources = source_rows(record, groups, requirements, Path(repo.project_row["root_path"]).resolve(), candidate, cfg)
                selected_ids = {t["id"] for g in groups for t in g["targets"]}
                selected_ids.update(g["verified_type_id"] for g in groups if g["verified_type_id"])
                review_rows = [{"Group ID": g["group_id"], "Equipment IDs": [t["id"] for t in g["targets"]], "Status": g["readiness"]["status"], "Reasons": g["readiness"]["reasons"], "Quantity": g["quantity"]} for g in groups]
                cases = [c for c in record["cases"] if c["entity_id"] in selected_ids]
                coverage = [c for c in record["coverage"] if c["entity_id"] in selected_ids]
                data = {"schema_version": "mep-package-data/1", "metadata": metadata, "groups": groups, "requirements": requirements,
                    "source_references": sources, "review_cases": cases, "coverage": coverage, "decisions": record["decisions"],
                    "decision_sources": record["decision_sources"], "database_snapshot": receipt, "original_text_not_summarized": True}
                try:
                    write_json(candidate / "Package_Data.json", data)
                    literal = repo.export_helpers.literal
                    for component in sorted(components):
                        path = candidate / cfg["file_names"][component]
                        if component == "register":
                            tables = [("Equipment", register_rows(groups, cfg), ["Item", "Category", "Verified Type ID", "Original Tags", "Final Reviewed Quantity"])]
                        elif component == "matrix":
                            tables = [("Requirements", requirements, ["requirement_id", "equipment_ids", "equipment_tags", "original_requirement_text", "source_document", "applicability", "verification_status"])]
                        elif component == "review":
                            tables = [("GroupReadiness", review_rows, ["Group ID", "Status", "Reasons"]), ("EngineeringCases", cases, ["id", "type", "status", "evidence"]), ("SourceCoverage", coverage, ["entity_id", "category", "status", "available", "successfully_processed", "reviewed", "approved"])]
                        elif component == "sources":
                            tables = [("SourceReferences", sources, ["Original Document", "Relative File Path", "File Hash", "Revision", "PDF Pages", "Section", "Clause", "Relative File Link"])]
                        elif component == "specifications":
                            specifications(path, metadata, groups, requirements, cfg)
                            continue
                        else:
                            rfq(path, metadata, groups, requirements, cfg, rfq_template)
                            continue
                        workbook(path, tables, metadata, cfg, literal)
                    files = [{"name": p.name, "sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(candidate.iterdir()) if p.is_file()]
                    manifest = {"schema_version": "mep-package-manifest/1", "project_id": repo.project, "package_id": package_id, "version_id": version,
                        "category": category, "equipment_ids": entity_ids, "technical_type_ids": sorted({g["verified_type_id"] for g in groups if g["verified_type_id"]}),
                        "requirement_ids": sorted({r["requirement_id"] for r in requirements}), "source_revisions": sources,
                        "review_decision_ids": receipt["eq_review_ids"], "registry_review_ids": receipt["registry_review_ids"],
                        "generation_timestamp": now(), "generation_status": "completed", "technical_readiness": status, "mode": mode,
                        "group_readiness": review_rows, "rfq_ready_technical_information": mode == "approved" and status == "READY_FOR_EXPORT",
                        "rfq_document_is_draft": True, "rfq_issued": False, "formal_package_release": False,
                        "database_snapshot_id": snapshot_id, "database_snapshot": receipt, "configuration_hash": key(cfg),
                        "generator_signature": repo.code_signature(), "rfq_template_hash": template_hash, "components": sorted(components), "outputs": files}
                    write_json(candidate / "Package_Manifest.json", manifest)
                    results.append({"package_id": package_id, "version_id": version, "directory": str(candidate), "unchanged": False, "status": status, "generation_status": "completed"})
                except BaseException as error:
                    write_json(candidate / "Generation_Failure.json", {"generation_status": "failed", "error_type": type(error).__name__, "message": str(error), "timestamp": now()})
                    raise
    return {"packages": results, "database_access": "read_only", "rfq_issued": False}


def inspect(repo, root, manifest_path=None):
    root = Path(root).expanduser().resolve(strict=True)
    paths = [Path(manifest_path).expanduser().resolve(strict=True)] if manifest_path else sorted(root.rglob("Package_Manifest.json"))
    current = key(repo.project_state())
    result = []
    for path in paths:
        if not path.is_relative_to(root):
            raise ValueError("Manifest lies outside selected output root")
        manifest, damaged = validate_manifest(path)
        if manifest["project_id"] != repo.project:
            continue
        result.append({"manifest": str(path), "package_id": manifest["package_id"], "version_id": manifest["version_id"],
            "technical_readiness_at_generation": manifest["technical_readiness"], "generation_status": manifest["generation_status"],
            "potentially_outdated": manifest["database_snapshot_id"] != current, "damaged_outputs": damaged,
            "engineering_evidence_was_not_modified": True})
    incomplete = [str(p.parent) for p in root.rglob("Generation_State.json") if not (p.parent / "Package_Manifest.json").is_file()]
    return {"packages": result, "incomplete_generation_directories": incomplete, "previous_versions_unchanged": True}
