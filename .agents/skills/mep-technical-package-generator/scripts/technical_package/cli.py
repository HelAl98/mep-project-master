"""No demo/test/approval/ingestion commands: read-only retrieval and local output only."""
import argparse
import json
from pathlib import Path
import sys

from .common import configuration
from .generation import COMPONENTS, generate, inspect
from .planning import plans
from .repository import Repository


def parser():
    root = argparse.ArgumentParser(description="Read-only MEP technical package generation from reviewed project SQLite")
    root.add_argument("--db", required=True)
    root.add_argument("--project-id", required=True)
    root.add_argument("--config", help="Package settings JSON")
    root.add_argument("--review-config", help="Exact existing cross-document review configuration")
    root.add_argument("--skills-root")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("categories")
    for name in ("readiness", "issues", "draft", "approved", "register", "specifications", "matrix", "rfq"):
        p = sub.add_parser(name)
        p.add_argument("--category", action="append", help="Actual category; repeat for several")
        p.add_argument("--tag")
        p.add_argument("--entity-id")
        if name not in ("readiness", "issues"):
            p.add_argument("--output", help="Dedicated output root; alternatively configure output_root")
        if name in ("register", "specifications", "matrix", "rfq"):
            p.add_argument("--mode", choices=("draft", "approved"), default="draft")
    p = sub.add_parser("inspect")
    p.add_argument("--output")
    p.add_argument("--manifest")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    repo = None
    try:
        cfg = configuration(args.config)
        repo = Repository(args.db, args.project_id, args.review_config, args.skills_root)
        command = args.command
        if command == "inspect":
            output = args.output or cfg["output_root"]
            if not output:
                raise ValueError("Supply a dedicated output root")
            result = inspect(repo, output, args.manifest)
        else:
            record = repo.record(tag=getattr(args, "tag", None), entity_id=getattr(args, "entity_id", None))
            categories = getattr(args, "category", None)
            groups = plans(repo, record, cfg, categories)
            if command == "categories":
                available = {}
                for group in groups:
                    available.setdefault(group["category"], []).append(group)
                # Reference-only source categories with no upstream entity remain visible, not fabricated.
                for occurrence in repo.upstream()["equipment"]["occurrences"]:
                    if occurrence.get("category"):
                        name = cfg["category_aliases"].get(occurrence["category"], occurrence["category"])
                        available.setdefault(name, [])
                result = {"categories": [{"category": category, "groups": len(rows), "ready_groups": sum(g["readiness"]["status"] == "READY_FOR_EXPORT" for g in rows),
                                          "upstream_entity_available": bool(rows)} for category, rows in sorted(available.items())]}
            elif command in ("readiness", "issues"):
                result = {"groups": [{"group_id": g["group_id"], "category": g["category"], "equipment_ids": [t["id"] for t in g["targets"]],
                                      "type": g["verified_type_id"], "quantity": g["quantity"], "readiness": g["readiness"]} for g in groups],
                          "comparison_status": record["comparison_status"], "database_access": "read_only"}
                if command == "issues":
                    result["groups"] = [g for g in result["groups"] if g["readiness"]["status"] != "READY_FOR_EXPORT"]
                    result["engineering_cases"] = record["cases"]
            else:
                output = args.output or cfg["output_root"]
                if not output:
                    raise ValueError("Supply a dedicated output root")
                mode = "approved" if command == "approved" else "draft" if command == "draft" else args.mode
                components = None if command in ("approved", "draft") else {command}
                result = generate(repo, record, cfg, output, mode, components, categories)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 0
    except KeyboardInterrupt:
        print('{"status":"interrupted","message":"Existing evidence/versions are unchanged; incomplete generation directories are retained."}', file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if repo is not None:
            repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
