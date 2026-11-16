"""Bounded deterministic proposals, review projections, identity clusters and quantities."""
from collections import defaultdict
from itertools import combinations
import json

from .common import compatible_parameters, decimal, dump, key, now, tag


def parameter_index(occurrence):
    grouped = defaultdict(list)
    for parameter in occurrence["parameters"]:
        grouped[parameter["name"]].append(parameter)
    result, ambiguous = {}, []
    for name, values in grouped.items():
        identities = {dump([p.get("normalized_value"), p.get("normalized_unit"), p.get("value"), p.get("unit")]) for p in values}
        if len(identities) == 1:
            result[name] = values[0]
        else:
            ambiguous.append(name)
    return result, ambiguous


def evidence_fields(left, right, cfg):
    equal, conflicts = [], []
    for field in cfg["match_context_fields"] + ["category"]:
        a, b = left.get(field), right.get(field)
        if a not in (None, "") and b not in (None, ""):
            (equal if str(a).strip().casefold() == str(b).strip().casefold() else conflicts).append(field)
    parameters, unknown = compatible_parameters(parameter_index(left)[0], parameter_index(right)[0], cfg)
    return equal, conflicts, parameters, unknown


def run_matches(db, cfg):
    state = db.current()
    if any(json.loads(i["manifest_json"])["config"] != cfg for i in state["imports"] if i["id"] in state["current_import_ids"]):
        raise ValueError("Current imports use a different configuration; reimport unchanged sources with the selected config before matching")
    existing = db.run_for(state, cfg)
    if existing:
        return {"run_id": existing["id"], "unchanged": True}
    basis = db.basis(state, cfg)
    run_id = key(db.project_id, "match-run", basis)
    occurrences = [o for o in state["occurrences"] if o["revision_status"] != "superseded"]
    buckets = defaultdict(list)
    for occurrence in occurrences:
        if occurrence.get("normalized_tag"):
            buckets[("tag", occurrence["normalized_tag"])].append(occurrence)
        if occurrence.get("category") and occurrence.get("scope"):
            buckets[("scope-category", occurrence["scope"], occurrence["category"])].append(occurrence)
    issue_count = match_count = relationship_count = 0
    considered, touched = set(), set()

    def issue(code, kind, evidence):
        nonlocal issue_count
        identity = key(run_id, code, evidence)
        issue_count += db.insert("eq_issues", {"id": identity, "project_id": db.project_id, "run_id": run_id,
            "code": code, "kind": kind, "evidence_json": dump(evidence), "created_at": now()})

    def relationship(left, right, kind, evidence):
        nonlocal relationship_count
        identity = key(run_id, left["id"], right["id"], kind, evidence)
        relationship_count += db.insert("eq_relationships", {"id": identity, "project_id": db.project_id,
            "run_id": run_id, "occurrence_id": left["id"], "target_occurrence_id": right["id"], "kind": kind,
            "evidence_json": dump(evidence), "created_at": now()})

    with db.transaction():
        db.insert("eq_runs", {"id": run_id, "project_id": db.project_id, "basis_hash": basis,
                              "config_json": dump(cfg), "created_at": now()})
        limited = False
        for bucket_key in sorted(buckets, key=str):
            for left, right in combinations(buckets[bucket_key], 2):
                pair = tuple(sorted((left["id"], right["id"])))
                if pair in considered:
                    continue
                if len(considered) >= cfg["max_candidate_pairs"]:
                    limited = True
                    break
                considered.add(pair)
                same_tag = left.get("normalized_tag") is not None and left.get("normalized_tag") == right.get("normalized_tag")
                is_boq = "boq" in (left["role"], right["role"])
                is_spec = "specification" in (left["role"], right["role"])
                if not same_tag and not is_boq and not is_spec:
                    continue
                equal, conflicts, parameter_conflicts, incomparable = evidence_fields(left, right, cfg)
                evidence = {"same_normalized_tag": same_tag, "consistent_fields": equal, "identity_conflicts": conflicts,
                    "parameter_conflicts": parameter_conflicts, "incomparable_parameters": incomparable,
                    "blocking_conflicts": conflicts + parameter_conflicts,
                    "source_ids": [left["source"], right["source"]], "rule": "exact-tag-context-or-explicit-scope-category/1",
                    "confidence": "strong_context" if same_tag and equal and not conflicts and not parameter_conflicts else "incomplete_or_conflicting"}
                if is_spec:
                    relationship(left, right, "candidate_specification_applicability", evidence)
                    continue
                kind = ("boq_scope_association" if is_boq else "type_applicability" if "type" in (left["identity_kind"], right["identity_kind"])
                        else "same_instance_candidate" if left["identity_kind"] == right["identity_kind"] == "instance" else "equipment_reference")
                status = "probable" if same_tag and equal and not conflicts and not parameter_conflicts else "possible"
                identity = key(run_id, pair, kind, evidence)
                match_count += db.insert("eq_matches", {"id": identity, "project_id": db.project_id, "run_id": run_id,
                    "left_id": pair[0], "right_id": pair[1], "kind": kind, "proposed_status": status,
                    "evidence_json": dump(evidence), "created_at": now()})
                touched.update(pair)
                if conflicts:
                    issue("IDENTITY_OR_CLASSIFICATION_CONFLICT", "potential_discrepancy", {"occurrence_ids": pair, **evidence})
                if parameter_conflicts:
                    issue("PARAMETER_CONFLICT", "potential_discrepancy", {"occurrence_ids": pair, **evidence})
                if same_tag:
                    issue("DUPLICATE_TAG_IDENTITY_REVIEW", "potential_discrepancy", {"occurrence_ids": pair, "not_a_physical_count": True})
                if left.get("discipline") and right.get("discipline") and left["discipline"] != right["discipline"]:
                    relationship(left, right, "cross_discipline_reference", {**evidence, "no_wiring_or_controls_inferred": True})
            if limited:
                break
        if limited:
            issue("CANDIDATE_PAIR_LIMIT", "missing_evidence", {"limit": cfg["max_candidate_pairs"], "incomplete": True})

        # Explicit association fields only; matching a tag alone never infers wiring or control logic.
        by_tag = defaultdict(list)
        by_category = defaultdict(list)
        for occurrence in occurrences:
            by_tag[occurrence.get("normalized_tag")].append(occurrence)
            if occurrence.get("category"):
                by_category[occurrence["category"]].append(occurrence)
        relation_budget = cfg["max_candidate_pairs"]
        for occurrence in occurrences:
            for field, relation_type in (("related_tag", "documented_equipment_reference"),
                                         ("controller_tag", "documented_controller_association"),
                                         ("control_panel_tag", "documented_control_panel_association")):
                reference = tag(occurrence.get(field), cfg)
                targets = by_tag.get(reference, []) if reference else []
                for target in targets:
                    if target["id"] == occurrence["id"]:
                        continue
                    if relation_budget <= 0:
                        break
                    relation_budget -= 1
                    specified = occurrence.get("relation_type")
                    allowed_types = {"requires_electrical_supply", "control_panel_association", "bms_reference", "cross_discipline_reference"}
                    relationship(occurrence, target, specified if specified in allowed_types else relation_type,
                                 {"field": field, "literal_reference": occurrence[field], "source": occurrence["source"],
                                  "target_source": target["source"], "proposed_only": True})
            if occurrence["role"] == "specification" and occurrence.get("category"):
                for target in by_category[occurrence["category"]]:
                    if target["role"] == "specification" or relation_budget <= 0:
                        continue
                    # Applicability remains a candidate even for a matching category/discipline.
                    equal, conflicts, unused, unused2 = evidence_fields(occurrence, target, cfg)
                    same_discipline = occurrence.get("discipline") and occurrence.get("discipline") == target.get("discipline")
                    if conflicts or not (same_discipline or any(f in equal for f in ("scope", "system", "building"))):
                        continue
                    relation_budget -= 1
                    relationship(occurrence, target, "candidate_specification_applicability",
                        {"spec_source": occurrence["source"], "equipment_source": target["source"], "consistent_fields": equal,
                         "same_discipline": bool(same_discipline), "not_compliance_verification": True, "applicability_requires_review": True})
        if relation_budget <= 0:
            issue("ASSOCIATION_LIMIT", "missing_evidence", {"incomplete": True, "limit": cfg["max_candidate_pairs"]})

        current_imports = [i for i in state["imports"] if i["id"] in state["current_import_ids"]]
        imported_files = {i["file_id"] for i in current_imports}
        pending = [f["file_id"] for f in state["registry"]["files"] if f["file_id"] not in imported_files]
        for imported in current_imports:
            if imported["status"] != "processed":
                issue("PARTIAL_OR_UNPROCESSED_IMPORT", "unprocessed_source", {"import_id": imported["id"], "issues": json.loads(imported["issues_json"])})
        for file_id in pending:
            issue("REGISTERED_SOURCE_NOT_EQUIPMENT_PROCESSED", "unprocessed_source", {"file_id": file_id})
        for occurrence in occurrences:
            oid = occurrence["id"]
            if not occurrence.get("building") or not occurrence.get("floor"):
                issue("LOCATION_EVIDENCE_INCOMPLETE", "missing_evidence", {"occurrence_ids": [oid], "room_not_inferred": True})
            if not occurrence.get("category"):
                issue("CATEGORY_NOT_IDENTIFIED", "missing_evidence", {"occurrence_ids": [oid]})
            if occurrence.get("classification_conflict"):
                issue("TAG_CLASSIFICATION_CONFLICT", "potential_discrepancy", {"occurrence_ids": [oid], "classifications": occurrence["classification_conflict"]})
            if parameter_index(occurrence)[1]:
                issue("DUPLICATE_PARAMETER_VALUES", "potential_discrepancy", {"occurrence_ids": [oid], "parameters": parameter_index(occurrence)[1]})
            if occurrence.get("category_method") == "inferred" and occurrence.get("discipline"):
                definition = next((c for c in cfg["categories"] if c["id"] == occurrence["category"]), {})
                if definition.get("discipline") and definition["discipline"] != occurrence["discipline"] and occurrence["role"] not in ("electrical", "bms"):
                    issue("CATEGORY_DISCIPLINE_REVIEW", "potential_discrepancy", {"occurrence_ids": [oid], "category": occurrence["category"], "discipline": occurrence["discipline"]})
            if occurrence.get("quantity") is not None and (decimal(occurrence["quantity"]) is None or decimal(occurrence["quantity"]) < 0):
                issue("UNVERIFIED_DECLARED_QUANTITY", "missing_evidence", {"occurrence_ids": [oid], "raw_quantity": occurrence["quantity"]})
            if occurrence.get("quantity") is not None and str(occurrence.get("quantity_unit", "")).strip().casefold() not in cfg["quantity_units"]:
                issue("QUANTITY_UNIT_NOT_VERIFIED_DISCRETE", "missing_evidence", {"occurrence_ids": [oid], "unit": occurrence.get("quantity_unit"), "not_summed_as_physical_items": True})
            if oid not in touched and occurrence["role"] in ("drawing", "schedule", "boq", "electrical", "bms"):
                issue("UNMATCHED_EQUIPMENT_REFERENCE", "missing_evidence", {"occurrence_ids": [oid], "role": occurrence["role"]})
            if occurrence["role"] in ("schedule", "drawing"):
                counterpart = "drawing" if occurrence["role"] == "schedule" else "schedule"
                peers = [p for p in by_tag.get(occurrence.get("normalized_tag"), []) if p["role"] == counterpart and not evidence_fields(occurrence, p, cfg)[1]]
                if not peers:
                    eligible = [i for i in current_imports if i["role"] == counterpart and i["status"] == "processed"]
                    issue("NO_CORRESPONDING_" + counterpart.upper() + "_EVIDENCE", "missing_evidence",
                          {"occurrence_ids": [oid], "successfully_processed_counterpart_imports": [i["id"] for i in eligible],
                           "unprocessed_registered_files": pending, "absence_of_equipment_not_established": True})
        # Counts remain separated by exact supplied scope and source file, never summed across drawings/schedules.
        for group in quantity_groups(occurrences, cfg):
            values = {decimal(row["quantity"]) for row in group["source_quantities"] if row["quantity"] is not None and row["count_kind"] != "tag_hypotheses"}
            hypotheses = group["drawing_tag_hypotheses"]
            if group["scope"] and (len(values) > 1 or (hypotheses is not None and values and decimal(hypotheses) not in values)):
                issue("POTENTIAL_QUANTITY_DISCREPANCY", "potential_discrepancy", group)
        counters = {"occurrences": len(occurrences), "candidate_pairs": len(considered), "matches": match_count,
                    "relationships": relationship_count, "issues": issue_count, "all_matches_require_review": True}
        db.conn.execute("INSERT INTO eq_results VALUES(?,?,?,?)", (run_id, "complete", dump(counters), now()))
    return {"run_id": run_id, "unchanged": False, **counters}


def decision_status(row, reviews, kind, basis):
    events = [r for r in reviews if r["target_kind"] == kind and r["target_id"] == row["id"] and r["basis_hash"] == basis]
    if not events:
        return row.get("proposed_status", "open" if kind == "issue" else "proposed"), None
    event = events[-1]
    return {"confirm": "confirmed", "reject": "rejected", "confirm_discrepancy": "confirmed_discrepancy",
            "resolve": "resolved", "not_applicable": "not_applicable", "reopen": "open"}.get(event["decision"], event["decision"]), event["id"]


def snapshot(db, cfg, history=False):
    state = db.current(history=history)
    current_state = db.current() if history else state
    run = db.run_for(current_state, cfg)
    by_id = {o["id"]: o for o in current_state["occurrences"] if o["revision_status"] != "superseded"}
    result = {"schema_version": "mep-equipment-summary/1", "project": state["project"], "generated_at": now(),
              "matching_status": "current" if run else "not_run_or_stale", "occurrences": state["occurrences"],
              "imports": state["imports"], "current_import_ids": state["current_import_ids"], "reviews": state["reviews"],
              "matches": [], "relationships": [], "issues": [], "entities": [], "unmatched": [], "quantities": []}
    for table, field, kind in (("eq_matches", "matches", "match"), ("eq_relationships", "relationships", "relationship"), ("eq_issues", "issues", "issue")):
        for row in db.rows(table):
            is_current = bool(run and row["run_id"] == run["id"])
            if not is_current and not history:
                continue
            row = {**row, "evidence": json.loads(row["evidence_json"]), "is_current": is_current}
            if is_current:
                row["status"], row["review_id"] = decision_status(row, state["reviews"], kind, run["basis_hash"])
            else:
                row["status"] = "invalidated"
            result[field].append(row)
    memberships = defaultdict(list)
    for link in db.rows("eq_entity_sources"):
        memberships[link["entity_id"]].append(link["occurrence_id"])
    for row in db.rows("eq_entities"):
        sources = memberships[row["id"]]
        current = bool(sources and all(s in by_id for s in sources))
        if not current and not history:
            continue
        row = {**row, "basis": json.loads(row["basis_json"]), "occurrence_ids": sources, "status": "candidate" if current else "invalidated"}
        if current:
            try:
                fingerprint = db.target_basis("entity", row["id"], current_state, cfg)
            except ValueError:
                row["status"] = "invalidated"
                result["entities"].append(row)
                continue
            events = [r for r in state["reviews"] if r["target_kind"] == "entity" and r["target_id"] == row["id"] and r["basis_hash"] == fingerprint]
            if events:
                row["status"] = "rejected" if events[-1]["decision"] == "reject" else "confirmed"
                row["review_id"] = events[-1]["id"]
        result["entities"].append(row)
    connected = {identity for m in result["matches"] if m["status"] in ("confirmed", "probable", "possible") for identity in (m["left_id"], m["right_id"])}
    result["unmatched"] = [o["id"] for o in by_id.values() if o["id"] not in connected and o["role"] != "specification"]
    # Only explicit instance confirmations establish physical items. Confirmed same-instance links collapse duplicates.
    parent = {oid: oid for oid in by_id}
    def find(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity
    for match in result["matches"]:
        if match["status"] == "confirmed" and match["kind"] in ("same_instance_candidate", "equipment_reference") and match["left_id"] in parent and match["right_id"] in parent:
            a, b = find(match["left_id"]), find(match["right_id"])
            parent[max(a, b)] = min(a, b)
    clusters = defaultdict(list)
    for oid in by_id:
        clusters[find(oid)].append(oid)
    confirmed_sources = {oid for entity in result["entities"] if entity["kind"] == "instance" and entity["status"] == "confirmed" for oid in entity["occurrence_ids"]}
    result["instance_clusters"] = [{"cluster_id": key(db.project_id, "cluster", sorted(ids)), "occurrence_ids": sorted(ids),
                                    "status": "verified_instance" if confirmed_sources.intersection(ids) else "candidate_only"}
                                   for ids in clusters.values() if any(by_id[oid]["identity_kind"] == "instance" for oid in ids)]
    result["quantities"] = quantity_groups(list(by_id.values()), cfg)
    for group in result["quantities"]:
        matching_ids = {o["id"] for o in by_id.values() if all(o.get(f) == group.get(f) for f in ("discipline", "system", "category", "building", "floor", "scope"))}
        verified = [c for c in result["instance_clusters"] if c["status"] == "verified_instance" and matching_ids.intersection(c["occurrence_ids"])]
        group["verified_unique_instances"] = len(verified)
        group["verified_instance_cluster_ids"] = [c["cluster_id"] for c in verified]
    result["summary"] = {"occurrences": len(by_id), "candidate_instances": len(result["instance_clusters"]),
                         "verified_unique_instances": sum(c["status"] == "verified_instance" for c in result["instance_clusters"]),
                         "matches": len(result["matches"]), "unmatched": len(result["unmatched"]),
                         "issues": len(result["issues"]), "matching_status": result["matching_status"]}
    return result


def quantity_groups(occurrences, cfg):
    groups = defaultdict(list)
    for occurrence in occurrences:
        if occurrence["role"] == "specification":
            continue
        signature = tuple(occurrence.get(f) for f in ("discipline", "system", "category", "building", "floor", "scope"))
        groups[signature].append(occurrence)
    result = []
    for signature, rows in sorted(groups.items(), key=lambda pair: str(pair[0])):
        record = dict(zip(("discipline", "system", "category", "building", "floor", "scope"), signature))
        by_source = defaultdict(list)
        for occurrence in rows:
            by_source[(occurrence["source"]["file_id"], occurrence["role"], occurrence.get("quantity_unit"))].append(occurrence)
        source_quantities = []
        for (file_id, role, unit), source_rows in sorted(by_source.items(), key=lambda pair: str(pair[0])):
            quantities = [decimal(row.get("quantity")) for row in source_rows]
            supported_unit = str(unit).strip().casefold() in cfg["quantity_units"]
            valid = bool(quantities and supported_unit and all(q is not None and q >= 0 for q in quantities))
            source_quantities.append({"file_id": file_id, "role": role, "unit": unit,
                "quantity": str(sum(quantities)) if valid else None, "raw_quantities": [r.get("quantity") for r in source_rows],
                "count_kind": "declared_quantity" if role != "drawing" else "tag_hypotheses",
                "occurrence_ids": [r["id"] for r in source_rows], "scope_verified": False})
        drawing_tags = {r.get("normalized_tag") for r in rows if r["role"] == "drawing" and r.get("normalized_tag")}
        record.update(source_quantities=source_quantities, drawing_tag_hypotheses=len(drawing_tags) if drawing_tags else None,
                      physical_quantity=None, review_required=True)
        result.append(record)
    return result


def propose_groups(db, cfg, by="type"):
    state = db.current()
    buckets = defaultdict(list)
    for occurrence in state["occurrences"]:
        if occurrence["revision_status"] == "superseded" or occurrence["role"] in ("boq", "specification") or not occurrence.get("category"):
            continue
        params, ambiguity = parameter_index(occurrence)
        required = cfg["type_required_by_category"].get(occurrence["category"], cfg["type_required_parameters"])
        missing = [name for name in required if name not in params or params[name].get("value") in (None, "")]
        missing_units = [name for name, p in params.items() if name not in cfg["unitless_parameters"] and decimal(p.get("value")) is not None and p.get("unit") is None and p.get("normalized_unit") is None]
        technical = {name: [p.get("normalized_value") or p.get("value"), p.get("normalized_unit") or p.get("unit")]
                     for name, p in sorted(params.items())}
        group_basis = {"category": occurrence["category"], "discipline": occurrence.get("discipline"), "system": occurrence.get("system")}
        if by == "type":
            group_basis.update(parameters=technical, missing_material_parameters=missing, ambiguous_parameters=ambiguity, missing_numeric_units=missing_units,
                               explicit_type=occurrence.get("equipment_type"), material_configuration_complete=not missing and not ambiguity and bool(params))
            group_basis["material_configuration_complete"] = group_basis["material_configuration_complete"] and not missing_units
        elif by == "location":
            group_basis.update(building=occurrence.get("building"), floor=occurrence.get("floor"))
        elif by != "category":
            raise ValueError("Grouping supports type/category/location")
        buckets[dump(group_basis)].append(occurrence["id"])
    with db.transaction():
        by_id = {o["id"]: o for o in state["occurrences"]}
        ids = [db.entity("type" if by == "type" else "group", {**json.loads(basis), "source_fingerprints": {oid: key(by_id[oid]) for oid in occurrence_ids}}, occurrence_ids)
               for basis, occurrence_ids in sorted(buckets.items())]
    return {"proposed_entities": ids, "grouping": by, "all_require_review": True}
