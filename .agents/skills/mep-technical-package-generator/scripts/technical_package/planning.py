"""Conservative grouping/readiness using existing decisions, never new technical matching."""
from collections import defaultdict
import json

from .common import dump, key, numeric


def approved_parameters(target, record, cfg):
    found = defaultdict(list)
    for occurrence in target["occurrences"]:
        for parameter in occurrence["parameters"]:
            found[parameter["name"]].append({"original_value": parameter.get("value"), "original_unit": parameter.get("unit"),
                "approved": parameter.get("verification_status") == "approved", "normalized_value": parameter.get("normalized_value"),
                "normalized_unit": parameter.get("normalized_unit"), "normalization_status": parameter.get("normalization_status"),
                "parameter_id": parameter["id"], "review_id": parameter.get("review_id"), "source": occurrence["source"]})
    applicable_ids = {target["id"]} | set(target["equipment_types"])
    for value in record["approved_values"]:
        if value["is_current"] and value["entity_id"] in applicable_ids:
            accepted, normalized = value["payload"]["accepted"], value["payload"]["normalized"]
            found[normalized["parameter"]].append({"original_value": accepted["value"], "original_unit": accepted.get("unit"),
                "approved": True, "normalized_value": normalized.get("value") if normalized.get("status") == "numeric" else None,
                "normalized_unit": normalized.get("unit"), "normalization_status": normalized.get("status"),
                "approved_value_id": value["id"], "review_id": value["review_id"], "source": {"parameter_id": value["parameter_id"], "requirement_id": value["requirement_id"], "evidence_review_id": value["review_id"]}})
    return dict(found)


def verified_type(target, types):
    matches = [t for t in types if t["identity_status"] == "confirmed" and set(t["occurrence_ids"]).intersection(target["occurrence_ids"])]
    return matches[0] if len(matches) == 1 else None


def quantities(group, record, upstream, cfg):
    targets = group["targets"]
    instances = [t for t in targets if t["kind"] == "instance" and t["identity_status"] == "confirmed"]
    # Upstream targets already collapse explicitly confirmed repeated representations.
    verified = len({t["id"] for t in instances}) if instances else None
    scopes = {scope for t in targets for scope in t["scopes"]}
    scope = next(iter(scopes)) if len(scopes) == 1 else None
    occurrences = {o["id"]: o for t in targets for o in t["occurrences"]}
    all_occurrences = {o["id"]: o for o in upstream["equipment"]["occurrences"]}
    for match in upstream["equipment"]["matches"]:
        if match["status"] == "confirmed" and match["kind"] == "boq_scope_association" and set(occurrences).intersection((match["left_id"], match["right_id"])):
            for oid in (match["left_id"], match["right_id"]):
                if oid in all_occurrences and all_occurrences[oid]["role"] == "boq":
                    occurrences[oid] = all_occurrences[oid]
    rows, duplicates = {}, []
    for occurrence in occurrences.values():
        if occurrence["role"] not in ("schedule", "boq", "register"):
            continue
        source = occurrence["source"]
        locator = (source["file_id"], source.get("sheet"), source.get("row"), source.get("pdf_page"), source.get("table_id"), source.get("json_index"))
        if all(v is None for v in locator[1:]):
            locator += (occurrence["id"],)
        item = {"occurrence_id": occurrence["id"], "role": occurrence["role"], "quantity": occurrence.get("quantity"),
                "unit": occurrence.get("quantity_unit"), "scope": occurrence.get("scope"), "identity_kind": occurrence["identity_kind"],
                "count_basis": occurrence.get("count_basis"), "description": occurrence.get("description"), "item_number": occurrence.get("item_number"),
                "section": occurrence.get("section"), "source": source, "revision_status": occurrence["revision_status"]}
        if locator in rows and any(rows[locator].get(k) != item.get(k) for k in ("quantity", "unit", "scope")):
            duplicates.append({"first": rows[locator], "second": item})
        else:
            rows.setdefault(locator, item)
    buckets = defaultdict(list)
    for item in rows.values():
        buckets[(item["role"], item["source"]["file_id"], item["unit"], item["scope"], item["count_basis"])].append(item)
    totals = []
    for (role, file_id, unit, source_scope, count_basis), items in buckets.items():
        values = [numeric(r["quantity"]) for r in items]
        valid = str(unit or "").casefold() in cfg["count_units"] and all(v is not None and v >= 0 for v in values)
        totals.append({"role": role, "file_id": file_id, "original_unit": unit, "scope": source_scope, "count_basis": count_basis,
                       "quantity": str(sum(values)) if valid else None, "rows": items, "physical_equivalence_established": count_basis == "individual_equipment"})
    decisions = []
    ids = {t["id"] for t in targets}
    for value in record["approved_values"]:
        if not value["is_current"]:
            continue
        accepted, normalized = value["payload"]["accepted"], value["payload"]["normalized"]
        declared_ids = set(accepted.get("equipment_ids", []))
        if normalized["parameter"] in cfg["quantity_parameters"] and accepted.get("count_basis") == "individual_equipment" and scope and accepted.get("scope") == scope and (declared_ids == ids or len(ids) == 1 and value["entity_id"] in ids):
            amount = numeric(normalized.get("value"))
            if normalized.get("status") == "numeric" and normalized.get("quantity_kind") == "discrete_count" and amount is not None and amount >= 0 and amount == amount.to_integral_value():
                decisions.append({"quantity": str(amount), "approved_value_id": value["id"], "review_id": value["review_id"], "source_scope": accepted})
    decision_values = {numeric(d["quantity"]) for d in decisions}
    comparable = [t for t in totals if scope and t["scope"] == scope and t["physical_equivalence_established"] and t["quantity"] is not None and all(r["revision_status"] == "applicable" for r in t["rows"])]
    schedule = [t for t in comparable if t["role"] in ("schedule", "register")]
    boq = [t for t in comparable if t["role"] == "boq"]
    consistent = verified is not None and len(instances) == len(targets) and scope and schedule and boq and all(numeric(t["quantity"]) == verified for t in comparable) and not duplicates
    final_quantity = next(iter(decision_values)) if len(decision_values) == 1 else numeric(verified) if consistent else None
    status = "APPROVED_DECISION" if len(decision_values) == 1 else "CONSISTENT_COMPARABLE_EVIDENCE" if consistent else "REQUIRES_REVIEW"
    if len(decision_values) > 1:
        status, final_quantity = "CONFLICTING_APPROVED_QUANTITIES", None
    return {"verified_instance_quantity": verified, "schedule_quantities": [t for t in totals if t["role"] in ("schedule", "register")],
            "boq_quantities": [t for t in totals if t["role"] == "boq"], "final_quantity": str(final_quantity) if final_quantity is not None else None,
            "quantity_reconciliation_status": status, "scope": scope, "decisions": decisions, "duplicate_row_conflicts": duplicates,
            "repeated_drawing_occurrences_not_counted": True}


def plans(repo, record, cfg, categories=None):
    upstream = repo.upstream()
    types = [t for t in record["targets"] if t["kind"] == "type"]
    instances = [t for t in record["targets"] if t["kind"] == "instance"]
    selected_categories = set(categories or [])
    primary = instances + [t for t in record["targets"] if t["kind"] != "instance" and not any(set(t["occurrence_ids"]).intersection(i["occurrence_ids"]) for i in instances)
        and not (t["kind"] == "group" and all(o["role"] == "boq" for o in t["occurrences"]) and any(set(t["categories"]).intersection(i["categories"]) for i in instances))]
    grouped = {}
    for target in primary:
        values = target["categories"]
        category = cfg["category_aliases"].get(values[0], values[0]) if len(values) == 1 else "UNCLASSIFIED"
        if selected_categories and category not in selected_categories:
            continue
        verified = verified_type(target, types) if target["kind"] == "instance" else target if target["kind"] == "type" and target["identity_status"] == "confirmed" else None
        parameters = approved_parameters(target, record, cfg)
        requirement_signature = sorted((l["requirement_id"], l["status"]) for l in record["applicability"] if l["entity_id"] == target["id"])
        approved_signature = {name: sorted({dump([v["normalized_value"] if v["normalized_value"] is not None else v["original_value"], v["normalized_unit"] or v["original_unit"]]) for v in observations if v["approved"]}) for name, observations in parameters.items()}
        fields = {"category": category, "type": verified["id"] if verified else "UNVERIFIED:" + target["id"]}
        for name, plural in (("discipline", "disciplines"), ("system", "systems"), ("building", "buildings"), ("floor", "floors"), ("scope", "scopes")):
            fields[name] = target[plural][0] if len(target[plural]) == 1 else None
        if fields["discipline"] is not None:
            fields["discipline"] = cfg["discipline_aliases"].get(fields["discipline"], fields["discipline"])
        grouping = {name: fields[name] for name in cfg["group_by"]}
        group_id = key(grouping, requirement_signature, approved_signature)
        group = grouped.setdefault(group_id, {"group_id": group_id, **fields, "verified_type_id": verified["id"] if verified else None,
            "targets": [], "parameters": {}, "requirement_signature": requirement_signature, "grouping_evidence": "Existing verified type membership plus identical reviewed parameter/requirement signatures; otherwise separate groups"})
        group["targets"].append(target)
        group["parameters"][target["id"]] = parameters
    result = []
    for group in grouped.values():
        group["quantity"] = quantities(group, record, upstream, cfg)
        group["readiness"] = readiness(group, record, cfg)
        result.append(group)
    return sorted(result, key=lambda g: (g["category"], str(g["system"]), g["group_id"]))


def readiness(group, record, cfg):
    reasons = []
    ids = {t["id"] for t in group["targets"]}
    if group["verified_type_id"]:
        ids.add(group["verified_type_id"])
    links = [l for l in record["applicability"] if l["entity_id"] in ids]
    req_ids = {l["requirement_id"] for l in links if l["status"] != "not_applicable"}
    requirements = [r for r in record["requirements"] if r["id"] in req_ids]
    current_cases = [c for c in record["cases"] if c["entity_id"] in ids and c["is_current"] and c["status"] not in ("resolve", "not_applicable")]
    conflict_cases = [c for c in current_cases if "conflict" in c["type"] or c["status"] in ("confirmed_conflict", "potential_conflict")]
    if any(t["identity_status"] != "confirmed" for t in group["targets"]):
        reasons.append("Equipment identity is not explicitly verified")
    if not group["verified_type_id"]:
        reasons.append("No single verified technical type; proposed equivalence is not accepted")
    if any(o["revision_status"] != "applicable" for t in group["targets"] for o in t["occurrences"]):
        reasons.append("Equipment evidence has unresolved or superseded document applicability")
    if group["quantity"]["final_quantity"] is None:
        reasons.append("Individual/set/package quantities are not reconciled for an equivalent documented scope")
    associated_boq = {row["occurrence_id"] for total in group["quantity"]["boq_quantities"] for row in total["rows"]}
    if any(t["kind"] == "group" and group["category"] in t["categories"] and any(o["role"] == "boq" and o["id"] not in associated_boq for o in t["occurrences"]) for t in record["targets"]):
        reasons.append("BOQ equipment/package associations remain unverified for this category")
    mandatory = set(cfg["mandatory_parameters"].get(group["category"], [])) | set(cfg["type_requirements"].get(group["category"], []))
    for target in group["targets"]:
        parameters = group["parameters"][target["id"]]
        for name in set(parameters) | mandatory:
            approved = [v for v in parameters.get(name, []) if v["approved"]]
            signatures = {dump([v["normalized_value"] if v["normalized_value"] is not None else v["original_value"], v["normalized_unit"] or v["original_unit"]]) for v in approved}
            if not approved or len(signatures) != 1:
                reasons.append(f"Parameter {name} for equipment {target['id']} lacks one consistent approved value")
    if not requirements:
        reasons.append("No reviewed applicable specification requirement set is available")
    if any(l["status"] not in ("confirmed_applicability", "not_applicable") for l in links):
        reasons.append("Specification applicability or exclusions remain unresolved")
    if any(r["verification_status"] != "approve_requirement" or r["revision_status"] != "applicable" or r["reference_status"] != "source_reference_available" or any(i["verification_status"] not in ("approve_interpretation", "reject_interpretation") for i in r["interpretations"]) for r in requirements):
        reasons.append("Original specification text, references, revisions or normalized interpretations lack current approval")
    if record["comparison_status"] != "current":
        reasons.append("Stored technical review is missing or outdated")
    completeness = {c["entity_id"]: c["all_applicable_requirements_verified_and_approved"] for c in record["completeness"]}
    if any(not completeness.get(identity, False) for identity in ids):
        reasons.append("Required source coverage and technical review are incomplete")
    if current_cases:
        reasons.append("Outstanding engineering review cases must be explicitly resolved")
    if cfg["require_formal_release_decision"]:
        decisions = {r["id"]: r for r in record["decisions"]}
        release = [decisions[i] for i in cfg["formal_release_review_ids"] if i in decisions and decisions[i]["decision"] == "approve_package_release" and set(json.loads(decisions[i]["value_json"] or "{}").get("equipment_ids", [])) == ids]
        if not release:
            reasons.append("No explicit engineering package-release decision exists for this exact scope")
    superseded = bool(requirements) and all(r["revision_status"] == "superseded" for r in requirements)
    status = "SUPERSEDED" if superseded else "BLOCKED_BY_CONFLICTS" if conflict_cases or group["quantity"]["quantity_reconciliation_status"] == "CONFLICTING_APPROVED_QUANTITIES" else "PENDING_ENGINEERING_REVIEW" if reasons and all(t["identity_status"] == "confirmed" for t in group["targets"]) else "DRAFT_INCOMPLETE" if reasons else "READY_FOR_EXPORT"
    return {"status": status, "reasons": sorted(set(reasons)), "open_case_ids": [c["id"] for c in current_cases],
            "rfq_ready_technical_information": status == "READY_FOR_EXPORT", "formally_issued_rfq": False,
            "successful_generation_is_not_approval": True}
