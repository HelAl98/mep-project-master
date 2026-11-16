"""Configuration, deterministic identities, dependency discovery and unit handling."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import unicodedata


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def key(*parts):
    return hashlib.sha256(dump(parts).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def implementation_signature(root):
    own = Path(__file__).resolve().parent.parent
    paths = sorted(own.rglob("*.py")) + sorted((own / "migrations").glob("*.sql"))
    paths += [Path(root) / skill / "scripts" / script for skill, script in (
        ("pdf-to-structured", "extract_pdf.py"), ("drawing-analyzer", "analyze_drawing.py"),
        ("dwg-to-excel", "extract_dwg.py"), ("etl-pipeline", "mep_store.py"))]
    return key([(str(path.relative_to(own)) if path.is_relative_to(own) else str(path.relative_to(root)), sha(path)) for path in paths])


def skills_root(explicit=None):
    candidates = [Path(explicit)] if explicit else list(Path(__file__).resolve().parents)
    for parent in candidates:
        for root in (parent, parent / ".agents" / "skills"):
            if (root / "mep-document-registry/scripts/mep_registry/db.py").is_file():
                return root.resolve()
    raise ValueError("Sibling mep-document-registry skill not found; supply --skills-root")


@lru_cache(maxsize=16)
def helper(root, skill, script):
    path = Path(root) / skill / "scripts" / script
    if not path.is_file():
        raise ValueError(f"Required existing helper unavailable: {path}")
    name = "_equipment_helper_" + key(str(path))[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CATEGORY_GROUPS = {
    "HVAC": ["AHU", "FAHU", "FCU", "CHILLER", "CHWP", "CWP", "HWP", "EF", "SF", "FAF", "VRF", "VRV", "PAC"],
    "Fire Fighting": ["EFP", "DFP", "JOCKEY-P", "FPC"],
    "Plumbing": ["DWP", "BPS", "TP", "SEWP", "SP", "WH", "TANK", "WTP"],
    "Electrical Power": ["TR", "GEN", "MDB", "SMDB", "DB", "MCC", "ATS", "UPS", "CAPBANK"],
    "Low Current": ["FACP", "NETWORK-CAB", "CCTV", "ACCESS-CONTROL"],
    "BMS": ["BMS", "DDC", "CP"]}


def default_config():
    categories = [{"id": name, "discipline": discipline, "aliases": [name], "prefixes": [name]}
                  for discipline, names in CATEGORY_GROUPS.items() for name in names]
    descriptions = {"AHU": r"\bair handling units?\b", "FAHU": r"\bfresh air handling units?\b",
                    "FCU": r"\bfan coil units?\b", "CHILLER": r"\bchillers?\b",
                    "CHWP": r"\bchilled water pumps?\b", "CWP": r"\bcondenser water pumps?\b",
                    "HWP": r"\bheating water pumps?\b", "EF": r"\bexhaust fans?\b", "SF": r"\bsupply fans?\b",
                    "EFP": r"\belectric fire pumps?\b", "DFP": r"\bdiesel fire pumps?\b", "JOCKEY-P": r"\bjockey pumps?\b",
                    "TR": r"\btransformers?\b", "GEN": r"\bgenerators?\b", "MDB": r"\bmain distribution boards?\b",
                    "FACP": r"\bfire alarm (?:control )?panels?\b", "WH": r"\bwater heaters?\b"}
    for item in categories:
        if item["id"] in descriptions:
            item["description_patterns"] = [descriptions[item["id"]]]
    return {
        "schema_version": "mep-equipment-config/1", "categories": categories,
        "tag_patterns": [r"(?<![\w])(?:[A-Z][A-Z0-9]*(?:[-_ ]+[A-Z]+)*[-_ ]+)(?:[A-Z]+\d+[-_ ]+)?\d+[A-Z]?(?![\w])"],
        "tag_aliases": {}, "prefix_aliases": {"CHW-P": "CHWP"}, "category_aliases": {},
        "discipline_aliases": {}, "building_aliases": {}, "floor_aliases": {},
        "parameter_aliases": {"flow rate": "flow", "air flow": "airflow", "motor power": "motor_power",
                              "rated voltage": "voltage", "rated current": "current", "esp": "esp"},
        "units": {
            "m3/h": ["volume_flow", "0.0002777777777777777777777777778", "m3/s"],
            "m\u00b3/h": ["volume_flow", "0.0002777777777777777777777777778", "m3/s"],
            "l/s": ["volume_flow", "0.001", "m3/s"], "l/min": ["volume_flow", "0.00001666666666666666666666666667", "m3/s"],
            "cfm": ["volume_flow", "0.0004719474432", "m3/s"], "m3/s": ["volume_flow", "1", "m3/s"],
            "kw": ["active_power", "1000", "W"], "w": ["active_power", "1", "W"],
            "kva": ["apparent_power", "1000", "VA"], "va": ["apparent_power", "1", "VA"],
            "v": ["voltage", "1", "V"], "kv": ["voltage", "1000", "V"],
            "a": ["current", "1", "A"], "ka": ["current", "1000", "A"],
            "m": ["length", "1", "m"], "mm": ["length", "0.001", "m"],
            "pa": ["pressure", "1", "Pa"], "kpa": ["pressure", "1000", "Pa"],
            "bar": ["pressure", "100000", "Pa"], "hz": ["frequency", "1", "Hz"],
            "rpm": ["speed", "1", "rpm"]},
        "type_required_parameters": ["motor_power", "voltage", "duty_arrangement"],
        "unitless_parameters": ["phase", "poles", "quantity", "duty_units", "standby_units"],
        "type_required_by_category": {}, "match_context_fields": ["building", "floor", "room", "system", "scope"],
        "max_candidate_pairs": 50000, "max_records": 100000, "max_pdf_bytes": 100000000,
        "max_json_bytes": 100000000, "max_zip_uncompressed_bytes": 500000000,
        "max_regex_text": 20000, "numeric_relative_tolerance": "0.000001",
        "quantity_units": ["no", "nos", "nr", "each", "ea", "unit", "units"],
        "auto_confirm": False}


def config(path=None):
    result = default_config()
    supplied = read_json(path) if path else {}
    if not isinstance(supplied, dict) or set(supplied) - set(result):
        raise ValueError("Unknown configuration keys or non-object configuration")
    for name, value in supplied.items():
        if isinstance(result[name], dict) and isinstance(value, dict):
            result[name] = {**result[name], **value}
        else:
            result[name] = value
    if result["schema_version"] != "mep-equipment-config/1" or result["auto_confirm"] is not False:
        raise ValueError("Unsupported config version; this release requires explicit engineering confirmation")
    for name in ("max_candidate_pairs", "max_records", "max_pdf_bytes", "max_json_bytes", "max_zip_uncompressed_bytes", "max_regex_text"):
        if isinstance(result[name], bool) or not isinstance(result[name], int) or result[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    for pattern in result["tag_patterns"]:
        re.compile(pattern, re.IGNORECASE)
    ids = [item["id"] for item in result["categories"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate equipment category identifiers")
    for name in ("tag_aliases", "prefix_aliases", "category_aliases", "discipline_aliases", "building_aliases", "floor_aliases", "parameter_aliases", "units", "type_required_by_category"):
        if not isinstance(result[name], dict):
            raise ValueError(f"{name} must be an object")
    if not set(result["match_context_fields"]) <= {"building", "floor", "room", "system", "scope"}:
        raise ValueError("Unsupported matching context field")
    tolerance = Decimal(str(result["numeric_relative_tolerance"]))
    if not tolerance.is_finite() or not 0 <= tolerance <= Decimal("0.01"):
        raise ValueError("Tolerance must be finite and between 0 and 0.01")
    for unit, entry in result["units"].items():
        if not isinstance(entry, list) or len(entry) != 3 or not Decimal(str(entry[1])).is_finite() or Decimal(str(entry[1])) <= 0:
            raise ValueError(f"Invalid unit conversion: {unit}")
    dump(result)
    return result


def alias(value, mapping):
    if value is None or value == "":
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return next((v for k, v in mapping.items() if str(k).casefold() == text.casefold()), text)


def tag(value, cfg):
    if value is None or isinstance(value, (bool, dict, list)) or str(value).startswith("="):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    text = re.sub(r"[\s_\u2010\u2011\u2013\u2014]+", "-", text)
    text = re.sub(r"-+", "-", text)
    for prefix, replacement in sorted(cfg["prefix_aliases"].items(), key=lambda pair: -len(pair[0])):
        if text.startswith(prefix.upper() + "-"):
            text = replacement.upper() + text[len(prefix):]
            break
    return alias(text, cfg["tag_aliases"])


def category(value, normalized_tag, description, cfg):
    explicit = alias(value, cfg["category_aliases"])
    if explicit:
        matches = [c for c in cfg["categories"] if explicit.casefold() in [str(v).casefold() for v in [c["id"]] + c.get("aliases", [])]]
        return (matches[0]["id"], "explicit") if len(matches) == 1 else (explicit, "explicit_unmapped")
    candidates = []
    prefix_matches = [item["id"] for item in cfg["categories"] if normalized_tag and any(normalized_tag.upper().startswith(p.upper() + "-") for p in item.get("prefixes", []))]
    if prefix_matches:
        return (prefix_matches[0], "inferred") if len(set(prefix_matches)) == 1 else (None, "ambiguous")
    for item in cfg["categories"]:
        if description and any(re.search(p, description, re.IGNORECASE) for p in item.get("description_patterns", [])):
            candidates.append(item["id"])
    values = sorted(set(candidates))
    return (values[0], "inferred") if len(values) == 1 else (None, "ambiguous" if values else "unknown")


def decimal(value):
    if value is None or isinstance(value, bool) or isinstance(value, (dict, list)):
        return None
    try:
        result = Decimal(str(value).strip())
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def parameter(raw, cfg):
    name = alias(raw.get("name"), cfg["parameter_aliases"])
    if not name:
        raise ValueError("Parameter requires an explicit name")
    name = str(name).strip().casefold().replace(" ", "_")
    value, unit = raw.get("value"), raw.get("unit")
    numeric = decimal(value)
    inline_unit = None
    if numeric is None and unit is None and isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d].*?)\s*", value)
        if match and match.group(2).casefold() in cfg["units"]:
            numeric, inline_unit = decimal(match.group(1)), match.group(2)
            unit = inline_unit
    conversion = cfg["units"].get(str(unit).strip().casefold()) if unit else None
    normalized_value = normalized_unit = dimension = None
    status = "unconverted"
    if numeric is not None and conversion:
        dimension, factor, normalized_unit = conversion
        normalized_value = str(numeric * Decimal(str(factor)))
        status = "converted"
    elif numeric is not None and unit is None:
        status = "unit_missing"
    return {"name": str(name), "original": raw, "value": value, "unit": unit,
            "normalized_value": normalized_value, "normalized_unit": normalized_unit,
            "dimension": dimension, "normalization_status": status, "parsed_inline_unit": inline_unit}


def compatible_parameters(left, right, cfg):
    """Return disagreements, retaining absent and incomparable parameters separately."""
    conflicts, unknown = [], []
    for name in sorted(set(left) & set(right)):
        a, b = left[name], right[name]
        if a.get("normalized_value") is not None and b.get("normalized_value") is not None and a["dimension"] == b["dimension"]:
            x, y = Decimal(a["normalized_value"]), Decimal(b["normalized_value"])
            tolerance = Decimal(str(cfg["numeric_relative_tolerance"])) * max(abs(x), abs(y), Decimal("1e-30"))
            if abs(x - y) > tolerance:
                conflicts.append(name)
        elif a.get("unit") == b.get("unit") and a.get("value") is not None and b.get("value") is not None:
            if str(a["value"]).strip().casefold() != str(b["value"]).strip().casefold():
                conflicts.append(name)
        else:
            unknown.append(name)
    return conflicts, unknown
