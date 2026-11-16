from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
import re


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def key(*parts):
    return hashlib.sha256(dump(parts).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def number(value):
    if isinstance(value, (dict, list, bool)) or value is None:
        return None
    try:
        result = Decimal(str(value).strip())
        return result if result.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


COVERAGE = ["mechanical_drawings", "equipment_schedules", "boq", "mechanical_specifications",
            "electrical_documentation", "electrical_specifications", "bms_documentation", "bms_specifications"]


def defaults():
    topics = {
        "Performance": ["flow", "head", "airflow", "capacity", "pressure", "efficiency", "temperature", "operating conditions"],
        "Construction": ["material", "casing", "impeller", "coil", "seal", "bearing", "insulation", "coating", "filter"],
        "Electrical": ["voltage", "frequency", "phase", "motor", "protection", "starting", "vfd"],
        "Controls and BMS": ["interface", "monitoring", "feedback", "fault", "alarm", "sequence", "protocol", "bms"],
        "Testing": ["factory test", "site test", "performance test", "inspection", "commissioning"],
        "Installation": ["mounting", "vibration", "support", "clearance", "accessories", "installation"],
        "Documentation": ["submittal", "certificate", "test report", "manual", "warranty", "drawing"]}
    def unit(dimension, factor, canonical, kinds, basis, context=None):
        return dict(dimension=dimension, factor=factor, canonical=canonical, kinds=kinds, basis=basis, context=context)
    units = {}
    for names, definition in [
        (["m3/s"], unit("volume_flow", "1", "m3/s", ["volume_flow"], "SI")),
        (["m3/h", "m\u00b3/h"], unit("volume_flow", "0.0002777777777777777777777777777777777777778", "m3/s", ["volume_flow"], "1 hour = 3600 seconds")),
        (["l/s"], unit("volume_flow", "0.001", "m3/s", ["volume_flow"], "1 litre = 0.001 cubic metre")),
        (["cfm"], unit("volume_flow", "0.0004719474432", "m3/s", ["volume_flow"], "international foot = 0.3048 metre")),
        (["w"], unit("power", "1", "W", ["active_power", "cooling_power", "heating_power"], "SI")),
        (["kw"], unit("power", "1000", "W", ["active_power", "cooling_power", "heating_power"], "SI prefix")),
        (["tr"], unit("power", "3516.852842066666666666666666666666666667", "W", ["cooling_power"], "12000 BTU_IT/hour; rounded decimal factor")),
        (["va"], unit("apparent_power", "1", "VA", ["apparent_power"], "apparent power, no power-factor conversion")),
        (["kva"], unit("apparent_power", "1000", "VA", ["apparent_power"], "SI prefix")),
        (["pa"], unit("pressure", "1", "Pa", ["pressure"], "SI")),
        (["kpa"], unit("pressure", "1000", "Pa", ["pressure"], "SI prefix")),
        (["bar"], unit("pressure", "100000", "Pa", ["pressure"], "1 bar = 100000 Pa")),
        (["in.w.g."], unit("pressure", "249.08891", "Pa", ["pressure"], "conventional inch water at 4 C", "conventional_4C")),
        (["m"], unit("length", "1", "m", ["length"], "SI")),
        (["mm"], unit("length", "0.001", "m", ["length"], "SI prefix")),
        (["v"], unit("voltage", "1", "V", ["voltage"], "SI")),
        (["a"], unit("current", "1", "A", ["current"], "SI")),
        (["hz"], unit("frequency", "1", "Hz", ["frequency"], "SI"))]:
        for name in names:
            units[name] = definition
    return {"schema_version": "mep-technical-review/1", "topics": topics,
        "parameter_aliases": {"rated_voltage": "voltage", "rated_current": "current", "flow_rate": "flow"},
        "parameter_kinds": {"flow": "volume_flow", "airflow": "volume_flow", "head": "length", "pressure": "pressure", "esp": "pressure",
                            "motor_power": "active_power", "rated_power": "active_power", "cooling_capacity": "cooling_power",
                            "heating_capacity": "heating_power", "apparent_power": "apparent_power", "voltage": "voltage", "current": "current",
                            "frequency": "frequency", "phase": "dimensionless", "quantity": "discrete_count"},
        "units": units, "unit_contexts": {}, "tolerances": {}, "text_aliases": {}, "text_conflict_rules": [],
        "discipline_aliases": {}, "system_aliases": {}, "equipment_aliases": {},
        "section_mappings": [], "parameter_patterns": [], "applicability_rules": [], "precedence_rules": [], "quantity_rules": [],
        "coverage_rules": [], "coverage_categories": COVERAGE,
        "status_labels": {}, "report": {"title": "MEP Technical Document Review"},
        "max_source_bytes": 100000000, "max_zip_bytes": 500000000, "max_records": 100000,
        "max_candidates_per_equipment": 5000, "max_comparisons": 100000, "max_text_match": 100000,
        "equipment_config": None}


def configuration(path=None):
    result = defaults()
    supplied = read_json(path) if path else {}
    if not isinstance(supplied, dict) or set(supplied) - set(result):
        raise ValueError("Unknown technical-review configuration keys")
    for name, value in supplied.items():
        result[name] = {**result[name], **value} if isinstance(result[name], dict) and isinstance(value, dict) else value
    if result["schema_version"] != "mep-technical-review/1" or result["coverage_categories"] != COVERAGE:
        raise ValueError("Unsupported schema or replacement of mandatory coverage categories")
    for name in ("max_source_bytes", "max_zip_bytes", "max_records", "max_candidates_per_equipment", "max_comparisons", "max_text_match"):
        if type(result[name]) is not int or result[name] < 1:
            raise ValueError(f"{name} must be positive")
    ids = []
    for rule in result["applicability_rules"]:
        ids.append(rule["id"])
        if rule.get("level") not in ("project", "discipline", "system", "equipment_category", "equipment_type", "equipment_instance") or not rule.get("basis"):
            raise ValueError("Applicability rules need a supported level and actual scope basis")
        if not rule.get("requirement") or not rule.get("equipment"):
            raise ValueError("Applicability rules require explicit requirement and equipment selectors")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate applicability rule IDs")
    for rule in result["parameter_patterns"]:
        compiled = re.compile(rule["pattern"], re.I)
        if not {"value", "unit"} <= compiled.groupindex.keys() or rule.get("operator") not in ("eq", "min", "max", "range", "contains"):
            raise ValueError("Parameter pattern requires named value/unit groups and explicit operator")
    for parameter, tolerance in result["tolerances"].items():
        if not tolerance.get("basis") or any(number(tolerance.get(k, "0")) is None or number(tolerance.get(k, "0")) < 0 for k in ("absolute", "relative")):
            raise ValueError(f"Tolerance for {parameter} requires nonnegative values and a documented basis")
    for name, definition in result["units"].items():
        if number(definition.get("factor")) is None or number(definition["factor"]) <= 0 or not definition.get("basis") or not definition.get("kinds"):
            raise ValueError(f"Invalid unit definition {name}")
    for rule in result["quantity_rules"]:
        if not all(rule.get(k) for k in ("scope", "count_basis", "duty_arrangement", "basis")) or rule["count_basis"] not in ("individual_equipment", "pump_set", "package"):
            raise ValueError("Quantity comparisons require explicit scope, count basis, arrangement and authority")
    for rule in result["precedence_rules"]:
        if not all(rule.get(k) for k in ("higher_file_id", "lower_file_id", "basis")):
            raise ValueError("Precedence needs selected file identities and actual authority")
    dump(result)
    return result


def canonical_parameter(value, cfg):
    text = str(value or "").strip().casefold().replace(" ", "_")
    return cfg["parameter_aliases"].get(text, text)


def normalize(parameter, value, unit, cfg, context=None):
    name = canonical_parameter(parameter, cfg)
    result = {"parameter": name, "original_value": value, "original_unit": unit, "quantity_kind": cfg["parameter_kinds"].get(name),
              "value": None, "unit": None, "dimension": None, "conversion": None, "status": "unresolved"}
    numeric = number(value)
    if numeric is None and unit is None and isinstance(value, str):
        inline = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d].*?)\s*", value)
        if inline and inline.group(2).casefold() in cfg["units"]:
            numeric, unit = number(inline.group(1)), inline.group(2)
    if numeric is None:
        if result["quantity_kind"] is None and isinstance(value, str) and not value.startswith("="):
            result.update(value=cfg["text_aliases"].get(name, {}).get(value, value), status="text")
        return result
    definition = cfg["units"].get(str(unit or "").strip().casefold())
    if result["quantity_kind"] in ("dimensionless", "discrete_count") and unit in (None, "", "1"):
        result.update(value=str(numeric), unit="1", dimension=result["quantity_kind"], status="numeric", conversion={"factor": "1", "basis": "explicit configured dimensionless parameter"})
    elif definition and result["quantity_kind"] in definition["kinds"]:
        required = definition.get("context")
        provided = context or cfg["unit_contexts"].get(str(unit).strip().casefold())
        if required and required != provided:
            result["status"] = "unit_context_unresolved"
            return result
        with localcontext() as arithmetic:
            arithmetic.prec = 40
            converted = str(numeric * Decimal(str(definition["factor"])))
        result.update(value=converted, unit=definition["canonical"], dimension=definition["dimension"], status="numeric", conversion=definition)
    else:
        result["status"] = "unit_or_quantity_kind_unresolved"
    return result


def classify(text, cfg):
    result = []
    for category, phrases in cfg["topics"].items():
        for phrase in phrases:
            match = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I)
            if match:
                result.append({"category": category, "topic": phrase, "literal": match.group(), "span": list(match.span())})
    return result or [{"category": "Unclassified", "topic": None, "literal": None, "span": None}]


def interpreted_patterns(text, cfg):
    interpretations = []
    for rule in cfg["parameter_patterns"]:
        for match in re.finditer(rule["pattern"], text[:cfg["max_text_match"]], re.I):
            groups = match.groupdict()
            interpretations.append({"parameter": canonical_parameter(rule["parameter"], cfg), "operator": rule["operator"],
                "value": groups["value"], "value_end": groups.get("value_end"), "unit": groups["unit"],
                "pattern_id": rule["id"], "literal": match.group(), "span": list(match.span()),
                "method": "configured_literal_pattern", "verification_status": "unreviewed"})
    return interpretations
