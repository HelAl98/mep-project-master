"""Requirement applicability, evidence comparisons and conservative coverage."""
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
import json
import re

from .common import canonical_parameter, COVERAGE, dump, key, normalize, now, number


def selected(target, selector):
    names = {"ids": [target["id"]] + target["aliases"], "categories": target["categories"], "types": target["equipment_types"],
             "tags": target["normalized_tags"] + target["tags"], "disciplines": target["disciplines"], "systems": target["systems"],
             "buildings": target["buildings"], "floors": target["floors"], "scopes": target["scopes"], "kinds": [target["kind"]]}
    for field, values in selector.items():
        if field == "project":
            if values is not True:
                return False
        elif field not in names or not set(map(str, values)).intersection(names[field]):
            return False
    return bool(selector)


def requirement_selected(requirement, selector):
    context = requirement["context"]
    topics = {i["topic"] for i in requirement["classification"]}
    categories = {i["category"] for i in requirement["classification"]}
    for field, expected in selector.items():
        if field == "sections":
            if not any(re.search(pattern, str(context.get("section") or "")) for pattern in expected):
                return False
        elif field == "topics":
            if not set(expected).intersection(topics):
                return False
        elif field == "technical_categories":
            if not set(expected).intersection(categories):
                return False
        elif field == "file_ids":
            if requirement["source"]["file_id"] not in expected:
                return False
        elif field in ("disciplines", "systems", "scopes"):
            if str(context.get(field[:-1])) not in [str(v) for v in expected]:
                return False
        elif field == "text_terms":
            if not any(term.casefold() in requirement["original_text"].casefold() for term in expected):
                return False
        else:
            if field not in {"sections", "topics", "technical_categories", "file_ids", "disciplines", "systems", "scopes", "text_terms"}:
                raise ValueError("Unsupported requirement selector " + field)
    return True


def state(store):
    upstream = store.upstream()
    catalog, imports, active = store.catalog(upstream)
    foundation = store.foundation(upstream, catalog, active)
    return {"upstream": upstream, "catalog": catalog, "imports": imports, "active": active, "foundation": foundation,
            "targets": store.targets(upstream)}


def requirement_links(store, current):
    result = []
    for row in store.rows("tr_links"):
        if row["basis_hash"] != current["foundation"]:
            continue
        row = {**row, "evidence": json.loads(row["evidence_json"])}
        default = "unresolved_applicability" if row["evidence"].get("proposed_exclusion") else "candidate_applicability"
        decision, event = store.event_status("technical_applicability", row["id"], row["basis_hash"], default)
        row["status"] = {"confirm_applicability": "confirmed_applicability", "reject_applicability": "not_applicable",
                         "request_clarification": "unresolved_applicability"}.get(decision, decision)
        row["review_id"] = event
        result.append(row)
    return result


def map_requirements(store):
    current = state(store)
    run_id = key(store.project, "mapping", current["foundation"])
    old = store.conn.execute("SELECT manifest_json FROM tr_mapping_runs WHERE id=?", (run_id,)).fetchone()
    if old:
        return {"mapping_run": run_id, "unchanged": True, **json.loads(old[0])}
    available = {r["id"] for r in current["catalog"]}
    count, truncated = 0, []
    with store.transaction():
        for target in current["targets"]:
            rules = [r for r in store.cfg["applicability_rules"] if selected(target, r["equipment"])]
            # Exact tag evidence is one route, not a restriction on topic/section-wide retrieval.
            direct = [{"id": "literal-tag", "level": "equipment_instance", "basis": "literal source equipment reference",
                       "equipment": {"ids": [target["id"]]}, "requirement": {"text_terms": target["normalized_tags"] + target["tags"]}}] if target["normalized_tags"] or target["tags"] else []
            used = set()
            for rule in direct + rules:
                selector = rule["requirement"]
                terms = selector.get("text_terms", []) + selector.get("topics", [])
                if terms:
                    query = " OR ".join('"' + str(t).replace('"', '""') + '"' for t in terms)
                    ids = [r[0] for r in store.conn.execute("SELECT requirement_id FROM tr_fts WHERE tr_fts MATCH ? AND project_id=?", (query, store.project)) if r[0] in available]
                else:
                    ids = [r["id"] for r in current["catalog"]]
                remaining = store.cfg["max_candidates_per_equipment"] - len(used)
                new_ids = sorted(set(ids) - used)
                if len(new_ids) > remaining:
                    truncated.append(target["id"])
                    new_ids = new_ids[:max(0, remaining)]
                used.update(new_ids)
                requirements = store.requirements(current["upstream"], ids=set(new_ids) | (set(ids) & used))[0]
                for requirement in requirements:
                    if requirement["revision_status"] == "superseded" or not requirement_selected(requirement, selector):
                        continue
                    evidence = {"rule_id": rule["id"], "scope_basis": rule["basis"], "equipment_selector": rule["equipment"],
                                "requirement_selector": selector, "source": requirement["source"], "entity_sources": target["occurrence_ids"],
                                "proposed_exclusion": bool(rule.get("exclude")), "no_automatic_approval": True}
                    if rule.get("exclude_pattern"):
                        match = re.search(rule["exclude_pattern"], requirement["original_text"], re.I)
                        if match:
                            evidence.update(proposed_exclusion=True, exclusion_literal=match.group(), exclusion_span=list(match.span()))
                    identity = key(store.project, target["id"], requirement["id"], current["foundation"], rule["id"], evidence)
                    count += store.insert("tr_links", {"id": identity, "project_id": store.project, "entity_id": target["id"],
                        "requirement_id": requirement["id"], "basis_hash": current["foundation"], "level": rule["level"],
                        "evidence_json": dump(evidence), "created_at": now()})
        manifest = {"links": count, "truncated_equipment_ids": sorted(set(truncated)), "all_applicability_requires_review": True}
        store.insert("tr_mapping_runs", {"id": run_id, "project_id": store.project, "basis_hash": current["foundation"], "manifest_json": dump(manifest), "created_at": now()})
    return {"mapping_run": run_id, "unchanged": False, **manifest}


def document_category(file, cfg):
    metadata = file["metadata"]
    for rule in cfg["coverage_rules"]:
        if all(str(metadata.get(k)) in [str(v) for v in values] for k, values in rule.get("metadata", {}).items()):
            if rule["category"] not in COVERAGE:
                raise ValueError("Unknown coverage category")
            return rule["category"]
    kind = str(metadata.get("document_type") or "").casefold()
    discipline = str(metadata.get("discipline") or "").casefold()
    spec = "specification" in kind
    if "boq" in kind:
        return "boq"
    if "schedule" in kind and not any(w in discipline for w in ("electrical", "bms", "controls")):
        return "equipment_schedules"
    if "bms" in discipline or "control" in discipline:
        return "bms_specifications" if spec else "bms_documentation"
    if any(w in discipline for w in ("electrical", "power", "lighting", "elv", "low current", "fire alarm", "cctv", "communication")):
        return "electrical_specifications" if spec else "electrical_documentation"
    if any(w in discipline for w in ("mechanical", "hvac", "plumbing", "fire fighting", "fire protection", "ventilation")):
        return "mechanical_specifications" if spec else "mechanical_drawings" if "drawing" in kind else None
    return None


def coverage(store, current, links):
    files = current["upstream"]["registry"]["files"]
    eq_imports = [i for i in current["upstream"]["imports"] if i["id"] in current["upstream"]["current_import_ids"]]
    tr_imports = [i for i in current["imports"] if i["id"] in current["active"]]
    req_files = {r["id"]: r["file_id"] for r in current["catalog"]}
    mapping = store.conn.execute("SELECT manifest_json FROM tr_mapping_runs WHERE id=?", (key(store.project, "mapping", current["foundation"]),)).fetchone()
    truncation = json.loads(mapping[0])["truncated_equipment_ids"] if mapping else [t["id"] for t in current["targets"]]
    result = []
    for target in current["targets"]:
        entity_links = [l for l in links if l["entity_id"] == target["id"]]
        direct_files = {o["source"]["file_id"] for o in target["occurrences"]}
        confirmed_files = {req_files[l["requirement_id"]] for l in entity_links if l["status"] == "confirmed_applicability"}
        for category in COVERAGE:
            candidates = [f for f in files if document_category(f, store.cfg) == category]
            processed = []
            for file in candidates:
                imports = [i for i in (tr_imports if category.endswith("specifications") else eq_imports) if i["file_id"] == file["file_id"]]
                equipment_has_evidence = any(o["source"]["file_id"] == file["file_id"] for o in current["upstream"]["equipment"]["occurrences"])
                if any((json.loads(i["coverage_json"]).get("record_count", 0) > 0 if "coverage_json" in i else i["status"] in ("processed", "partial") and equipment_has_evidence) for i in imports):
                    processed.append(file["file_id"])
            scope_id = key(store.project, target["id"], category, current["foundation"])
            evidence = {"candidate_file_ids": [f["file_id"] for f in candidates], "processed_file_ids": processed,
                        "foundation_hash": current["foundation"], "scope_completeness": "unverified"}
            decision, review_id = store.event_status("technical_coverage", scope_id, current["foundation"])
            review = next((r for r in store.legacy.rows("eq_reviews") if r["id"] == review_id), None)
            declaration = json.loads(review["value_json"]) if review else {}
            not_applicable = decision == "not_applicable"
            fully_processed = bool(candidates) and len(processed) == len(candidates)
            matched = bool((direct_files | confirmed_files).intersection(processed))
            approved = decision == "approve_coverage" and isinstance(declaration, dict) and declaration.get("complete_document_scope") is True and fully_processed and matched and target["id"] not in truncation
            result.append({"id": scope_id, "entity_id": target["id"], "category": category, **evidence,
                "available": bool(candidates), "successfully_processed": fully_processed, "matched": matched,
                "reviewed": decision in ("approve_coverage", "reviewed", "not_applicable"), "approved": approved,
                "unavailable": not candidates, "not_applicable": not_applicable, "review_id": review_id,
                "mapping_incomplete": target["id"] in truncation,
                "matched_file_ids": sorted((direct_files | confirmed_files).intersection(f["file_id"] for f in candidates)),
                "unmatched_file_ids": sorted({f["file_id"] for f in candidates} - (direct_files | confirmed_files)),
                "scope_declaration": declaration, "technical_completeness_auto_certified": False,
                "status": "not_applicable" if not_applicable else "approved" if approved else "unavailable" if not candidates else "unprocessed_or_partial_review" if not fully_processed else "pending_review"})
    return result


def observation(occurrence, parameter, cfg, identity):
    raw = parameter.get("original", {})
    normalized = normalize(parameter["name"], parameter.get("value"), parameter.get("unit"), cfg, raw.get("unit_context"))
    return {"kind": "equipment_parameter", "id": parameter["id"], "occurrence_id": occurrence["id"], "parameter": normalized["parameter"],
            "value": parameter.get("value"), "unit": parameter.get("unit"), "normalized": normalized, "operator": "eq",
            "source": occurrence["source"], "revision_status": occurrence["revision_status"], "role": occurrence["role"],
            "discipline": occurrence.get("discipline"), "identity_confirmed": identity, "raw_observation": parameter,
            "interpretation_approved": True, "applicability_confirmed": True}


def requirement_observation(requirement, interpretation, link, cfg):
    normalized = normalize(interpretation.get("parameter"), interpretation.get("value"), interpretation.get("unit"), cfg, interpretation.get("unit_context"))
    if interpretation.get("value_end") is not None:
        normalized["value_end"] = normalize(interpretation.get("parameter"), interpretation["value_end"], interpretation.get("unit"), cfg, interpretation.get("unit_context"))
    return {"kind": "requirement", "id": interpretation.get("id"), "requirement_id": requirement["id"], "link_id": link["id"],
            "parameter": normalized["parameter"], "operator": interpretation.get("operator"), "normalized": normalized,
            "value": interpretation.get("value"), "unit": interpretation.get("unit"), "original_text": requirement["original_text"],
            "source": requirement["source"], "revision_status": requirement["revision_status"], "discipline": requirement["context"].get("discipline"),
            "identity_confirmed": True, "applicability_confirmed": link["status"] == "confirmed_applicability",
            "interpretation_approved": interpretation.get("verification_status") == "approve_interpretation",
            "reference_status": requirement["reference_status"]}


def compare_values(left, right, cfg):
    a, b = left["normalized"], right["normalized"]
    if a["quantity_kind"] != b["quantity_kind"] or left["parameter"] != right["parameter"]:
        return "unresolved_interpretation", {"reason": "different semantic quantity kinds"}
    if a["status"] == b["status"] == "numeric" and a["dimension"] == b["dimension"]:
        def bounds(side):
            value = Decimal(side["normalized"]["value"])
            operator = side.get("operator")
            if operator == "eq":
                return value, value
            if operator == "min":
                return value, Decimal("Infinity")
            if operator == "max":
                return Decimal("-Infinity"), value
            end = side["normalized"].get("value_end", {})
            if operator == "range" and end.get("status") == "numeric":
                upper = Decimal(end["value"])
                if upper >= value:
                    return value, upper
            return None
        aa, bb = bounds(left), bounds(right)
        if aa is None or bb is None:
            return "unresolved_interpretation", {"reason": "unsupported or incomplete numerical constraint"}
        tolerance = cfg["tolerances"].get(left["parameter"], {"absolute": "0", "relative": "0", "basis": "strict comparison; no engineering tolerance supplied"})
        scale = max(abs(Decimal(a["value"])), abs(Decimal(b["value"])))
        allowance = Decimal(str(tolerance.get("absolute", "0"))) + scale * Decimal(str(tolerance.get("relative", "0")))
        disjoint = max(aa[0], bb[0]) - min(aa[1], bb[1]) > allowance
        return ("potential_conflict" if disjoint else "no_difference_detected" if aa == bb else "no_disjoint_constraint_detected"), {"bounds_a": [str(v) for v in aa], "bounds_b": [str(v) for v in bb], "tolerance": tolerance, "allowance": str(allowance)}
    if a["status"] == b["status"] == "text":
        if a["value"] == b["value"]:
            return "no_difference_detected", {"logic": "exact configured text equality"}
        for rule in cfg["text_conflict_rules"]:
            if rule["parameter"] == left["parameter"] and ((re.search(rule["left_pattern"], a["value"], re.I) and re.search(rule["right_pattern"], b["value"], re.I)) or (re.search(rule["left_pattern"], b["value"], re.I) and re.search(rule["right_pattern"], a["value"], re.I))):
                return "potential_conflict", {"logic": "configured textual contradiction", "rule": rule}
        return "unresolved_interpretation", {"reason": "different text is not automatically a contradiction"}
    return "unresolved_interpretation", {"reason": "unit, quantity kind or source value could not be normalized", "a": a["status"], "b": b["status"]}


def review_context(store):
    current = state(store)
    links = requirement_links(store, current)
    required_ids = {l["requirement_id"] for l in links}
    requirements = store.requirements(current["upstream"], ids=required_ids)[0]
    by_requirement = {r["id"]: r for r in requirements}
    cov = coverage(store, current, links)
    basis = key(current["foundation"], [(l["id"], l["status"], l["review_id"]) for l in links],
                [(r["id"], r["verification_status"], r["interpretations"]) for r in requirements], cov)
    run_id = key(store.project, "comparison", basis)
    return current, links, requirements, cov, basis, run_id


def compare(store):
    current, links, requirements, cov, basis, run_id = review_context(store)
    by_requirement = {r["id"]: r for r in requirements}
    if store.conn.execute("SELECT 1 FROM tr_results WHERE run_id=?", (run_id,)).fetchone():
        return {"run_id": run_id, "unchanged": True}
    occurrence_index = {o["id"]: o for o in current["upstream"]["equipment"]["occurrences"]}
    comparisons = cases = 0
    exhausted = False
    with store.transaction():
        store.insert("tr_runs", {"id": run_id, "project_id": store.project, "basis_hash": basis, "foundation_hash": current["foundation"], "config_json": dump(store.cfg), "created_at": now()})
        def case(target, kind, status, evidence, confirmable=False):
            nonlocal cases
            concept = key(target["id"], kind, evidence.get("parameter"), sorted(evidence.get("file_ids", [])))
            identity = key(run_id, target["id"], kind, evidence)
            cases += store.insert("tr_cases", {"id": identity, "project_id": store.project, "run_id": run_id, "entity_id": target["id"],
                "case_key": concept, "type": kind, "initial_status": status, "confirmable": int(confirmable), "evidence_json": dump(evidence), "created_at": now()})
        for target in current["targets"]:
            observations = defaultdict(list)
            own_ids = set(target["occurrence_ids"])
            for oid in list(own_ids) + target["candidate_occurrence_ids"]:
                occurrence = occurrence_index.get(oid)
                if not occurrence:
                    continue
                for parameter in occurrence["parameters"]:
                    obs = observation(occurrence, parameter, store.cfg, target["identity_status"] == "confirmed" and oid in own_ids)
                    if obs["parameter"] == "quantity":
                        continue
                    observations[obs["parameter"]].append(obs)
            for link in [l for l in links if l["entity_id"] == target["id"] and l["status"] != "not_applicable"]:
                requirement = by_requirement[link["requirement_id"]]
                if not requirement["interpretations"]:
                    case(target, "qualitative_requirement_review", "unresolved_interpretation", {"requirement_id": requirement["id"], "link_id": link["id"], "original_text": requirement["original_text"], "source": requirement["source"], "applicability": link["status"]})
                for interpretation in requirement["interpretations"]:
                    if interpretation.get("verification_status") == "reject_interpretation":
                        continue
                    obs = requirement_observation(requirement, interpretation, link, store.cfg)
                    if obs["parameter"] == "quantity":
                        case(target, "quantity_requirement_scope_review", "unresolved_interpretation", {"requirement": obs, "quantity_rules_required": True})
                        continue
                    if not observations.get(obs["parameter"]):
                        case(target, "required_parameter_evidence_missing", "missing_evidence", {"parameter": obs["parameter"], "requirement": obs, "source_completeness_unverified": True})
                    observations[obs["parameter"]].append(obs)
            if target["identity_status"] != "confirmed":
                case(target, "equipment_identity_unresolved", "unresolved_interpretation", {"occurrence_ids": target["occurrence_ids"], "candidate_occurrence_ids": target["candidate_occurrence_ids"]})
            for match in current["upstream"]["equipment"]["matches"]:
                if own_ids.intersection((match["left_id"], match["right_id"])) and match["evidence"].get("identity_conflicts"):
                    case(target, "equipment_identity_conflict", "unresolved_interpretation", {"equipment_match_id": match["id"], "evidence": match["evidence"]})
            for link in [l for l in links if l["entity_id"] == target["id"] and l["status"] != "not_applicable"]:
                requirement = by_requirement[link["requirement_id"]]
                if requirement["reference_status"] == "source_reference_incomplete":
                    case(target, "source_reference_incomplete", "missing_evidence", {"requirement_id": requirement["id"], "source": requirement["source"]})
                if requirement["revision_status"] != "applicable":
                    case(target, "document_applicability_unresolved", "unresolved_interpretation", {"requirement_id": requirement["id"], "source": requirement["source"], "registry_status": requirement["revision_status"]})
            for rule in store.cfg["quantity_rules"]:
                if rule.get("equipment") and not selected(target, rule["equipment"]):
                    continue
                totals = defaultdict(list)
                for occurrence in target["occurrences"]:
                    if occurrence.get("scope") != rule["scope"] or occurrence["role"] not in rule.get("roles", ["drawing", "schedule", "boq"]):
                        continue
                    arrangement = [p.get("value") for p in occurrence["parameters"] if canonical_parameter(p["name"], store.cfg) == "duty_arrangement"]
                    if rule["duty_arrangement"] not in arrangement:
                        continue
                    value = number(occurrence.get("quantity"))
                    if value is not None and value >= 0 and occurrence.get("quantity_unit") in rule.get("equivalent_units", []):
                        totals[occurrence["source"]["file_id"]].append({"value": str(value), "source": occurrence["source"], "occurrence_id": occurrence["id"], "revision_status": occurrence["revision_status"]})
                sums = [{"file_id": fid, "quantity": str(sum(Decimal(o["value"]) for o in observations)), "observations": observations} for fid, observations in totals.items()]
                if len(sums) >= 2 and len({Decimal(s["quantity"]) for s in sums}) > 1:
                    case(target, "quantity_conflict", "potential_conflict", {"parameter": "quantity", "file_ids": sorted(totals), "independent_source_totals": sums, "scope_rule": rule, "no_tag_occurrence_counts_used": True}, target["identity_status"] == "confirmed" and all(o["revision_status"] == "applicable" for values in totals.values() for o in values))
            for parameter, values in observations.items():
                for left, right in combinations(values, 2):
                    if comparisons >= store.cfg["max_comparisons"]:
                        exhausted = True
                        break
                    if left["id"] == right["id"]:
                        continue
                    outcome, logic = compare_values(left, right, store.cfg)
                    files = sorted({left["source"]["file_id"], right["source"]["file_id"]})
                    precedence = [r for r in store.cfg["precedence_rules"] if r["higher_file_id"] in files and r["lower_file_id"] in files]
                    eligible = target["identity_status"] == "confirmed" and all(o["identity_confirmed"] and o["revision_status"] == "applicable" and o["applicability_confirmed"] and o["interpretation_approved"] for o in (left, right))
                    evidence = {"parameter": parameter, "source_a": left, "source_b": right, "logic": logic, "file_ids": files, "precedence_candidates": precedence, "automatic_resolution": False}
                    identity = key(run_id, target["id"], left["id"], right["id"], evidence)
                    comparisons += store.insert("tr_comparisons", {"id": identity, "project_id": store.project, "run_id": run_id, "entity_id": target["id"], "parameter": parameter, "outcome": outcome, "evidence_json": dump(evidence), "created_at": now()})
                    if outcome in ("potential_conflict", "unresolved_interpretation"):
                        kind = "specification_conflict" if left["kind"] == right["kind"] == "requirement" else "technical_value_conflict"
                        if left.get("discipline") and right.get("discipline") and left["discipline"] != right["discipline"]:
                            kind = "cross_discipline_conflict"
                        if left["source"].get("document_id") and left["source"].get("document_id") == right["source"].get("document_id") and left["source"].get("document_revision") != right["source"].get("document_revision"):
                            kind = "revision_conflict"
                        case(target, kind, outcome, evidence, eligible and outcome == "potential_conflict")
                if exhausted:
                    break
            for row in [r for r in cov if r["entity_id"] == target["id"]]:
                store.insert("tr_coverage_scopes", {"id": row["id"], "project_id": store.project, "entity_id": target["id"], "category": row["category"], "foundation_hash": current["foundation"], "evidence_json": dump(row), "created_at": now()})
                if not row["not_applicable"] and (not row["successfully_processed"] or row["mapping_incomplete"]):
                    case(target, "documentation_coverage_incomplete", "unprocessed_source" if row["available"] else "missing_evidence", row)
            if exhausted:
                case(target, "comparison_budget_reached", "unresolved_interpretation", {"limit": store.cfg["max_comparisons"], "review_incomplete": True})
                break
        summary = {"comparisons": comparisons, "cases": cases, "comparison_limit_reached": exhausted, "mapping_present": bool(links),
                   "conclusion": "Findings apply only to processed/reviewed evidence; no claim of conflict-free design or complete requirements coverage."}
        store.conn.execute("INSERT INTO tr_results VALUES(?,?,?,?)", (run_id, dump(summary), dump(cov), now()))
    return {"run_id": run_id, "unchanged": False, **summary}
