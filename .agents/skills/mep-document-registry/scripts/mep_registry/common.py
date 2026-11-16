from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

FIELDS = ('document_number', 'title', 'revision', 'revision_date', 'issue_status', 'discipline',
          'document_type', 'system', 'building', 'floor', 'scale', 'sheet_number')
LEVELS = {'missing': 0, 'inferred': 1, 'filename_derived': 2, 'content_extracted': 3}


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def key(*values):
    return hashlib.sha256(dump(values).encode('utf-8')).hexdigest()


def path_key(path):
    return os.path.normcase(str(Path(path).resolve())).replace('\\', '/')


def relative_key(relative):
    text = str(relative).replace('\\', '/')
    return text.casefold() if os.name == 'nt' else text


def skills_root(explicit=None):
    if explicit is not None:
        root = Path(explicit).resolve()
        if not (root / 'etl-pipeline/scripts/mep_store.py').is_file():
            raise ValueError('skills_root must contain the existing project etl-pipeline skill')
        return root
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent, parent / '.agents/skills'):
            if (candidate / 'etl-pipeline/scripts/mep_store.py').is_file():
                return candidate
    raise ValueError('Existing etl-pipeline skill not found; supply --skills-root')


@lru_cache(maxsize=8)
def load_core(root):
    path = Path(root) / 'etl-pipeline/scripts/mep_store.py'
    name = '_registry_existing_etl_' + key(str(path))[:12]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalized_number(value):
    return re.sub(r'\s+', '', str(value)).upper() if value not in (None, '') else None


def metadata_fingerprint(item):
    return key(item['metadata'], item['provenance'])


def select_fields(observations, reviews=()):
    """Literal content outranks filename heuristics; equal-priority conflict remains null."""
    result, provenance = {f: None for f in FIELDS}, {}
    corrections = {r['target_observation']: r for r in reviews
                   if r.get('decision') == 'correct_metadata' and r.get('target_observation')}
    for field in set(FIELDS) | {o['field'] for o in observations}:
        candidates = [o for o in observations if o['field'] == field]
        corrected = [(corrections[o['observation_id']], o) for o in candidates if o['observation_id'] in corrections]
        if corrected:
            decision, original = max(corrected, key=lambda pair: pair[0]['id'])
            result[field] = decision['value']
            provenance[field] = {**original, 'value': decision['value'], 'evidence_class': 'engineering_review',
                                  'review_status': 'reviewed', 'review_id': decision['id'],
                                  'actor': decision['actor'], 'original_value': original['value']}
            continue
        nonempty = [o for o in candidates if o['value'] is not None and o['value'] != '']
        if not nonempty:
            provenance[field] = candidates[0] if candidates else {'evidence_class': 'missing', 'review_status': 'unreviewed', 'source': {}}
            continue
        strongest = max(LEVELS.get(o['evidence_class'], 0) for o in nonempty)
        best = [o for o in nonempty if LEVELS.get(o['evidence_class'], 0) == strongest]
        distinct = {dump(o['value']) for o in best}
        if len(distinct) == 1:
            result[field] = best[0]['value']
            provenance[field] = best[0]
            if field == 'title' and best[0]['source'].get('method') == 'filename-heuristic':
                # A bare filename stem is not a document title. Keep its candidate
                # observation, while leaving the unknown title explicitly null.
                result[field] = None
        else:
            result[field] = None
            provenance[field] = {'evidence_class': 'conflicting', 'review_status': 'needs_review', 'candidates': best}
    return result, provenance
