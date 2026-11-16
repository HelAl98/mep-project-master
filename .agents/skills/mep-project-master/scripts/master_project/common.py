import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

HOME = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def key(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def resolve(base, path):
    item = Path(path).expanduser()
    return (item if item.is_absolute() else Path(base) / item).resolve()


def configuration(path):
    path = Path(path).resolve(strict=True)
    cfg = read(path)
    cfg["config_path"] = str(path)
    for name in ("project_id", "project_name", "source_directory", "database", "output_directory", "skills_root"):
        if not isinstance(cfg.get(name), str) or not cfg[name].strip():
            raise ValueError("Missing configuration field: " + name)
    for name in ("source_directory", "database", "output_directory", "skills_root"):
        cfg[name] = str(resolve(path.parent, cfg[name]))
    src, db, out = (Path(cfg[n]) for n in ("source_directory", "database", "output_directory"))
    if not src.is_dir():
        raise ValueError("Source directory does not exist")
    if out == src or out in src.parents or out.is_relative_to(src) or db.is_relative_to(src):
        raise ValueError("Keep output and database outside source directory to prevent re-ingestion")
    if db == out or db.is_dir():
        raise ValueError("Database must be a file path")
    if cfg.get("execution_mode", "guided") not in ("guided", "automatic"):
        raise ValueError("execution_mode must be guided or automatic")
    cfg.setdefault("execution_mode", "guided")
    cfg.setdefault("scope", {"id": "project", "file_ids": [], "system": None, "categories": [], "entity_ids": []})
    if not cfg["scope"].get("id"):
        raise ValueError("An explicit scope ID is required")
    for name in ("registry_config", "matching_config", "review_config", "package_config", "quality_config"):
        if cfg.get(name):
            cfg[name] = str(resolve(path.parent, cfg[name]))
            if not Path(cfg[name]).is_file():
                raise ValueError("Configuration dependency missing: " + cfg[name])
    return cfg


def code_hash():
    return key([(str(p.relative_to(HOME)), sha(p)) for p in sorted(HOME.rglob("*"))
                if p.is_file() and p.suffix in (".py", ".json", ".sql", ".md", ".yaml")])
