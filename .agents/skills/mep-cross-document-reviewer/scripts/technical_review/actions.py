"""Human decisions and queryable technical records; shared eq_reviews audit log."""
import json
import uuid
from decimal import Decimal

from .common import canonical_parameter, dump, key, normalize, now
from .engine import document_category, review_context, selected


def snapshot(store, entity_id=None, tag=None, category=None, history=False):
    current, links, requirements, cov, basis, run_id = review_context(store)
    targets = current["targets"]
    if entity_id:
        targets = [t for t in targets if entity_id == t["id"] or entity_id in t["aliases"]]
    if tag:
        normalized = store.ec.tag(tag, current["upstream"]["equipment_config"])
        targets = [t for t in targets if normalized in t["normalized_tags"] or tag in t["tags"]]
    if category:
        category = store.cfg["equipment_aliases"].get(category, category)
        targets = [t for t in targets if category in t["categories"]]
    if (entity_id or tag or category) and not targets:
        raise ValueError("No current equipment target matches the selected ID/tag/category")
    target_ids = {t["id"] for t in targets}
    links = [l for l in links if l["entity_id"] in target_ids]
    req_ids = {l["requirement_id"] for l in links}
    requirements = [r for r in requirements if r["id"] in req_ids]
    cases = []
    for row in store.rows("tr_cases"):
        if row["entity_id"] not in target_ids or (not history and row["run_id"] != run_id):
            continue
        row = {**row, "evidence": json.loads(row["evidence_json"]), "is_current": row["run_id"] == run_id}
        decision, review = store.event_status("technical_case", row["id"], basis, row["initial_status"]) if row["is_current"] else ("invalidated", None)
        row.update(status={"confirm_conflict": "confirmed_conflict", "request_clarification": "clarification_requested"}.get(decision, decision), review_id=review,
                   previous_case_ids=[c["id"] for c in store.rows("tr_cases") if c["case_key"] == row["case_key"] and c["id"] != row["id"]])
        cases.append(row)
    comparisons = [{**r, "evidence": json.loads(r["evidence_json"]), "is_current": r["run_id"] == run_id} for r in store.rows("tr_comparisons") if r["entity_id"] in target_ids and (history or r["run_id"] == run_id)]
    approved_values = []
    for row in store.rows("tr_approved_values"):
        if row["entity_id"] not in target_ids:
            continue
        status, event = store.event_status("technical_value", row["id"], row["basis_hash"])
        is_current = row["basis_hash"] == current["foundation"] and status == "accept_value"
        if is_current or history:
            approved_values.append({**row, "payload": json.loads(row["payload_json"]), "is_current": is_current,
                                    "status": "approved_interpretation" if is_current else "withdrawn_or_invalidated", "current_review_id": event})
    result_row = store.conn.execute("SELECT * FROM tr_results WHERE run_id=?", (run_id,)).fetchone()
    summary = json.loads(result_row["summary_json"]) if result_row else {"conclusion": "Comparison not run or stale; no absence-of-conflict conclusion is available."}
    cov = [r for r in cov if r["entity_id"] in target_ids]
    unclassified = [f["file_id"] for f in current["upstream"]["registry"]["files"] if document_category(f, store.cfg) is None]
    approval_conflicts = []
    for target in targets:
        grouped = {}
        for approved in approved_values:
            if approved["entity_id"] == target["id"] and approved["is_current"]:
                normalized = approved["payload"]["normalized"]
                grouped.setdefault(normalized["parameter"], []).append(approved)
        for parameter, values in grouped.items():
            if len({dump(v["payload"]["normalized"]) for v in values}) > 1:
                approval_conflicts.append({"entity_id": target["id"], "parameter": parameter, "approved_value_ids": [v["id"] for v in values], "status": "unresolved_approved_interpretations"})
    completeness = []
    for target in targets:
        relevant_links = [l for l in links if l["entity_id"] == target["id"] and l["status"] != "not_applicable"]
        applicable_ids = {l["requirement_id"] for l in relevant_links}
        relevant_requirements = [r for r in requirements if r["id"] in applicable_ids]
        coverage_rows = [r for r in cov if r["entity_id"] == target["id"]]
        outstanding = [c for c in cases if c["entity_id"] == target["id"] and c["is_current"] and c["status"] not in ("resolve", "not_applicable")]
        complete = bool(result_row and not unclassified and not any(c["entity_id"] == target["id"] for c in approval_conflicts) and not summary.get("comparison_limit_reached") and target["identity_status"] == "confirmed" and
            current["upstream"]["equipment"]["matching_status"] == "current" and
            len(coverage_rows) == 8 and all(r["approved"] or r["not_applicable"] for r in coverage_rows) and
            all(l["status"] == "confirmed_applicability" for l in relevant_links) and
            all(r["verification_status"] == "approve_requirement" and r["revision_status"] == "applicable" and r["reference_status"] == "source_reference_available" and all(i["verification_status"] in ("approve_interpretation", "reject_interpretation") for i in r["interpretations"]) for r in relevant_requirements) and not outstanding)
        completeness.append({"entity_id": target["id"], "all_applicable_requirements_verified_and_approved": complete,
            "outstanding_case_ids": [c["id"] for c in outstanding], "reviewed_evidence_is_not_complete_design_verification": True})
    decisions = [r for r in store.legacy.rows("eq_reviews") if r["target_kind"].startswith("technical_")]
    for row in cases + cov:
        row["status_label"] = store.cfg["status_labels"].get(row["status"], row["status"])
    return {"schema_version": "mep-technical-record/1", "generated_at": now(), "project": current["upstream"]["project"],
        "foundation_hash": current["foundation"], "comparison_basis": basis, "run_id": run_id,
        "comparison_status": "current" if result_row else "not_run_or_stale", "targets": targets, "requirements": requirements,
        "applicability": links, "comparisons": comparisons, "cases": cases, "coverage": cov, "completeness": completeness,
        "approved_values": approved_values, "decisions": decisions, "decision_sources": store.rows("tr_decision_evidence"),
        "unclassified_registered_file_ids": unclassified, "approved_interpretation_conflicts": approval_conflicts,
        "report_settings": store.cfg["report"], "summary": summary}


def review(store, kind, target, decision, actor, reason, refs, value=None):
    current, links, requirements, cov, basis, run_id = review_context(store)
    all_requirements = store.requirements(current["upstream"])[0]
    references = store.references(refs, current["upstream"], all_requirements)
    foundation = current["foundation"]
    allowed = {"requirement": {"approve_requirement", "reject_requirement", "request_clarification"},
        "interpretation": {"approve_interpretation", "reject_interpretation", "request_clarification"},
        "applicability": {"confirm_applicability", "reject_applicability", "request_clarification"},
        "case": {"confirm_conflict", "resolve", "reopen", "not_applicable", "request_clarification"},
        "coverage": {"reviewed", "approve_coverage", "not_applicable", "reopen"},
        "value": {"withdraw_value"}, "equipment_match": {"confirm", "reject"}}
    if decision not in allowed.get(kind, set()):
        raise ValueError("Unsupported technical target/decision pair")
    if kind == "equipment_match":
        # Delegate identity semantics to the existing matcher; retain supporting references here.
        previous = next((m for m in current["upstream"]["equipment"]["matches"] if m["id"] == target), None)
        if previous is None:
            raise ValueError("No current equipment match target")
        matcher_basis = store.legacy.target_basis("match", target, current["upstream"], current["upstream"]["equipment_config"])
        if decision == "confirm" and previous["evidence"].get("blocking_conflicts"):
            raise ValueError("Resolve the matcher's blocking identity/parameter conflicts first")
        with store.transaction():
            event = store.append_decision("match", target, decision, actor, reason, None, matcher_basis, references, previous)
        return {"review_id": event, "target_id": target, "decision": decision}
    previous = None
    review_basis = foundation
    if kind == "requirement":
        previous = next((r for r in all_requirements if r["id"] == target), None)
        if previous is None:
            raise ValueError("Requirement is historical or outside this project")
        review_basis = key(target, previous["source"])
    elif kind == "interpretation":
        previous = next((i for r in all_requirements for i in r["interpretations"] if i["id"] == target), None)
        if previous is None:
            raise ValueError("Interpretation is not current")
        if decision == "approve_interpretation":
            normalized = normalize(previous["parameter"], previous.get("value"), previous.get("unit"), store.cfg, previous.get("unit_context"))
            operator = previous.get("operator")
            if normalized["status"] not in ("numeric", "text") or operator in ("min", "max", "range") and normalized["status"] != "numeric" or operator == "contains" and normalized["status"] != "text":
                raise ValueError("Interpretation has unresolved units/meaning or an incompatible operator")
            if operator == "range":
                upper = normalize(previous["parameter"], previous.get("value_end"), previous.get("unit"), store.cfg, previous.get("unit_context"))
                if upper["status"] != "numeric" or Decimal(upper["value"]) < Decimal(normalized["value"]):
                    raise ValueError("Range interpretation requires a valid ordered upper bound")
        review_basis = key(target, previous.get("parameter"), previous.get("value"), previous.get("unit"), previous.get("operator"))
    elif kind == "applicability":
        previous = next((l for l in links if l["id"] == target), None)
        if previous is None:
            raise ValueError("Applicability target is stale; regenerate mapping")
        requirement = next(r for r in all_requirements if r["id"] == previous["requirement_id"])
        if decision == "confirm_applicability" and requirement["reference_status"] == "source_reference_incomplete":
            raise ValueError("Complete original source references before confirming applicability")
    elif kind == "case":
        previous = next((c for c in store.rows("tr_cases") if c["id"] == target and c["run_id"] == run_id), None)
        if previous is None:
            raise ValueError("Case is stale/unprocessed; compare current sources first")
        if decision == "confirm_conflict" and not previous["confirmable"]:
            raise ValueError("Equipment identity, source applicability or interpretation remains unresolved; conflict cannot be confirmed")
        review_basis = basis
    elif kind == "coverage":
        previous = next((r for r in cov if r["id"] == target), None)
        if previous is None:
            raise ValueError("Coverage scope is stale")
        if decision == "approve_coverage":
            supporting_files = {r.get("file_id", r.get("source", {}).get("file_id")) for r in references}
            if not isinstance(value, dict) or value.get("complete_document_scope") is not True or not value.get("reviewed_scope"):
                raise ValueError("Coverage approval needs an explicit complete_document_scope and actual reviewed_scope declaration")
            if not previous["successfully_processed"] or not previous["matched"] or previous["mapping_incomplete"] or not set(previous["candidate_file_ids"]) <= supporting_files:
                raise ValueError("Unprocessed/unmatched/truncated sources or missing supporting file references block coverage approval")
    elif kind == "value":
        previous = next((r for r in store.rows("tr_approved_values") if r["id"] == target and r["basis_hash"] == foundation), None)
        if previous is None:
            raise ValueError("Approved value is stale or outside this project")
    with store.transaction():
        if kind == "coverage":
            store.insert("tr_coverage_scopes", {"id": target, "project_id": store.project, "entity_id": previous["entity_id"],
                "category": previous["category"], "foundation_hash": foundation, "evidence_json": dump(previous), "created_at": now()})
        event = store.append_decision("technical_" + kind, target, decision, actor, reason, value, review_basis, references, previous)
    return {"review_id": event, "target_id": target, "decision": decision}


def interpret(store, requirement_id, payload, actor, reason, refs, method="manual"):
    current = store.upstream()
    requirements = store.requirements(current)[0]
    requirement = next((r for r in requirements if r["id"] == requirement_id), None)
    if not requirement or not isinstance(payload, dict) or not payload.get("parameter") or payload.get("operator") not in ("eq", "min", "max", "range", "contains") or "value" not in payload:
        raise ValueError("Current requirement and explicit parameter/operator/value interpretation required")
    if method not in ("manual", "codex_assisted"):
        raise ValueError("Unsupported interpretation method; no external model API is invoked")
    if payload.get("span"):
        start, end = payload["span"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(requirement["original_text"]) or requirement["original_text"][start:end] != payload.get("literal"):
            raise ValueError("Interpretation span/literal does not match original source text")
    elif not payload.get("basis"):
        raise ValueError("An interpretation without a literal span needs an explicit evidence basis")
    references = store.references(refs, current, requirements)
    identity = key(requirement_id, payload, method, uuid.uuid4().hex)
    with store.transaction():
        event = store.append_decision("technical_interpretation", identity, "propose_interpretation", actor, reason, payload,
                                      key(requirement_id, requirement["source"]), references, {"original_text": requirement["original_text"], "source": requirement["source"]})
        store.insert("tr_interpretations", {"id": identity, "project_id": store.project, "requirement_id": requirement_id,
            "payload_json": dump(payload), "method": method, "review_id": event, "created_at": now()})
    return {"interpretation_id": identity, "status": "unreviewed", "source_text_unchanged": True}


def accept_value(store, entity_id, payload, actor, reason, refs):
    current, links, requirements, cov, basis, run_id = review_context(store)
    target = next((t for t in current["targets"] if t["id"] == entity_id), None)
    if not target or target["identity_status"] != "confirmed" or not isinstance(payload, dict) or not payload.get("parameter") or "value" not in payload:
        raise ValueError("A confirmed equipment target and explicit parameter/value interpretation are required")
    parameter_id, requirement_id, interpretation_id = payload.get("parameter_id"), payload.get("requirement_id"), payload.get("interpretation_id")
    source_parameter = next(((o, p) for o in target["occurrences"] for p in o["parameters"] if p["id"] == parameter_id), None)
    if source_parameter:
        occurrence, parameter = source_parameter
        if occurrence["revision_status"] != "applicable" or canonical_parameter(parameter["name"], store.cfg) != canonical_parameter(payload["parameter"], store.cfg):
            raise ValueError("Selected parameter/revision does not support this approved value")
    else:
        requirement = next((r for r in requirements if r["id"] == requirement_id), None)
        interpretation = next((i for i in requirement["interpretations"] if i["id"] == interpretation_id), None) if requirement else None
        if not requirement or requirement["revision_status"] != "applicable" or not interpretation or interpretation["verification_status"] != "approve_interpretation" or not any(l["entity_id"] == entity_id and l["requirement_id"] == requirement_id and l["status"] == "confirmed_applicability" for l in links):
            raise ValueError("Supply a current source parameter or an approved interpretation of a confirmed applicable requirement")
        if canonical_parameter(interpretation["parameter"], store.cfg) != canonical_parameter(payload["parameter"], store.cfg):
            raise ValueError("Approved interpretation and accepted value have different parameter meanings")
    all_requirements = store.requirements(current["upstream"])[0]
    if requirement_id and not any(r["id"] == requirement_id for r in all_requirements):
        raise ValueError("Requirement reference is not current in this project")
    if interpretation_id and not any(i["id"] == interpretation_id for r in all_requirements if r["id"] == requirement_id for i in r["interpretations"]):
        raise ValueError("Interpretation does not belong to the selected current requirement")
    references = store.references(refs, current["upstream"], all_requirements)
    normalized = normalize(payload["parameter"], payload["value"], payload.get("unit"), store.cfg, payload.get("unit_context"))
    if normalized["status"] not in ("numeric", "text"):
        raise ValueError("Approved value needs explicit valid units/quantity kind or a qualitative text interpretation")
    identity = uuid.uuid4().hex
    with store.transaction():
        event = store.append_decision("technical_value", identity, "accept_value", actor, reason, payload, current["foundation"], references,
                                      {"source_parameter": source_parameter, "original_requirement_id": requirement_id})
        store.insert("tr_approved_values", {"id": identity, "project_id": store.project, "entity_id": entity_id,
            "parameter_id": parameter_id if source_parameter else None, "requirement_id": requirement_id,
            "interpretation_id": interpretation_id, "review_id": event, "basis_hash": current["foundation"],
            "payload_json": dump({"accepted": payload, "normalized": normalized}), "created_at": now()})
    return {"approved_value_id": identity, "review_id": event, "original_evidence_unchanged": True}
