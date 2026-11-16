"""P1-01. Query-only source currency and explicit saved-provenance impact projection."""
from collections import Counter, defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .common import read, resolve, now, key
from .memory import connect
from .evidence import current_files


def stable_hash(path, max_bytes=None):
    """A racing file, permission error or non-file never establishes CURRENT."""
    try:
        with Path(path).open('rb') as stream:
            before = os.fstat(stream.fileno())
            if not __import__('stat').S_ISREG(before.st_mode):
                return {'status': 'UNVERIFIED', 'reason': 'not_a_regular_file'}
            if max_bytes is not None and before.st_size > max_bytes:
                return {'status': 'UNVERIFIED', 'reason': 'configured_hash_size_limit'}
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        final = Path(path).stat()
        # Windows fstat/stat can expose different ctime semantics. Compare it only
        # between the two observations of the same open handle.
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after) or before.st_ctime_ns != after.st_ctime_ns or signature(after) != signature(final):
            return {'status': 'UNVERIFIED', 'reason': 'file_changed_during_read'}
        return {'status': 'READABLE', 'sha256': digest.hexdigest(), 'bytes': final.st_size}
    except FileNotFoundError:
        return {'status': 'MISSING', 'reason': 'path_not_found'}
    except (OSError, ValueError) as error:
        return {'status': 'UNVERIFIED', 'reason': type(error).__name__, 'detail': str(error)}


class ImpactGraph:
    def __init__(self):
        self.nodes = {}
        self.aliases = defaultdict(set)
        self.edges = defaultdict(dict)
        self.parents = defaultdict(dict)
        self.paths = {}
        self.unknown = defaultdict(set)
        self.context = []
        self.source_root = None
        self.recorded_hashes = {}

    def add(self, kind, identity, locator, **metadata):
        node = kind + ':' + str(identity)
        self.nodes.setdefault(node, {'node_id': node, 'kind': kind, 'id': identity, 'locator': locator, **metadata})
        self.aliases[str(identity)].add(node)
        return node

    def edge(self, parent, child, evidence):
        if parent not in self.nodes or child not in self.nodes:
            self.context.append({'parent': parent, 'consumer': child, 'classification': 'UNKNOWN', 'reason': 'orphan_saved_relation', 'evidence': evidence})
            if child in self.nodes:
                self.unknown[child].add('orphan_saved_relation:' + parent)
            return
        if parent != child:
            self.edges[parent].setdefault(child, evidence)
            self.parents[child].setdefault(parent, evidence)

    def link(self, identity, child, evidence, kinds=None):
        candidates = self.aliases.get(str(identity), set())
        if kinds:
            candidates = {n for n in candidates if self.nodes[n]['kind'] in kinds}
        if len(candidates) == 1:
            self.edge(next(iter(candidates)), child, evidence)
        else:
            self.unknown[child].add('unresolved_reference:' + str(identity))

    def walk(self, value, consumer, pointer='', base=None):
        """Only exact known IDs/paths count. Exclusions and inventory are contextual."""
        if isinstance(value, list):
            for index, item in enumerate(value):
                self.walk(item, consumer, pointer + '/' + str(index), base)
        elif isinstance(value, dict):
            reference_id = value.get('file_id', value.get('original_file_id'))
            recorded_hash = value.get('sha256', value.get('original_sha256'))
            if reference_id in self.recorded_hashes and recorded_hash and recorded_hash != self.recorded_hashes[reference_id]:
                self.unknown[consumer].add('saved_source_hash_differs_from_registered_head:' + reference_id)
            id_kinds = {'file_id': {'source'}, 'original_file_id': {'source'}, 'source_file_id': {'source'},
                        'version_id': {'version'}, 'analysis_id': {'analysis'}, 'occurrence_id': {'equipment_observation'},
                        'import_id': {'equipment_import', 'specification_import'}, 'record_id': {'extracted_record'},
                        'core_record_id': {'extracted_record'}, 'profile_id': {'consolidated_profile'},
                        'entity_id': {'equipment_entity'}, 'parameter_id': {'equipment_parameter'},
                        'requirement_id': {'technical_requirement'}, 'run_id': {'extraction_run', 'consolidation_run', 'matching_run'}}
            context_keys = {'registered_heads', 'changed_source_exclusions', 'excluded_provisional_references',
                            'source_inventory', 'registry_snapshot', 'historical_sources'}
            for field, item in value.items():
                location = pointer + '/' + field.replace('~', '~0').replace('/', '~1')
                output_listing = field in ('outputs', 'output_files', 'deliverables') or (field == 'artifacts' and (not pointer or pointer.endswith('/receipt')))
                if field in context_keys or output_listing:
                    self.context.append({'consumer': consumer, 'pointer': location, 'classification': 'CONTEXT_ONLY',
                                         'reason': 'output_listing_is_not_an_input_dependency' if output_listing else 'inventory_or_excluded_evidence_is_not_a_positive_dependency'})
                    continue
                if field in id_kinds and item is not None:
                    self.link(item, consumer, location, id_kinds[field])
                elif field in ('source_file_ids', 'occurrence_ids', 'equipment_ids', 'requirement_ids') and isinstance(item, list):
                    for identity in item:
                        self.link(identity, consumer, location)
                elif field == 'id' and isinstance(item, str) and item in self.aliases:
                    matches = self.aliases[item]
                    if len(matches) == 1:
                        self.edge(next(iter(matches)), consumer, location)
                elif field in ('path', 'original_path', 'source_path', 'relative_path', 'evidence_path') and isinstance(item, str):
                    origin = self.source_root if field == 'relative_path' and self.source_root else base or Path.cwd()
                    path = resolve(origin, item)
                    anchor = self.paths.get(str(path).casefold())
                    if anchor:
                        self.edge(anchor, consumer, location)
                self.walk(item, consumer, location, base)

    def project(self, sources):
        roots = {s['node_id']: s for s in sources}
        ancestors = {node: set() for node in self.nodes}
        queue = deque()
        for node in roots:
            ancestors[node].add(node)
            queue.append(node)
        while queue:
            parent = queue.popleft()
            for child in self.edges[parent]:
                addition = ancestors[parent] - ancestors[child]
                if addition:
                    ancestors[child].update(addition)
                    queue.append(child)
        for node in self.nodes:
            for parent in self.parents[node]:
                if not ancestors[parent]:
                    self.unknown[node].add('unresolved_dependency_ancestry:' + parent)
        queue = deque(n for n in self.nodes if self.unknown[n])
        while queue:
            parent = queue.popleft()
            for child in self.edges[parent]:
                added = self.unknown[parent] - self.unknown[child]
                if added:
                    self.unknown[child].update(added)
                    queue.append(child)
        result = []
        for node, metadata in self.nodes.items():
            if node in roots:
                continue
            known = ancestors[node]
            changed = sorted(r for r in known if roots[r]['currency'] in ('MODIFIED', 'MISSING'))
            uncertain = sorted(r for r in known if roots[r]['currency'] == 'UNVERIFIED')
            if changed:
                status = 'POTENTIALLY_OUTDATED'
            elif uncertain or not known or self.unknown[node]:
                status = 'UNKNOWN'
            else:
                status = 'UNAFFECTED_BY_DETECTED_SOURCE_CHANGES'
            parents = [{'node_id': p, 'evidence': evidence} for p, evidence in self.parents[node].items()]
            result.append({**metadata, 'impact': status, 'changed_source_ids': changed,
                           'direct_changed_source_ids': sorted(set(changed) & set(self.parents[node])),
                           'unverified_source_ids': uncertain, 'known_source_ids': sorted(known),
                           'unknown_dependencies': sorted(self.unknown[node])[:25],
                           'unknown_dependency_count': len(self.unknown[node]), 'direct_dependencies': parents,
                           'coverage_statement': 'Explicit saved paths only; absent provenance does not prove independence'})
        return result


def load_config(path):
    """Reuse master config paths, allowing an unavailable source root to be reported."""
    path = Path(path).resolve(strict=True)
    cfg = read(path)
    for field in ('database', 'source_directory', 'output_directory'):
        cfg[field] = str(resolve(path.parent, cfg[field]))
    cfg.setdefault('scope', {'id': 'project'})
    cfg['config_path'] = str(path)
    return cfg


def assess(cfg, max_source_bytes=None, max_json_files=2000, max_json_bytes=32 * 1024 * 1024):
    conn = connect(cfg, writable=False)
    # Every SQL statement is read-only, including statements reached by future refactors.
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}
    conn.set_authorizer(lambda action, a, b, db, trigger: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    conn.execute('BEGIN')
    try:
        return _assess_snapshot(cfg, conn, max_source_bytes, max_json_files, max_json_bytes)
    finally:
        conn.rollback()
        conn.close()


def _assess_snapshot(cfg, conn, max_source_bytes, max_json_files, max_json_bytes):
    from types import SimpleNamespace
    graph = ImpactGraph()
    graph.source_root = Path(cfg['source_directory'])
    source_rows = current_files(SimpleNamespace(conn=conn, cfg=cfg))
    versions = {r['id']: dict(r) for r in conn.execute('SELECT * FROM versions')}
    available = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    sources = []
    for row in source_rows:
        path = (Path(cfg['source_directory']) / row['relative_path']).resolve()
        expected = versions.get(row['version_id'])
        source = graph.add('source', row['file_id'], {'table': 'registry_files', 'id': row['file_id']})
        graph.paths[str(path).casefold()] = source
        checked = stable_hash(path, max_source_bytes)
        identity_ok = (expected is not None and Path(expected['source_path']).resolve() == path
                       and path.is_relative_to(Path(cfg['source_directory']).resolve())
                       and re.fullmatch(r'[a-fA-F0-9]{64}', row['sha256'] or '') is not None)
        if not identity_ok:
            status, reason = 'UNVERIFIED', 'registered_identity_or_hash_cannot_be_verified'
        elif checked['status'] == 'READABLE':
            status = 'CURRENT' if checked['sha256'] == row['sha256'] else 'MODIFIED'
            reason = 'original_bytes_match_registered_hash' if status == 'CURRENT' else 'original_bytes_differ_from_registered_hash'
        else:
            status, reason = checked['status'], checked['reason']
        sources.append({**row, 'node_id': source, 'path': str(path), 'currency': status, 'reason': reason,
                        'recorded_sha256': row['sha256'], 'live_sha256': checked.get('sha256'),
                        'archive_path': expected.get('archive_path') if expected else None,
                        'identity_verified': identity_ok, 'hash_check': checked,
                        'revision_approval': 'SEPARATE_EXISTING_REVIEW_NOT_ASSESSED_OR_CHANGED'})
        if status in ('MODIFIED', 'MISSING') and expected and expected.get('archive_path'):
            archive = resolve(Path(cfg['database']).parent, expected['archive_path'])
            archive_result = stable_hash(archive, max_source_bytes)
            sources[-1]['archive_check'] = {**archive_result, 'matches_recorded_source': archive_result.get('sha256') == row['sha256']}
        else:
            sources[-1]['archive_check'] = {'status': 'NOT_CHECKED', 'reason': 'archive_content_check_bounded_to_modified_or_missing_originals'}
        graph.recorded_hashes[row['file_id']] = row['sha256']
    source_paths = dict(graph.paths)

    def original_source_ids(value):
        if isinstance(value, dict):
            found = {value[k] for k in ('file_id', 'original_file_id') if isinstance(value.get(k), str) and value[k] in graph.recorded_hashes}
            for item in value.values():
                found.update(original_source_ids(item))
            return found
        if isinstance(value, list):
            return set().union(*(original_source_ids(item) for item in value)) if value else set()
        return set()

    def rows(table):
        if table not in available:
            return []
        columns = {r[0] for r in conn.execute('SELECT * FROM "' + table + '" LIMIT 0').description}
        if 'project_id' in columns:
            return [dict(r) for r in conn.execute('SELECT * FROM "' + table + '" WHERE project_id=?', (cfg['project_id'],))]
        return [dict(r) for r in conn.execute('SELECT * FROM "' + table + '"')]

    # Build actual SQL lineage. Optional extension tables are read only when present.
    definitions = [
        ('versions', 'version', None, [('source_path', 'path')]),
        ('registry_analyses', 'analysis', None, [('version_id', 'version')]),
        ('runs', 'extraction_run', None, [('version_id', 'version')]),
        ('records', 'extracted_record', None, [('version_id', 'version')]),
        ('eq_imports', 'equipment_import', None, [('file_id', 'source')]),
        ('eq_occurrences', 'equipment_observation', None, [('import_id', 'equipment_import')]),
        ('eq_parameters', 'equipment_parameter', None, [('occurrence_id', 'equipment_observation')]),
        ('eq_entities', 'equipment_entity', None, []),
        ('eq_runs', 'matching_run', None, []),
        ('tr_imports', 'specification_import', None, [('file_id', 'source')]),
        ('tr_requirements', 'technical_requirement', None, [('import_id', 'specification_import')]),
        ('uc_runs', 'consolidation_run', None, []),
        ('uc_profiles', 'consolidated_profile', 'run_id', []),
        ('uc_context', 'consolidated_context', 'run_id', [('file_id', 'source')]),
        ('uc_fields', 'consolidated_parameter', 'profile_id', []),
        ('uc_findings', 'consolidated_finding', 'profile_id', []),
    ]
    loaded = []
    for table, kind, membership, links in definitions:
        for row in rows(table):
            if table == 'versions' and str(Path(row['source_path']).resolve()).casefold() not in source_paths:
                try:
                    if not original_source_ids(json.loads(row['metadata_json'])):
                        continue
                except (TypeError, ValueError):
                    continue
            if membership and row[membership] not in graph.aliases:
                continue
            if table in ('runs', 'records') and row['version_id'] not in graph.aliases:
                continue
            node = graph.add(kind, row['id'], {'table': table, 'id': row['id']},
                             label=row.get('normalized_tag', row.get('name')), stored_review_status=row.get('review_status'))
            loaded.append((table, row, node, links))
    for table, row, node, links in loaded:
        for field, kind in links:
            if kind == 'path':
                parent = source_paths.get(str(Path(row[field]).resolve()).casefold())
                if parent:
                    graph.edge(parent, node, table + '.' + field)
            else:
                graph.link(row[field], node, table + '.' + field, {kind})
    for row in rows('eq_entity_sources'):
        graph.link(row['occurrence_id'], 'equipment_entity:' + row['entity_id'], 'eq_entity_sources.id=' + row['id'], {'equipment_observation'})
    for row in rows('uc_observations'):
        child = 'consolidated_profile:' + row['profile_id']
        if child in graph.nodes:
            graph.link(row['occurrence_id'], child, 'uc_observations:' + row['relationship'], {'equipment_observation'})
    for row in rows('uc_links'):
        child = 'consolidated_profile:' + row['profile_id']
        if child in graph.nodes:
            graph.link(row['context_id'], child, 'uc_links:' + row['relationship'], {'consolidated_context'})
    for table, row, node, links in loaded:
        if table in ('uc_fields', 'uc_findings'):
            graph.link(row['profile_id'], node, table + '.profile_id', {'consolidated_profile'})
        if table == 'uc_profiles':
            graph.edge(node, 'consolidation_run:' + row['run_id'], 'uc_profiles.run_id aggregate output')
    for row in rows('uc_spec_evidence'):
        if row['run_id'] in graph.aliases:
            node = graph.add('specification_evidence', key(row), {'table': 'uc_spec_evidence', **row})
            graph.link(row['record_id'], node, 'uc_spec_evidence.record_id', {'extracted_record'})
            graph.link(row['file_id'], node, 'uc_spec_evidence.file_id', {'source'})

    artifacts, documents, skipped = {}, {}, []
    output_root = Path(cfg['output_directory']).resolve()
    if output_root.is_dir():
        for path in sorted(output_root.rglob('*')):
            if not path.is_file() or any(p.casefold() in {'snapshots', 'backups', 'qa'} for p in path.relative_to(output_root).parts):
                continue
            if not path.resolve().is_relative_to(output_root):
                skipped.append({'path': str(path), 'reason': 'output_link_outside_root'})
                continue
            if path.suffix.lower() not in {'.json', '.xlsx', '.xls', '.html', '.pdf', '.docx', '.csv', '.zip'}:
                continue
            node = graph.add('artifact', str(path.resolve()), {'path': str(path.resolve())}, format=path.suffix.lower())
            graph.paths[str(path.resolve()).casefold()] = node
            artifacts[str(path.resolve()).casefold()] = node
            if path.suffix.lower() == '.json':
                if len(documents) >= max_json_files or path.stat().st_size > max_json_bytes:
                    graph.unknown[node].add('configured_json_read_limit')
                    skipped.append({'path': str(path), 'reason': 'configured_json_read_limit'})
                    continue
                try:
                    documents[node] = read(path)
                except (OSError, ValueError) as error:
                    graph.unknown[node].add('unreadable_artifact:' + type(error).__name__)
    # Existing receipts explicitly describe outputs. Source-bearing outputs also feed their descriptor.
    for table, row, node, links in loaded:
        for field, text in row.items():
            if field.endswith('_json') and field != 'basis_json':
                try:
                    graph.walk(json.loads(text), node, table + '.' + field, Path(cfg['source_directory']))
                except (TypeError, json.JSONDecodeError):
                    graph.unknown[node].add('unreadable_saved_json:' + field)
    def output_links(value, consumer, base, allow_artifacts=False):
        if not isinstance(value, dict):
            return
        if not graph.parents[consumer]:
            return  # Co-listed outputs without recorded inputs do not establish a transformation.
        fields = ('outputs', 'output_files', 'deliverables') + (('artifacts',) if allow_artifacts else ())
        for field in fields:
            item = value.get(field, [])
            descriptors = item.values() if isinstance(item, dict) else item if isinstance(item, list) else []
            for descriptor in descriptors:
                if isinstance(descriptor, dict) and isinstance(descriptor.get('path'), str):
                    path = str(resolve(base, descriptor['path'])).casefold()
                    if path in artifacts:
                        graph.edge(consumer, artifacts[path], '/' + field + ' declared output')
    for node, value in documents.items():
        base = Path(graph.nodes[node]['locator']['path']).parent
        graph.walk(value, node, base=base)
        # Nested source.artifacts lists are INPUTS, never output declarations.
        output_links(value, node, base, allow_artifacts=isinstance(value, dict) and value.get('generation_status') == 'completed')
    for table in ('master_events', 'master_operator_events', 'master_packages'):
        for row in rows(table):
            field = 'manifest_json' if table == 'master_packages' else 'payload_json'
            try:
                value = json.loads(row[field])
            except (ValueError, TypeError):
                continue
            node = graph.add('saved_checkpoint' if table == 'master_events' else 'saved_provenance', row['id'],
                             {'table': table, 'id': row['id']}, stored_status=row.get('status'), action=row.get('action'))
            graph.walk(value, node, base=Path(cfg['config_path']).parent)
            base = Path(cfg['config_path']).parent
            output_links(value, node, base, allow_artifacts=table == 'master_events')
            if row.get('action') == 'equipment_consolidation_delivery':
                output_links(value.get('receipt', {}), node, base, allow_artifacts=True)
    impacted = graph.project(sources)
    return {'schema_version': 'mep-source-currency/1', 'project_id': cfg['project_id'], 'assessed_at': now(),
            'database': cfg['database'], 'database_access': 'mode=ro; query_only=ON; read transaction; authorizer denies writes',
            'summary': {'source_currency': dict(Counter(s['currency'] for s in sources)),
                        'impact_by_kind': {kind: dict(Counter(n['impact'] for n in impacted if n['kind'] == kind))
                                           for kind in sorted({n['kind'] for n in impacted})}},
            'sources': sources, 'dependencies': impacted, 'context_only_references': graph.context,
            'artifact_scan_limits': {'max_json_files': max_json_files, 'max_json_bytes_per_file': max_json_bytes, 'skipped': skipped},
            'accepted_limitations': [dict(r) for r in conn.execute("SELECT id,action,payload_json FROM master_operator_events WHERE project_id=? AND action='accepted_source_limitation' ORDER BY rowid", (cfg['project_id'],))] if 'master_operator_events' in available else [],
            'limitations': ['Impact is an assessment, existing checkpoints/revisions/approvals remain recorded as before.',
                            'UNAFFECTED means no changed source on the recorded paths; it is not complete dependency certification.',
                            'Unregistered external references are not searched; accepted limitations retain their existing audit meaning.',
                            'Historical snapshots/QA/backups are excluded from the current output scan.',
                            'Unknown provenance and unsupported tables are not inferred from filenames or engineering similarity.'],
            'engineering_approval_created': False, 'database_writes': False, 'workflow_changes': False}
