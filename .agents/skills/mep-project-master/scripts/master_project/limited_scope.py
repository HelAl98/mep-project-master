"""Audited available-PDF-text eligibility; never full coverage or technical approval.
Uses existing master_operator_events only. No models, extraction, external probing or migrations.
"""
from pathlib import Path
import json
import uuid
from .common import read, sha, key, encoded, now, resolve
from .memory import Memory, project_lock
from .evidence import current_files, selected_files, source_fingerprint, valid_artifacts, valid_persisted

OPERATIONS = {'03': '04:specification-extractor.extract', '04': '05:etl-pipeline.ingest'}
REVIEW_WARNINGS = {'raster_content_unprocessed', 'unicode_text_review',
                   'specification_layout_review', 'continuation_candidate'}

def need(condition, message):
    if not condition:
        raise ValueError(message)

def snapshot(cfg, memory):
    return {'source_digest': source_fingerprint(cfg), 'registered_heads': current_files(memory)}

def _path(cfg, name):
    return resolve(Path(cfg['config_path']).parent, name)

def _file(cfg, descriptor, output=False):
    need(isinstance(descriptor, dict), 'Expected path/sha256 descriptor')
    p = _path(cfg, descriptor.get('path', ''))
    need(p.is_file() and sha(p) == descriptor.get('sha256'), 'Missing/changed artifact: ' + str(p))
    if output:
        need(p.is_relative_to(Path(cfg['output_directory'])), 'Evidence artifact must be in project output')
    return p

def _rows(memory, action):
    return [dict(r) for r in memory.conn.execute(
        'SELECT * FROM master_operator_events WHERE project_id=? AND scope_id=? AND action=? ORDER BY rowid',
        (memory.cfg['project_id'], memory.cfg['scope']['id'], action))]

def _lookup(memory, action, identity):
    rows = [r for r in _rows(memory, action) if r['id'] == identity]
    need(len(rows) == 1, 'Unknown/foreign scoped audit ID: ' + str(identity))
    payload = json.loads(rows[0]['payload_json'])
    _file(memory.cfg, payload['receipt_file'], output=True)
    return payload

def _append(memory, action, receipt, path, basis):
    identity = uuid.uuid4().hex
    payload = {'receipt': receipt, 'receipt_file': {'path': str(path), 'sha256': sha(path)}, 'basis': basis,
               'engineering_approval_created': False}
    with memory.conn:
        memory.conn.execute('INSERT INTO master_operator_events VALUES(?,?,?,?,?,?,?,?)',
            (identity, memory.cfg['project_id'], memory.cfg['scope']['id'], action,
             receipt['actor'], receipt['reason'], encoded(payload), now()))
    return {'audit_id': identity, 'action': action, 'formal_stage_completion_created': False,
            'engineering_approval_created': False}

def _envelope(cfg, receipt):
    need(receipt.get('project_id') == cfg['project_id'] and receipt.get('scope_id') == cfg['scope']['id'],
         'Foreign project/scope receipt')
    need(receipt.get('engineering_approval') is False and receipt.get('actor') and receipt.get('reason'),
         'Actor, reason and engineering_approval=false required')

def _source(memory, item):
    rows = {r['file_id']: r for r in selected_files(memory)}
    source = rows.get(item.get('file_id'))
    need(source and source['status'] not in ('missing', 'error', 'excluded'), 'Source is not registered/current')
    need(source['sha256'] == item.get('sha256'), 'Registered source hash mismatch')
    p = Path(memory.cfg['source_directory']) / source['relative_path']
    archive = Path(memory.cfg['database']).with_suffix('.evidence') / source['sha256'][:2] / source['sha256']
    need(p.is_file() and sha(p) == source['sha256'], 'Live source changed: ' + str(p))
    need(archive.is_file() and sha(archive) == source['sha256'], 'Original archive verification failed')
    return source, p

def _prerequisites(cfg):
    from .engine import status
    states = {s['id']: s['status'] for s in status(cfg)['stages']}
    need(states.get('01') == 'COMPLETED' and states.get('02') == 'COMPLETED',
         'Scoped eligibility still requires current Stage01 and Stage02')

def record_limitation(cfg, receipt_path, human_authorized=False):
    need(human_authorized, 'Actual human authorization required to record source limitation')
    p = _path(cfg, receipt_path); receipt = read(p); _envelope(cfg, receipt)
    need(receipt.get('schema_version') == 'mep-accepted-source-limitation/1', 'Unsupported limitation contract')
    need(p.is_relative_to(Path(cfg['output_directory'])), 'Limitation receipt must be in project output')
    with project_lock(cfg):
        m = Memory(cfg, writable=True)
        try:
            if receipt.get('disposition') == 'retired':
                target = receipt.get('limitation_id'); _lookup(m, 'accepted_source_limitation', target)
                return _append(m, 'retired_source_limitation', receipt, p, snapshot(cfg, m))
            need(receipt.get('disposition') == 'accepted_unavailable' and receipt.get('authorization'),
                 'Explicit accepted_unavailable disposition and human authorization evidence required')
            need(receipt.get('classification') == 'unresolved_source_coverage_limitation',
                 'Missing reference cannot be recorded as a confirmed design conflict')
            refs = receipt.get('references', [])
            need(refs, 'Missing reference inventory required')
            names = set()
            for ref in refs:
                name = ref.get('name')
                need(isinstance(name, str) and name and name not in names, 'Unique reference names required')
                names.add(name)
                need(ref.get('hosts') and ref.get('potentially_affected_information') and
                     ref.get('unresolved_coordination_limitations'), 'Hosts and engineering impact/uncertainty required')
                for host in ref['hosts']:
                    _source(m, host)
            need(receipt.get('allowed_operations') and
                 set(receipt['allowed_operations']) <= set(OPERATIONS.values()) | {'06:mep-equipment-matcher.import-json', '06:mep-equipment-matcher.match'}, 'Unsupported scoped operation')
            return _append(m, 'accepted_source_limitation', receipt, p, snapshot(cfg, m))
        finally:
            m.close()

def _limitation(cfg, memory, identity, basis):
    payload = _lookup(memory, 'accepted_source_limitation', identity)
    need(payload['basis'] == basis, 'Limitation stale: source inventory/bytes changed; reassess restored/new sources')
    need(not any(json.loads(r['payload_json'])['receipt'].get('limitation_id') == identity
                 for r in _rows(memory, 'retired_source_limitation')), 'Limitation has been retired/restored')
    return payload['receipt']

def warning_inventory(package):
    warnings = list(package.get('issues', []))
    for r in package.get('records', []):
        warnings.extend(r.get('review', {}).get('issues', []))
    return warnings

def _validate_item(cfg, memory, item, stage, parent_items):
    source, original = _source(memory, item['original'])
    evidence_path = _file(cfg, item['evidence'], output=True); package = read(evidence_path)
    # Reuse the installed package contract; never relax record review or locator rules.
    import importlib.util
    validator_path = Path(cfg['skills_root']) / 'etl-pipeline/scripts/mep_store.py'
    spec = importlib.util.spec_from_file_location('_mep_available_scope_contract', validator_path)
    validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
    validator.validate_package(package)
    need(package.get('schema_version') == 'mep-evidence/1' and package.get('records'), 'Nonempty existing evidence required')
    doc = package.get('document', {})
    need(doc.get('media_type') == 'pdf', 'Initial available-scope contract supports native PDF text only')
    pdf = _file(cfg, {'path': doc.get('path'), 'sha256': doc.get('sha256')}, output=True)
    conversion = read(_file(cfg, item['conversion'], output=True))
    need(conversion.get('source_file_id', conversion.get('original_file_id')) == source['file_id'] and
         conversion.get('source_sha256', conversion.get('original_sha256')) == source['sha256'],
         'Conversion manifest does not identify this original registered source')
    need(conversion.get('pdf_sha256') == doc['sha256'] and
         _path(cfg, conversion.get('pdf_path', '')) == pdf, 'Conversion target hash/path mismatch')
    origin_name = conversion.get('source_path', conversion.get('original_path'))
    need(origin_name and _path(cfg, origin_name) == original, 'Conversion original path mismatch')
    need(item.get('available_scope') == 'native_pdf_text_only' and item.get('requires_external_references') == [],
         'Explicit available native-text scope without missing-Xref dependency required')
    warnings = warning_inventory(package)
    codes = {w.get('code') if isinstance(w, dict) else w for w in warnings}
    need(codes <= REVIEW_WARNINGS, 'Substantive/unknown extraction warnings remain blocked: ' + str(codes - REVIEW_WARNINGS))
    disposition = item.get('warning_disposition', {})
    need(disposition.get('inventory_digest') == key(warnings) and
         disposition.get('action') == 'preserve_unreviewed_for_text_extraction_or_ingestion' and
         disposition.get('reason'), 'Exact retained-warning disposition required; warnings cannot be suppressed')
    if stage == '03':
        need(any(r.get('kind') == 'line' for r in package['records']), 'No native PDF lines available')
    else:
        parent = parent_items.get(source['file_id'])
        need(parent and parent['original'] == item['original'], 'Stage04 source lacks matching Stage03 available-evidence receipt')
        parent_path = _file(cfg, parent['evidence'], output=True); native = read(parent_path)
        need(doc['sha256'] == native['document']['sha256'] and
             item.get('parent_evidence_sha256') == parent['evidence']['sha256'], 'Wrong source-local extraction parent')
        need(all(r.get('kind') == 'specification' for r in package['records']), 'Stage04 receipt requires specification records')
        for r in package['records']:
            fragments = r.get('data', {}).get('line_fragments', [])
            need(fragments and r.get('raw_text') == '\n'.join(f['raw_text'] for f in fragments), 'Specification text/fragment mismatch')
            for f in fragments:
                i = f.get('input_record_index')
                need(type(i) is int and 0 <= i < len(native['records']), 'Invalid original line locator')
                line = native['records'][i]
                need(line.get('kind') == 'line' and f['raw_text'] == line.get('raw_text') and
                     f.get('source') == line.get('source'), 'Specification fragment lost source text/locator provenance')
    return {'file_id': source['file_id'], 'evidence': item['evidence'], 'warning_codes': sorted(codes)}

def _validate_receipt(cfg, memory, receipt, basis):
    _envelope(cfg, receipt)
    need(receipt.get('schema_version') == 'mep-available-evidence/1', 'Unsupported available-evidence receipt')
    stage = receipt.get('stage')
    need(stage in OPERATIONS and receipt.get('allowed_operation') == OPERATIONS[stage], 'Unsupported stage/operation bridge')
    need(receipt.get('full_source_coverage') is False and receipt.get('technical_findings_promoted') is False,
         'Available evidence never establishes full coverage or verified technical findings')
    need(receipt.get('limitations'), 'Persistent unresolved limitations required')
    parent_items = {}
    if stage == '04':
        parent = _check_record(cfg, memory, receipt.get('parent_receipt_id'), basis, expected_stage='03')
        parent_items = {i['original']['file_id']: i for i in parent['receipt']['items']}
    context = []
    for identity in receipt.get('context_limitation_ids', []):
        limit = _limitation(cfg, memory, identity, basis)
        context.append({'audit_id': identity, 'references': limit['references'],
                        'scope_role': 'context only; not a blanket exemption for these inputs'})
    items = receipt.get('items', [])
    need(items and len({i['original']['file_id'] for i in items}) == len(items), 'Unique exact source items required')
    result = [_validate_item(cfg, memory, item, stage, parent_items) for item in items]
    return {'receipt': receipt, 'items': result, 'context_limitations': context,
            'full_source_coverage': False, 'engineering_approval': False}

def _check_record(cfg, memory, identity, basis, expected_stage=None):
    payload = _lookup(memory, 'available_evidence_scope', identity)
    need(payload['basis'] == basis, 'Available-evidence receipt stale: source inventory or registered versions changed')
    need(expected_stage is None or payload['receipt'].get('stage') == expected_stage, 'Wrong prerequisite receipt stage')
    return _validate_receipt(cfg, memory, payload['receipt'], basis)

def record_available(cfg, receipt_path):
    p = _path(cfg, receipt_path); receipt = read(p)
    need(p.is_relative_to(Path(cfg['output_directory'])), 'Receipt must be in project output')
    _prerequisites(cfg)
    with project_lock(cfg):
        m = Memory(cfg, writable=True)
        try:
            basis = snapshot(cfg, m); result = _validate_receipt(cfg, m, receipt, basis)
            event = _append(m, 'available_evidence_scope', receipt, p, basis)
            return {**event, 'available_scope_status': 'RECORDED_UNREVIEWED',
                    'source_file_ids': [i['file_id'] for i in result['items']], 'full_source_coverage': False}
        finally:
            m.close()

def assess(cfg, memory, request, basis=None):
    need(request.get('project_id') == cfg['project_id'] and request.get('scope_id') == cfg['scope']['id'], 'Foreign eligibility request')
    operation = request.get('operation'); need(operation in OPERATIONS.values(), 'Operation not eligible for limited-source bridge')
    basis = snapshot(cfg, memory) if basis is None else basis
    checked = _check_record(cfg, memory, request.get('receipt_id'), basis)
    need(checked['receipt']['allowed_operation'] == operation, 'Receipt does not authorize this operation')
    selected = request.get('evidence', []); need(selected, 'Explicit evidence subset required')
    known = {i['file_id']: i['evidence'] for i in checked['items']}
    ids = [i['file_id'] for i in selected]; need(len(ids) == len(set(ids)), 'Duplicate requested sources')
    for item in selected:
        need(known.get(item['file_id']) == {'path': item['path'], 'sha256': item['sha256']}, 'Input outside audited available scope')
    return {'eligible': True, 'eligibility_kind': 'EXACT_OPERATION_AVAILABLE_TEXT_ONLY', 'operation': operation,
            'source_file_ids': ids, 'evidence': selected, 'receipt_id': request['receipt_id'],
            'limitations': checked['receipt']['limitations'], 'context_limitations': checked['context_limitations'],
            'formal_stage_completion': False, 'full_source_coverage': False, 'engineering_approval': False}

def eligibility(cfg, request_path):
    try:
        _prerequisites(cfg); m = Memory(cfg)
        try:
            return assess(cfg, m, read(_path(cfg, request_path)))
        finally:
            m.close()
    except (ValueError, OSError, KeyError, TypeError) as e:
        return {'eligible': False, 'reason': str(e), 'formal_stage_completion': False, 'engineering_approval': False}

def job_eligibility(cfg, memory, stage, job):
    if stage == '06' and job.get('skill') == 'mep-equipment-matcher' and job.get('command') == 'match':
        from .matching_scope import assess_job
        return assess_job(cfg, memory, job)
    if stage == '06' and job.get('skill') == 'mep-equipment-matcher' and job.get('command') == 'import-json':
        from .equipment_scope import assess_job
        return assess_job(cfg, memory, job)
    path = job.get('scoped_request')
    need(path and stage in ('04', '05'), 'No supported explicit operation-scoped request')
    request = read(_path(cfg, path)); expected = stage + ':' + job['skill'] + '.' + job.get('command', '')
    need(request.get('operation') == expected, 'Scoped request cannot bypass another operation')
    result = assess(cfg, memory, request)
    need(set(job.get('source_file_ids', [])) == set(result['source_file_ids']), 'Job source scope differs from eligible input scope')
    need([str(_path(cfg, p)) for p in job.get('inputs', [])] ==
         [str(_path(cfg, i['path'])) for i in result['evidence']], 'Job inputs differ from audited evidence')
    return result

def bridge(cfg, memory, stage, jobs, blocked, states):
    need(stage in ('04', '05') and blocked == [{'04': '03', '05': '04'}[stage]] and jobs,
         'Unrelated prerequisite remains blocked')
    need(states.get('01') == 'COMPLETED' and states.get('02') == 'COMPLETED', 'Unrelated upstream prerequisite is not current')
    return [job_eligibility(cfg, memory, stage, job) for job in jobs]

def revalidate_prerequisites(cfg, receipt_path):
    """Explicit master-upgrade revalidation, not rerunning intake/profile or technical approval."""
    p = _path(cfg, receipt_path); proof = read(p)
    need(proof.get('schema_version') == 'mep-prerequisite-revalidation/1' and
         proof.get('project_id') == cfg['project_id'] and proof.get('scope') == cfg['scope'] and
         proof.get('engineering_approval') is False and proof.get('actor') and proof.get('reason'), 'Invalid prerequisite baseline')
    from .engine import jobs_for, job_fingerprint, stage_signature
    from .discovery import discover
    with project_lock(cfg):
        m = Memory(cfg, writable=True)
        try:
            basis = snapshot(cfg, m)
            need(proof['source_digest'] == basis['source_digest'] and proof['registered_heads'] == basis['registered_heads'],
                 'Sources changed since prerequisite baseline; cannot revalidate')
            inventory = discover(cfg)
            need(proof['skills'] == [[r['name'], r['signature'], r['available']] for r in inventory],
                 'Specialized skill implementation/capability changed; reassess upstream work')
            need([s['stage'] for s in proof['stages']] == ['01', '02'], 'Only Stage01/02 implementation revalidation supported')
            plans = []
            for st in proof['stages']:
                stage = st['stage']; need(st['configuration'] == cfg['stages'][stage], 'Upstream stage configuration changed')
                events = {e['id']: e for e in m.events(stage)}; event = events.get(st['stage_event_id'])
                need(event and event['status'] == 'COMPLETED' and event['fingerprint'] == st['stage_event_fingerprint'], 'Invalid historical stage basis')
                jobs = jobs_for(cfg, stage)
                need([j['job_spec'] for j in st['jobs']] == jobs, 'Upstream job specification changed')
                for old in st['jobs']:
                    cached = events.get(old['event_id'])
                    need(cached and cached['status'] == 'COMPLETED' and cached['fingerprint'] == old['fingerprint'] and
                         valid_artifacts(cached['payload']) and valid_persisted(m, cached['payload']), 'Prior job evidence is missing/stale')
                    for item in old['inputs']:
                        _file(cfg, item)
                audit = event['payload'].get('database_audit')
                if audit:
                    _file(cfg, audit)
                plans.append((st, event, events))
            # All stages checked before any revalidation event is appended.
            for st, event, events in plans:
                for old in st['jobs']:
                    payload = {**events[old['event_id']]['payload'], 'implementation_revalidation':
                               {'baseline': str(p), 'baseline_sha256': sha(p), 'prior_event_id': old['event_id'],
                                'meaning': 'Same source/evidence, new master implementation fingerprint only'}}
                    m.event(st['stage'], 'COMPLETED', job_fingerprint(cfg, m, old['job_spec'], inventory), payload, old['job_id'])
                m.event(st['stage'], 'COMPLETED', stage_signature(cfg, m, st['stage'], inventory),
                        {**event['payload'], 'implementation_revalidation': {'baseline': str(p), 'sha256': sha(p)}})
            return {'revalidated_stages': ['01', '02'], 'extractions_repeated': 0, 'engineering_approvals_created': False}
        finally:
            m.close()


def fingerprint_basis(cfg, memory):
    audits = []
    for action in ('accepted_source_limitation', 'retired_source_limitation', 'available_evidence_scope', 'equipment_evidence_scope', 'matching_evidence_scope'):
        for row in _rows(memory, action):
            payload = json.loads(row['payload_json']); f = _path(cfg, payload['receipt_file']['path'])
            audits.append([row['id'], sha(f) if f.is_file() else None])
    return {'sources': snapshot(cfg, memory), 'scoped_audits': audits}

def audit_summary(memory):
    return [{'audit_id': r['id'], 'stage': json.loads(r['payload_json'])['receipt']['stage'],
             'status': 'RECORDED_REQUIRES_EXACT_ELIGIBILITY_CHECK'}
            for r in _rows(memory, 'available_evidence_scope')]
