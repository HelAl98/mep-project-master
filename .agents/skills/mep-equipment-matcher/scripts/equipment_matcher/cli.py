"""Compact Windows-compatible CLI; no demonstration or test command."""
import argparse
import json
from pathlib import Path
import sys

from .common import config, dump, read_json
from .exports import export
from .matching import propose_groups, run_matches, snapshot
from .sources import check_size, extract, import_package, import_schedule, sql_package
from .storage import Database


def parser():
    result = argparse.ArgumentParser(description="MEP equipment evidence intake, candidate matching and engineering review")
    result.add_argument("--db", required=True, help="Existing registered engineering SQLite database")
    result.add_argument("--project-id", required=True)
    result.add_argument("--config", help="Project equipment configuration JSON")
    result.add_argument("--skills-root", help="Parent of existing sibling project skills")
    sub = result.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract", help="Reuse stored drawing evidence or extract registered native PDF/DXF")
    p.add_argument("--file-id")
    p.add_argument("--run-id")
    for command in ("import-schedule", "import-cad"):
        p = sub.add_parser(command)
        p.add_argument("--file-id", required=True)
        p.add_argument("--mapping", required=True)
        p.add_argument("--role", choices=("schedule", "boq", "electrical", "bms", "register", "drawing"), default="drawing" if command == "import-cad" else "schedule")
        p.add_argument("--slot")
    for command in ("import-json", "import-sql"):
        p = sub.add_parser(command)
        p.add_argument("--file-id", required=True)
        p.add_argument("--role", required=True, choices=("drawing", "schedule", "boq", "electrical", "bms", "register", "specification"))
        p.add_argument("--slot", required=True)
        if command == "import-json":
            p.add_argument("--input", required=True)
        else:
            p.add_argument("--run-id", required=True)
    sub.add_parser("match")
    sub.add_parser("unmatched")
    sub.add_parser("conflicts")
    p = sub.add_parser("show")
    p.add_argument("--id", help="Occurrence, entity, or cluster identifier")
    p.add_argument("--history", action="store_true")
    p = sub.add_parser("search")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("group")
    p.add_argument("--by", choices=("type", "category", "location"), default="type")
    p = sub.add_parser("export")
    p.add_argument("--output", required=True)
    p = sub.add_parser("review")
    p.add_argument("--target-kind", required=True, choices=("match", "relationship", "issue", "occurrence", "parameter", "entity"))
    p.add_argument("--target-id", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--value-json")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    database = None
    try:
        cfg = config(args.config)
        database = Database(args.db, args.project_id, args.skills_root)
        command = args.command
        if command == "extract":
            output = {"results": extract(database, cfg, args.file_id, args.run_id)}
        elif command in ("import-schedule", "import-cad"):
            output = import_schedule(database, args.file_id, read_json(args.mapping), args.role, cfg, args.slot, command == "import-cad")
        elif command == "import-json":
            path = Path(args.input).resolve(strict=True)
            check_size(path, cfg)
            output = import_package(database, args.file_id, read_json(path), cfg, args.role, args.slot)
        elif command == "import-sql":
            file = database.file(args.file_id)
            package, run_id = sql_package(database, file, args.run_id)
            output = import_package(database, args.file_id, package, cfg, args.role, args.slot, {"adapter": "existing-sql", "run_id": run_id})
        elif command == "match":
            output = run_matches(database, cfg)
        elif command == "group":
            output = propose_groups(database, cfg, args.by)
        elif command == "review":
            output = database.review(args.target_kind, args.target_id, args.decision, args.actor, args.reason,
                                     json.loads(args.value_json) if args.value_json is not None else None, cfg)
        else:
            state = snapshot(database, cfg, history=getattr(args, "history", False))
            if command == "export":
                output = export(state, args.output)
            elif command == "unmatched":
                output = {"matching_status": state["matching_status"], "occurrences": [o for o in state["occurrences"] if o["id"] in state["unmatched"]]}
            elif command == "conflicts":
                output = {"matching_status": state["matching_status"], "issues": state["issues"]}
            elif command == "show":
                output = state
                if args.id:
                    output = next((item for items in (state["occurrences"], state["entities"], state["instance_clusters"]) for item in items
                                   if item.get("id", item.get("cluster_id")) == args.id), None)
                    if output is None:
                        raise ValueError("Record not found in requested project/currentness mode")
            elif command == "search":
                if not 1 <= args.limit <= 1000 or not args.query.strip():
                    raise ValueError("Search needs nonempty text and limit 1..1000")
                phrase = '"' + args.query.replace('"', '""') + '"'
                matches = {r[0] for r in database.conn.execute("SELECT occurrence_id FROM eq_fts WHERE eq_fts MATCH ? AND project_id=?", (phrase, args.project_id))}
                output = {"occurrences": [o for o in state["occurrences"] if o["id"] in matches][:args.limit], "mode": "current-literal-FTS5-including-reviewed-aliases"}
        print(json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 1 if args.command == "extract" and any("error" in r for r in output["results"]) else 0
    except KeyboardInterrupt:
        print('{"status":"interrupted","message":"Completed imports remain committed; incomplete transactions roll back."}', file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
