"""Read metadata/source only: never eval SKILL.md snippets or import them as APIs."""
from pathlib import Path
import importlib.util
from .common import HOME, read, sha, key


def routes(cfg):
    rows = read(HOME / "assets/config/skill-routes.json")
    overrides = cfg.get("routing", {})
    for row in rows:
        # Routing may disable a skill, but cannot invent executable entry points.
        row["enabled"] = overrides.get(row["name"], {}).get("enabled", True)
    return rows


def discover(cfg):
    root = Path(cfg["skills_root"])
    result = []
    for row in routes(cfg):
        path = root / row["name"]
        md = path / "SKILL.md"
        scripts = [path / p for p in row.get("interfaces", [])]
        installed = md.is_file()
        dependencies = []
        for module in row.get("python_dependencies", []):
            try:
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False
            dependencies.append({"module": module, "available": found})
        missing_skills = [n for n in row.get("skill_dependencies", []) if not (root / n / "SKILL.md").is_file()]
        missing_interfaces = [str(p) for p in scripts if not p.is_file()]
        signature = [(str(p.relative_to(path)), sha(p)) for p in sorted(path.rglob("*"))
                     if p.is_file() and p.suffix in (".md", ".py", ".sql", ".json", ".yaml")]
        result.append({**row, "path": str(path), "installed": installed,
                       "available": bool(installed and row["enabled"] and not missing_skills and not missing_interfaces
                                         and all(d["available"] for d in dependencies)),
                       "dependency_status": dependencies, "missing_skills": missing_skills,
                       "missing_interfaces": missing_interfaces, "signature": key(signature),
                       "skill_document_sha256": sha(md) if installed else None})
    return result


def workflow():
    return read(HOME / "assets/config/workflow.json")
