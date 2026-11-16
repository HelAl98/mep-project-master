from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


def dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def key(*values):
    return hashlib.sha256(dump(values).encode("utf-8")).hexdigest()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def numeric(value):
    if value is None or isinstance(value, (bool, list, dict)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


def safe_name(value, maximum=60):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    text = re.sub(r"\s+", "_", text)[:maximum].rstrip(" .") or "UNSPECIFIED"
    if text.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        text = "_" + text
    return text


def defaults():
    return {"schema_version": "mep-package-config/1", "output_root": None, "language": "en", "rtl": False,
        "font": "Calibri", "font_size": 10, "accent_color": "17365D", "page_size": "A4",
        "category_aliases": {}, "discipline_aliases": {}, "category_columns": {},
        "parameter_order": ["flow", "airflow", "head", "pressure", "esp", "cooling_capacity", "heating_capacity", "motor_power", "voltage", "current", "frequency", "phase", "duty_arrangement"],
        "mandatory_parameters": {}, "type_requirements": {}, "quantity_parameters": ["quantity", "verified_quantity"],
        "count_units": ["ea", "each", "no", "nos", "nr", "unit", "units"],
        "group_by": ["discipline", "system", "category", "type", "building"], "category_titles": {},
        "file_names": {"register": "Equipment_Register.xlsx", "specifications": "Technical_Specifications.docx",
            "matrix": "Requirements_Matrix.xlsx", "review": "Review_Status.xlsx", "rfq": "RFQ_Draft.docx", "sources": "Source_References.xlsx"},
        "specification_sections": ["General Requirements", "Mechanical Requirements", "Electrical Requirements", "BMS and Controls", "Documentation Requirements"],
        "section_routes": {"Electrical": "Electrical Requirements", "Controls and BMS": "BMS and Controls", "Documentation": "Documentation Requirements",
                           "Construction": "Mechanical Requirements", "Performance": "Mechanical Requirements", "Testing": "Mechanical Requirements", "Installation": "Mechanical Requirements"},
        "rfq_template": None, "source_links": True, "max_path_length": 235, "max_excel_rows": 1048575,
        "mandatory_coverage": ["mechanical_drawings", "equipment_schedules", "boq", "mechanical_specifications", "electrical_documentation", "electrical_specifications", "bms_documentation", "bms_specifications"],
        "readiness_requirements": {"identity": True, "type": True, "applicable_revisions": True, "quantity": True, "reviewed_parameters": True, "approved_requirements": True, "coverage": True, "no_open_cases": True},
        "require_formal_release_decision": False, "formal_release_review_ids": []}


def configuration(path=None):
    result = defaults()
    supplied = read_json(path) if path else {}
    if not isinstance(supplied, dict) or set(supplied) - set(result):
        raise ValueError("Unknown package configuration keys")
    for name, value in supplied.items():
        result[name] = {**result[name], **value} if isinstance(result[name], dict) and isinstance(value, dict) else value
    if result["schema_version"] != "mep-package-config/1" or result["language"] not in ("en", "ar"):
        raise ValueError("Unsupported package schema/language")
    if result["language"] != "en":
        raise ValueError("English report labels are supported initially; original source language/RTL text is preserved")
    if result["readiness_requirements"] != defaults()["readiness_requirements"] or result["mandatory_coverage"] != defaults()["mandatory_coverage"]:
        raise ValueError("Mandatory final-readiness safeguards cannot be disabled in configuration")
    if not re.fullmatch(r"[A-Fa-f0-9]{6}", result["accent_color"]):
        raise ValueError("Accent color must be six hex digits")
    if not set(result["group_by"]) <= {"discipline", "system", "category", "type", "building", "floor", "scope"} or "category" not in result["group_by"] or "type" not in result["group_by"]:
        raise ValueError("Grouping requires category/type and supported scope fields")
    expected = {"register": ".xlsx", "matrix": ".xlsx", "review": ".xlsx", "sources": ".xlsx", "specifications": ".docx", "rfq": ".docx"}
    if set(result["file_names"]) != set(expected) or len(set(n.casefold() for n in result["file_names"].values())) != len(expected):
        raise ValueError("Output component names must be complete and unique")
    for name, suffix in expected.items():
        value = result["file_names"][name]
        if not isinstance(value, str) or safe_name(value, 120) != value or Path(value).suffix.lower() != suffix:
            raise ValueError("Output names must be safe literal basenames with their required extension")
    for name in ("max_path_length", "max_excel_rows", "font_size"):
        if type(result[name]) is not int or result[name] < 1:
            raise ValueError(f"{name} must be positive")
    if not 8 <= result["max_excel_rows"] <= 1048575 or result["max_path_length"] > 30000 or result["page_size"] not in ("A4", "Letter"):
        raise ValueError("Invalid export sizing constraints")
    dump(result)
    return result


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
