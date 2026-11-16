"""Local CLI. No test/demo command, external service or automatic model invocation."""
import argparse
import json
import sys

from .actions import accept_value, interpret, review, snapshot
from .common import configuration
from .engine import compare, coverage, map_requirements, requirement_links, state
from .exports import export
from .indexing import index
from .storage import Store


def parser():
    p = argparse.ArgumentParser(description="Map MEP technical requirements and review cross-document evidence")
    p.add_argument("--db", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--config")
    p.add_argument("--skills-root")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("index")
    c.add_argument("--file-id")
    c.add_argument("--mode", choices=("auto", "native", "sql", "json"), default="auto")
    c.add_argument("--run-id")
    c.add_argument("--input")
    c.add_argument("--slot", default="specification")
    sub.add_parser("map")
    sub.add_parser("compare")
    for command in ("record", "category", "conflicts", "coverage", "export", "export-approved"):
        c = sub.add_parser(command)
        c.add_argument("--entity-id")
        c.add_argument("--tag")
        c.add_argument("--category")
        c.add_argument("--history", action="store_true")
        if command in ("export", "export-approved"):
            c.add_argument("--output", required=True)
        if command == "export-approved":
            c.add_argument("--require-complete", action="store_true")
    c = sub.add_parser("source")
    c.add_argument("--requirement-id", required=True)
    c = sub.add_parser("search")
    c.add_argument("--query", required=True)
    c.add_argument("--limit", type=int, default=50)
    c = sub.add_parser("review")
    c.add_argument("--target-kind", choices=("requirement", "interpretation", "applicability", "case", "coverage", "value", "equipment_match"), required=True)
    c.add_argument("--target-id", required=True)
    c.add_argument("--decision", required=True)
    c.add_argument("--value-json")
    for command in ("interpret", "accept-value"):
        c = sub.add_parser(command)
        c.add_argument("--payload-json", required=True)
        if command == "interpret":
            c.add_argument("--requirement-id", required=True)
            c.add_argument("--method", choices=("manual", "codex_assisted"), default="manual")
        else:
            c.add_argument("--entity-id", required=True)
    for name in ("review", "interpret", "accept-value"):
        c = sub.choices[name]
        c.add_argument("--actor", required=True)
        c.add_argument("--reason", required=True)
        c.add_argument("--refs-json", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    store = None
    try:
        cfg = configuration(args.config)
        if args.command == "index" and args.mode == "json" and not args.input:
            raise ValueError("JSON mode requires --input and the original registered --file-id")
        store = Store(args.db, args.project_id, cfg, args.skills_root)
        command = args.command
        if command == "index":
            result = {"imports": index(store, args.file_id, mode=args.mode, run_id=args.run_id, input_json=args.input, slot=args.slot)}
        elif command == "map":
            result = map_requirements(store)
        elif command == "compare":
            result = compare(store)
        elif command == "review":
            result = review(store, args.target_kind, args.target_id, args.decision, args.actor, args.reason, json.loads(args.refs_json), json.loads(args.value_json) if args.value_json is not None else None)
        elif command == "interpret":
            result = interpret(store, args.requirement_id, json.loads(args.payload_json), args.actor, args.reason, json.loads(args.refs_json), args.method)
        elif command == "accept-value":
            result = accept_value(store, args.entity_id, json.loads(args.payload_json), args.actor, args.reason, json.loads(args.refs_json))
        elif command == "source":
            records = store.requirements(store.upstream(), ids=[args.requirement_id])[0]
            if not records:
                raise ValueError("Requirement is not current in this project")
            result = records[0]
        elif command == "search":
            if not args.query.strip() or not 1 <= args.limit <= 1000:
                raise ValueError("Nonempty literal query and limit 1..1000 required")
            upstream = store.upstream()
            available = {r["id"] for r in store.catalog(upstream)[0]}
            phrase = '"' + args.query.replace('"', '""') + '"'
            ids = [r[0] for r in store.conn.execute("SELECT requirement_id FROM tr_fts WHERE tr_fts MATCH ? AND project_id=?", (phrase, args.project_id)) if r[0] in available][:args.limit]
            result = {"mode": "current_literal_FTS5", "requirements": store.requirements(upstream, ids=ids)[0]}
        else:
            record = snapshot(store, args.entity_id, args.tag, args.category, args.history)
            if command == "conflicts":
                result = {"comparison_status": record["comparison_status"], "cases": [c for c in record["cases"] if c["status"] not in ("resolve", "not_applicable")]}
            elif command == "coverage":
                result = {"coverage": record["coverage"], "completeness": record["completeness"], "comparison_status": record["comparison_status"]}
            elif command in ("export", "export-approved"):
                result = export(record, args.output, command == "export-approved", getattr(args, "require_complete", False))
            else:
                result = record
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 1 if command == "index" and any("error" in i for i in result["imports"]) else 0
    except KeyboardInterrupt:
        print('{"status":"interrupted","message":"Completed imports remain committed; incomplete transactions roll back."}', file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
