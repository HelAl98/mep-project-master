"""User commands; no tests, demo, fixture creation or automatic dependency installs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from .common import HOME, configuration, read, write, key, resolve
from .discovery import discover, workflow
from .engine import run, status, jobs_for, job_fingerprint, validate_config
from .memory import Memory
from .operations import checkpoint, decision, retrieve
from .limited_scope import record_limitation, record_available, eligibility, revalidate_prerequisites
from .evidence import engineering_gate, current_files


def plan(cfg):
    inventory = discover(cfg)
    validate_config(cfg)
    memory = Memory(cfg) if Path(cfg["database"]).is_file() else None
    try:
        stages = []
        for stage in workflow():
            tasks = []
            for job in jobs_for(cfg, stage["id"]):
                row = next(r for r in inventory if r["name"] == job["skill"])
                try:
                    fingerprint = job_fingerprint(cfg, memory, job, inventory) if memory else None
                    error = None
                except (ValueError, KeyError, OSError) as exc:
                    fingerprint, error = None, str(exc)
                tasks.append({**job, "input_fingerprint": fingerprint, "planning_issue": error,
                              "available": row["available"], "read_before_use": str(Path(row["path"]) / "SKILL.md"),
                              "execution": "Codex workflow + checkpoint" if job.get("kind") == "codex" else "allow-listed local CLI"})
            stages.append({**stage, "tasks": tasks, "configuration_required": not tasks and stage["id"] != "09",
                           "coverage": cfg.get("stages", {}).get(stage["id"], {}).get("coverage")})
        return {"project_id": cfg["project_id"], "scope": cfg["scope"], "stages": stages, "skills": inventory,
                "processing_started": False, "mode": cfg["execution_mode"]}
    finally:
        if memory:
            memory.close()


def parser():
    p = argparse.ArgumentParser(description="Coordinate the existing 15 MEP skills using one persistent engineering SQLite database")
    p.add_argument("--config", help="Master project JSON; all relative paths resolve against this file")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("procurement", help="One-request mechanical item preparation; preserves legacy stages")
    c.add_argument("action", choices=("run", "status", "decide", "link", "interpret", "configure", "reasoning", "issue"))
    c.add_argument("--root", help="Original project folder; defaults to current folder for run")
    c.add_argument("--state", help="Optional dedicated project state root outside sources")
    c.add_argument("--category", action="append")
    c.add_argument("--system")
    c.add_argument("--tag", action="append")
    c.add_argument("--item", action="append", help="Exact stored item IDs")
    c.add_argument("--exclude-item", action="append", help="Explicitly exclude these reviewed items from issue; preserve them in draft/history")
    c.add_argument("--field")
    c.add_argument("--source-link")
    c.add_argument("--record")
    c.add_argument("--relation", choices=("candidate", "conditional", "direct", "supported"), default="candidate")
    c.add_argument("--basis")
    c.add_argument("--statement", help="Actual user's exact decision/issue confirmation from chat")
    c.add_argument("--actor", help="Actual attribution; not authenticated identity")
    c.add_argument("--fingerprint", help="Exact reviewed item-scope fingerprint for issue")
    c.add_argument("--request", help="Main-authored mappings/scope options; users need not manage this file")
    c = sub.add_parser("init", help="Create configuration only; never scan/process documents")
    for name in ("project-id", "project-name", "source", "database", "output", "skills-root", "write-config"):
        c.add_argument("--" + name, required=True)
    c.add_argument("--mode", choices=("guided", "automatic"), default="guided")
    for name in ("discover", "plan", "status", "files", "reviews", "readiness"):
        sub.add_parser(name)
    for name in ("start", "run", "resume"):
        c = sub.add_parser(name)
        c.add_argument("--stage", choices=[s["id"] for s in workflow()])
    c = sub.add_parser("matching-scope")
    c.add_argument("--receipt", required=True)
    c = sub.add_parser("source-currency", help="Read-only original source hashes and saved dependency impact")
    c.add_argument("--output", help="New report JSON outside original sources and installed skills")
    c.add_argument("--max-source-mb", type=int, help="Optional per-source hash limit; larger sources are UNVERIFIED")
    c.add_argument("--max-json-files", type=int, default=2000)
    c.add_argument("--max-json-mb", type=int, default=32)
    c = sub.add_parser("evidence", help="P1-02 read-only evidence API; no workflow execution")
    c.add_argument("action", choices=("profile", "list", "observations", "parameters", "schedule-fields", "specifications", "drawings", "context", "findings", "relationships", "provenance", "limitations"))
    c.add_argument("--reference")
    c.add_argument("--family")
    c.add_argument("--role", choices=("boq", "electrical", "bms", "drawing", "schedule"))
    c.add_argument("--section")
    c.add_argument("--applicability")
    c.add_argument("--table", help="Optional explicit supported evidence table for provenance")
    c.add_argument("--history", action="store_true")
    c.add_argument("--include-decisions", action="store_true", help="Opt-in granular assertion history; never overwrites original values")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--offset", type=int, default=0)
    c.add_argument("--currency-snapshot", help="Explicit saved Phase 01 assessment; no source rehash")
    c.add_argument("--output", help="Explicit new JSON file outside source/state/archive")
    c = sub.add_parser("supplier-draft", help="P1-03 draft-only compilation through EvidenceReader; never a workflow stage")
    c.add_argument("--options", required=True, help="mep-supplier-draft-config/1 JSON")
    c.add_argument("--output", required=True, help="New output directory outside source/state/archive/master")
    c.add_argument("--currency-snapshot", help="Explicit saved Phase 01 assessment; not a new hash check")
    c.add_argument("--node-executable", help="Bundled Node executable resolved by workspace dependency loader")
    c.add_argument("--artifact-module-root", help="Bundled node_modules directory")
    c = sub.add_parser("human-review", help="P1-04 granular assertions; never engineering/package approval")
    c.add_argument("action", choices=("pending", "inspect", "history", "prepare", "record", "supersede", "reject", "validity"))
    c.add_argument("--request", help="Human review request JSON; prepare only")
    c.add_argument("--proposal", help="Exact prepared proposal JSON to inspect and record")
    c.add_argument("--reference", help="Evidence/equipment/decision ID or exact label for history")
    c.add_argument("--table", help="Exact supported evidence table for inspect")
    c.add_argument("--decision-type", choices=("identity", "quantity", "specification_applicability", "document_revision"))
    c.add_argument("--family")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--offset", type=int, default=0)
    c.add_argument("--currency-snapshot", help="Explicit Phase 01 snapshot; no source rehash")
    c.add_argument("--output", help="Explicit new JSON file outside source/state/archive")
    c.add_argument("--human-authorized", action="store_true", help="Intent assertion only, not authentication; record still requires direct human terminal confirmation")
    c = sub.add_parser("operation", help="P1-05 exact-scope eligibility and native/reuse adapters; no stage rewriting")
    c.add_argument("action", choices=("list", "requirements", "assess", "plan", "execute", "receipts"))
    c.add_argument("--operation", choices=("A", "B", "C", "D", "E"))
    c.add_argument("--scope", help="mep-operation-scope/1 JSON")
    c.add_argument("--plan", help="Exact saved mep-operation-plan/1 JSON")
    c.add_argument("--authorize-plan", help="Exact inspected plan fingerprint; a preview is not execution authorization")
    c.add_argument("--actor")
    c.add_argument("--reason")
    c.add_argument("--allow-native-processing", action="store_true")
    c.add_argument("--executor-role", choices=("main", "subagent"), default="main")
    c.add_argument("--currency-snapshot", help="Explicit Phase 01 snapshot; native writes also require fresh selected-source bytes")
    c.add_argument("--output", help="Explicit new plan JSON export only; no implicit project writes")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--offset", type=int, default=0)
    c = sub.add_parser("matching-execute")
    c.add_argument("--plan", required=True)
    c = sub.add_parser("equipment-scope")
    c.add_argument("--receipt", required=True)
    c = sub.add_parser("equipment-execute")
    c.add_argument("--plan", required=True)
    c = sub.add_parser("source-limitation")
    c.add_argument("--receipt", required=True)
    c.add_argument("--human-authorized", action="store_true")
    c = sub.add_parser("available-evidence")
    c.add_argument("--receipt", required=True)
    c = sub.add_parser("eligibility")
    c.add_argument("--request", required=True)
    c = sub.add_parser("revalidate-prerequisites")
    c.add_argument("--receipt", required=True)
    c = sub.add_parser("checkpoint")
    c.add_argument("--stage", required=True); c.add_argument("--job", required=True); c.add_argument("--receipt", required=True)
    c = sub.add_parser("decision")
    c.add_argument("--request", required=True)
    c.add_argument("--human-authorized", action="store_true", help="Only after the human explicitly supplies/authorizes this exact disposition")
    c = sub.add_parser("review-equipment")
    c.add_argument("--tag", required=True)
    c = sub.add_parser("search")
    c.add_argument("--query", required=True)
    c = sub.add_parser("packages")
    c.add_argument("--mode", choices=("draft", "approved"), default="draft")
    c.add_argument("--category", action="append")
    c.add_argument("--entity-id")
    c = sub.add_parser("scope")
    c.add_argument("--id", required=True); c.add_argument("--system", required=True)
    c.add_argument("--file-id", action="append", required=True)
    c.add_argument("--entity-id", action="append", default=[])
    c.add_argument("--write-config", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'procurement':
            from . import procurement
            if args.action != 'run' and not args.config:
                raise ValueError('Main must supply the existing config returned by procurement run')
            cfg=procurement.prepare(args.root,config_path=args.config,state=args.state)
            selected={k:v for k,v in {'categories':args.category,'system':args.system,'tags':args.tag}.items() if v}
            if args.action=='run':
                result=procurement.run_procurement(cfg,scope=selected or None,options=read(args.request) if args.request else None)
            elif args.action=='status':
                result=procurement.snapshot(cfg,scope=selected or None,item_ids=args.item)
            elif args.action=='decide':
                if not args.item or len(args.item)!=1 or not args.field:
                    raise ValueError('Field decision needs one exact item and field')
                result=procurement.decide(cfg,args.item[0],args.field,args.source_link,args.statement,args.actor)
            elif args.action=='link':
                if not args.item or len(args.item)!=1 or not args.record or not args.basis:
                    raise ValueError('Association needs exact item, record and evidence basis')
                result=procurement.link_evidence(cfg,args.item[0],args.record,field=args.field,relation=args.relation,basis=args.basis)
            elif args.action=='configure':
                if not args.request:raise ValueError('Main mapping/options request required')
                result=procurement.configure(cfg,read(args.request))
            elif args.action=='interpret':
                if not args.request:raise ValueError('Main bounded interpretation request required')
                request=read(args.request)
                result=procurement.interpret(cfg,request['item_id'],request['record_id'],request['fields'],
                    request['excerpt'],request['basis'])
            elif args.action=='reasoning':
                if not args.request:raise ValueError('Main native-host reasoning/fallback receipt required')
                result=procurement.record_reasoning(cfg,read(args.request))
            else:
                result=procurement.confirm_issue(cfg,args.item,args.fingerprint,args.statement,args.actor,exclude_item_ids=args.exclude_item)
            print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
            return 0
        if args.command=='operation' and args.action in ('list','requirements'):
            from .operation_workflow import operations,requirements
            if args.action=='requirements' and not args.operation:raise ValueError('Requirements needs --operation A..E')
            result={'schema_version':'mep-operation-catalog/1','operations':operations() if args.action=='list' else [requirements(args.operation)],'processing_started':False}
            print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return 0
        if args.command == "init":
            target = Path(args.write_config).resolve()
            cfg = read(HOME / "assets/config/project.example.json")
            cfg.update(project_id=args.project_id, project_name=args.project_name, source_directory=str(Path(args.source).resolve()),
                       database=str(Path(args.database).resolve()), output_directory=str(Path(args.output).resolve()),
                       skills_root=str(Path(args.skills_root).resolve()), execution_mode=args.mode)
            write(target, cfg)
            result = {"config": str(target), "processing_started": False, "next_action": "Review project rules and run start in Guided Mode"}
        else:
            if not args.config:
                raise ValueError("Provide --config before the command")
            if args.command=='operation':
                from .source_currency import load_config
                from .operation_workflow import operation_reader,assess_operation
                from .operation_adapters import execute_operation,operation_receipts
                operation_cfg=load_config(args.config)
                if args.action=='execute':
                    if not args.plan or not args.authorize_plan or not args.actor or not args.reason:
                        raise ValueError('Execution requires exact --plan, --authorize-plan, --actor and --reason')
                    result=execute_operation(operation_cfg,read(args.plan),authorized_plan_fingerprint=args.authorize_plan,
                        actor=args.actor,reason=args.reason,currency_snapshot=args.currency_snapshot,
                        allow_native_processing=args.allow_native_processing,executor_role=args.executor_role)
                elif args.action=='receipts':
                    result=operation_receipts(operation_cfg,operation=args.operation,limit=args.limit,offset=args.offset)
                else:
                    if not args.scope:raise ValueError('Assess/plan requires explicit --scope request JSON')
                    with operation_reader(operation_cfg,args.currency_snapshot) as reader:
                        result=assess_operation(reader,read(args.scope))[0]
                        if args.output:
                            reader.write_json(args.output,result)
                            result={'plan':str(Path(args.output).resolve()),'plan_fingerprint':result['plan_fingerprint'],
                                'eligibility':result['eligibility'],'execution_authorized':False}
                print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return 0
            if args.command == 'human-review':
                from .source_currency import load_config
                from .evidence_reader import EvidenceReader
                from .human_decisions import prepare_decision, prepare_successor, authorize_in_terminal, record_decision
                review_cfg = load_config(args.config)
                if args.action == 'record':
                    if not args.human_authorized or not args.proposal:
                        raise ValueError('Record needs an exact prepared --proposal and explicit --human-authorized intent; a direct human terminal interaction is still required')
                    if Path(args.proposal).stat().st_size > 16 * 1024 * 1024:
                        raise ValueError('Proposal exceeds bounded 16 MiB input limit')
                    proposed = read(args.proposal)
                    authorization = authorize_in_terminal(proposed)
                    result = record_decision(review_cfg, proposed, authorization, currency_snapshot=args.currency_snapshot)
                else:
                    with EvidenceReader(review_cfg, args.currency_snapshot) as reader:
                        reader.bounds(args.limit,args.offset)
                        if args.action == 'pending':
                            result = reader.list_pending_reviews(family=args.family,limit=args.limit,offset=args.offset)
                        elif args.action == 'inspect':
                            if not args.table or not args.reference: raise ValueError('Inspect needs --table and --reference')
                            result = reader.inspect_evidence(args.reference,table=args.table)
                        elif args.action == 'history':
                            result = reader.get_decision_history(args.reference,decision_type=args.decision_type,limit=args.limit,offset=args.offset)
                        elif args.action == 'validity':
                            if not args.reference: raise ValueError('Validity needs --reference DECISION_ID')
                            result = reader.check_decision_validity(args.reference)
                        else:
                            if not args.request: raise ValueError('Prepare/supersede/reject needs an explicit --request JSON')
                            request = read(args.request)
                            if args.action == 'prepare':
                                result = prepare_decision(reader,request)
                            else:
                                if not args.reference: raise ValueError('Supersede/reject needs --reference DECISION_ID')
                                result = prepare_successor(reader,args.reference,
                                    result='Rejected' if args.action=='reject' else request['result'],reviewer=request['reviewer'],
                                    rationale=request['rationale'],assertion=request.get('assertion'))
                        if args.output:
                            saved = reader.write_json(args.output,result)
                            result = {'report':saved,'status':'PROPOSAL_ONLY' if args.action in ('prepare','supersede','reject') else 'READ_ONLY_EXPORT'}
                print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
                return 0
            if args.command == "supplier-draft":
                from .source_currency import load_config
                from .evidence_reader import EvidenceReader
                from .supplier_draft import generate_supplier_drafts
                draft_cfg = load_config(args.config)
                try:
                    draft_reader = EvidenceReader(draft_cfg, args.currency_snapshot)
                except (OSError, ValueError) as snapshot_error:
                    if not args.currency_snapshot:
                        raise
                    draft_reader = EvidenceReader(draft_cfg)
                    draft_reader.snapshot_info = {'status': 'UNAVAILABLE_OR_INCOMPATIBLE_SNAPSHOT',
                        'requested_path': str(Path(args.currency_snapshot).resolve()), 'source_currency': 'UNKNOWN',
                        'dependency_impact': 'UNKNOWN', 'reason': str(snapshot_error), 'live_source_rehash_performed': False}
                with draft_reader:
                    result = generate_supplier_drafts(draft_reader, read(args.options), args.output,
                        node_executable=args.node_executable, artifact_module_root=args.artifact_module_root)
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            if args.command == "evidence":
                from .source_currency import load_config
                from .evidence_reader import EvidenceReader
                with EvidenceReader(load_config(args.config), args.currency_snapshot) as reader:
                    opts = {'limit': args.limit, 'offset': args.offset}
                    reader.bounds(args.limit, args.offset)
                    if args.action not in ('list', 'limitations') and not args.reference:
                        raise ValueError('Provide --reference for this evidence action')
                    if args.action == 'profile':
                        result = reader.get_equipment_profile(args.reference, include_history=args.history, include_decisions=args.include_decisions, **opts)
                    elif args.action == 'list':
                        result = reader.list_equipment(args.family, include_history=args.history, **opts)
                    elif args.action == 'limitations':
                        result = reader.list_source_limitations(**opts)
                    elif args.action == 'provenance':
                        result = reader.get_provenance(args.reference, table=args.table)
                    else:
                        method = {'observations': reader.get_observations, 'parameters': reader.get_parameters,
                                  'schedule-fields': reader.get_schedule_fields, 'specifications': reader.get_specifications,
                                  'drawings': reader.get_drawing_references, 'context': reader.get_context,
                                  'findings': reader.get_findings, 'relationships': reader.get_relationships}[args.action]
                        extra = {'role': args.role} if args.action == 'context' else (
                            {'section': args.section, 'applicability': args.applicability} if args.action == 'specifications' else {})
                        result = reader.envelope(args.action, reference=args.reference, include_history=args.history,
                            result=method(args.reference, include_history=args.history, **opts, **extra))
                    if args.output:
                        saved = reader.write_json(args.output, result)
                        result = {'report': saved, 'schema_version': result['schema_version'], 'database_access': 'read_only'}
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            if args.command == "source-currency":
                from .source_currency import assess, load_config
                currency_cfg = load_config(args.config)
                if args.max_json_files < 1 or args.max_json_mb < 1 or (args.max_source_mb is not None and args.max_source_mb < 1):
                    raise ValueError("Currency assessment limits must be positive")
                result = assess(currency_cfg, max_source_bytes=args.max_source_mb * 1024 * 1024 if args.max_source_mb else None,
                                max_json_files=args.max_json_files, max_json_bytes=args.max_json_mb * 1024 * 1024)
                if args.output:
                    output = Path(args.output).resolve()
                    if output.is_relative_to(Path(currency_cfg['source_directory'])) or output.is_relative_to(HOME) or output == Path(currency_cfg['database']):
                        raise ValueError("Currency report must be outside original sources, installed master and database")
                    write(output, result)
                    result = {'report': str(output), 'summary': result['summary'], 'database_access': 'read_only', 'engineering_approval_created': False}
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            cfg = configuration(args.config)
            command = args.command
            if command == "discover":
                result = {"skills": discover(cfg)}
            elif command == "plan":
                result = plan(cfg)
            elif command == "status":
                result = status(cfg)
            elif command in ("start", "run", "resume"):
                result = run(cfg, args.stage)
            elif command == "matching-scope":
                from .matching_scope import record
                result = record(cfg, args.receipt)
            elif command == "matching-execute":
                from .matching_scope import execute
                result = execute(cfg, args.plan)
            elif command == "equipment-scope":
                from .equipment_scope import record
                result = record(cfg, args.receipt)
            elif command == "equipment-execute":
                from .equipment_scope import execute
                result = execute(cfg, args.plan)
            elif command == "source-limitation":
                result = record_limitation(cfg, args.receipt, args.human_authorized)
            elif command == "available-evidence":
                result = record_available(cfg, args.receipt)
            elif command == "eligibility":
                result = eligibility(cfg, args.request)
            elif command == "revalidate-prerequisites":
                result = revalidate_prerequisites(cfg, args.receipt)
            elif command == "checkpoint":
                result = checkpoint(cfg, args.stage, args.job, args.receipt)
            elif command == "decision":
                result = decision(cfg, args.request, args.human_authorized)
            elif command == "review-equipment":
                result = retrieve(cfg, tag=args.tag)
            elif command == "search":
                result = retrieve(cfg, query=args.query)
            elif command == "files":
                memory = Memory(cfg)
                try:
                    result = {"files": current_files(memory)}
                finally:
                    memory.close()
            elif command in ("reviews", "readiness"):
                result = engineering_gate(cfg)
                if command == "reviews":
                    # Gate reasons show actual outstanding approval conditions, no fictitious approval action.
                    result["instructions"] = "Read upstream current conflicts/coverage/source records; record actual decisions through decision"
            elif command == "packages":
                if not args.category and not args.entity_id:
                    raise ValueError("Select actual categories or an equipment entity ID")
                options = {}
                if args.category:
                    options["category"] = args.category
                if args.entity_id:
                    options["entity-id"] = args.entity_id
                cfg["package_mode"] = args.mode
                cfg["explicit_package_request"] = True
                scope_files = cfg["stages"].get("10", {}).get("coverage", {}).get("included_file_ids", []) if cfg["stages"].get("10", {}).get("coverage") else []
                cfg["stages"].setdefault("10", {})["jobs"] = [{"id": "packages-" + key([args.mode, options])[:16],
                    "skill": "mep-technical-package-generator", "command": args.mode,
                    "options": options, "source_file_ids": scope_files}]
                result = run(cfg, "10")
            elif command == "scope":
                memory = Memory(cfg)
                try:
                    known = {r["file_id"] for r in current_files(memory)}
                    if set(args.file_id) - known:
                        raise ValueError("Unknown registered file ID in system scope")
                finally:
                    memory.close()
                cfg["scope"] = {"id": args.id, "system": args.system, "file_ids": args.file_id,
                                "entity_ids": args.entity_id, "categories": []}
                cfg.pop("config_path", None)
                # Reset coverage declarations/jobs: source IDs from another scope are never inherited as complete.
                for identity, spec in cfg["stages"].items():
                    if identity != "01":
                        spec["jobs"] = []; spec["coverage"] = None
                write(Path(args.write_config).resolve(), cfg)
                result = {"scope_config": str(Path(args.write_config).resolve()), "processing_started": False,
                          "next_action": "Configure selected source tasks and shared requirements; CLI global match/map restrictions are enforced"}
            else:
                raise ValueError("Unknown command")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if isinstance(result, dict) and any(r.get("status") in ("BLOCKED", "FAILED") for r in result.get("results", [])):
            return 1
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "message": "Inspect lock/process, persisted events and partial outputs before resume"}), file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
