"""BOQ-first screening from a deliberately bounded ASCII DXF export route.

Only model-space, horizontal or vertical LINE centerlines are measurable.
Labels can verify calibration/revision, but never contribute measured length.
No DWG conversion, image estimation, nested blocks, arcs or symbol counts.
"""
import json
import math
from pathlib import Path
import re

from .common import key, sha
from . import procurement_items as items

VERSION = 'ascii-dxf-line/1'
UNITS = {1: ('in', .0254), 2: ('ft', .3048), 4: ('mm', .001),
         5: ('cm', .01), 6: ('m', 1.)}
LENGTH_UNITS = dict(UNITS.values())
ACTION = 'procurement_geometry_checks_v1'


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a quantity')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite geometry/quantity')
    return result


def dxf_records(path):
    """Preserve original entity groups; fail closed on malformed/binary DXF."""
    if path.stat().st_size > 20_000_000:
        raise ValueError('ASCII DXF exceeds the supported 20 MB limit')
    raw = path.read_bytes()
    if raw.startswith(b'AutoCAD Binary DXF'):
        raise ValueError('Binary DXF is unsupported; export ASCII DXF')
    lines = raw.decode('utf-8-sig').splitlines()
    if len(lines) % 2:
        raise ValueError('Malformed DXF group pairs')
    pairs = [(int(lines[i].strip()), lines[i+1].strip()) for i in range(0, len(lines), 2)]
    if not pairs or pairs[-1] != (0, 'EOF'):
        raise ValueError('Incomplete DXF: missing EOF')
    section = None; header = []; entities = []; entity = None; seen_entities = False
    index = 0
    while index < len(pairs):
        code, value = pairs[index]
        if code == 0 and value == 'SECTION':
            if section is not None or index+1 >= len(pairs) or pairs[index+1][0] != 2:
                raise ValueError('Malformed DXF section')
            section = pairs[index+1][1]; seen_entities |= section == 'ENTITIES'
            index += 2; continue
        if code == 0 and value == 'ENDSEC':
            if entity is not None: entities.append(entity); entity = None
            section = None
        elif section == 'HEADER':
            header.append((code, value))
        elif section == 'ENTITIES':
            if code == 0:
                if entity is not None: entities.append(entity)
                entity = [(code, value)]
            elif entity is not None:
                entity.append((code, value))
        index += 1
    if section is not None or not seen_entities:
        raise ValueError('Incomplete DXF ENTITIES section')
    units = [int(header[i+1][1]) for i, p in enumerate(header[:-1])
             if p == (9, '$INSUNITS') and header[i+1][0] == 70]
    if len(units) != 1:
        raise ValueError('DXF requires one explicit $INSUNITS header')
    def record(kind, source, data, groups):
        return {'kind': kind, 'raw_text': '\n'.join(str(v) for p in groups for v in p),
                'source': {'method': VERSION, 'page_basis': 'CAD model space; no PDF page', **source},
                'data': data, 'review': {'status': 'unreviewed', 'issues': []}}
    records = [record('cad_header', {}, {'insunits': units[0], 'units': UNITS.get(units[0], (None,))[0]}, header)]
    handles = set()
    for groups in entities:
        values = {}
        for code, val in groups: values.setdefault(code, []).append(val)
        one = lambda c, default=None: values.get(c, [default])[0]
        handle = one(5)
        if not handle or handle in handles:
            raise ValueError('Missing/duplicate CAD handle; export cannot be traced uniquely')
        handles.add(handle)
        data = {'entity_type': one(0), 'groups': groups, 'text': one(1), 'geometry': None}
        if one(0) == 'LINE':
            try:
                if one(67, '0') != '0' or one(410, 'Model') != 'Model':
                    raise ValueError('Paper-space geometry is unsupported')
                if any(len(values.get(c, [])) != 1 for c in (10, 20, 11, 21)):
                    raise ValueError('LINE requires unique XY endpoints')
                a = [number(one(10)), number(one(20)), number(one(30, 0))]
                b = [number(one(11)), number(one(21)), number(one(31, 0))]
                horizontal = math.dist(a[:2], b[:2]); vertical = abs(a[2]-b[2])
                if horizontal > 1e-9 and vertical > 1e-9:
                    raise ValueError('Sloping 3D centerline is unsupported')
                if max(horizontal, vertical) <= 1e-9:
                    raise ValueError('Zero-length centerline')
                data['geometry'] = {'start': a, 'end': b, 'length': math.dist(a, b),
                                    'component': 'horizontal' if horizontal > 1e-9 else 'riser'}
            except (ValueError, TypeError) as exc:
                data['unsupported_reason'] = str(exc)
        else:
            data['unsupported_reason'] = 'Only LINE centerlines are measured; other entities retained as evidence'
        records.append(record('cad_entity', {'handle': handle, 'layer': one(8), 'layout': one(410, 'Model')}, data, groups))
    return records


def _path(cfg, relative):
    root = Path(cfg['source_directory']).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root): raise ValueError('Drawing/BOQ reference must stay inside source root')
    return str(path)


def _find_boq(conn, cfg, states, plan):
    locator = plan['boq']; path = _path(cfg, locator['file'])
    found = []
    for state in states:
        if state['path'] != path or state['role'] != 'boq': continue
        for rid in state['record_ids']:
            fact = items.core_fact(conn, rid); src = fact['record']['source']
            if src.get('sheet') == locator['sheet'] and src.get('row') == locator['row'] and 'quantity' in fact['record']['data'].get('fields', {}):
                found.append(fact)
    if len(found) != 1: raise ValueError('BOQ locator must resolve to one current quantity row')
    return found[0]


def _overlap(a, b):
    """Detect positive collinear overlap in metres, including reversed duplicates."""
    p, q = a; r, s = b
    v = [q[i]-p[i] for i in range(3)]; length = math.dist(p, q)
    unit = [x/length for x in v]
    def projection(t):
        offset = [t[i]-p[i] for i in range(3)]
        along = sum(offset[i]*unit[i] for i in range(3))
        away = math.sqrt(sum((offset[i]-along*unit[i])**2 for i in range(3)))
        return along, away
    rr, rd = projection(r); ss, sd = projection(s)
    return rd < 1e-7 and sd < 1e-7 and min(length, max(rr, ss))-max(0., min(rr, ss)) > 1e-7


def measure(conn, cfg, states, plan, tolerance):
    result = {'check_id': plan['id'], 'item_ids': [], 'boq': None, 'drawing_quantity': None,
              'horizontal_quantity': None, 'verified_riser_quantity': None, 'difference': None,
              'unit': None, 'status': 'unable_to_verify', 'review_status': 'Unreviewed screening',
              'measurement_basis': VERSION + '; model-space LINE centerlines, never annotation totals',
              'coverage': plan.get('coverage', {}), 'limitations': [], 'drawing_references': [],
              'tolerance': tolerance, 'tolerance_is_engineering_acceptance': False,
              'evidence_record_ids': [], 'duplicate_handles': []}
    try:
        boq = _find_boq(conn, cfg, states, plan); fields = boq['record']['data']['fields']
        quantity = fields['quantity']; original = number(quantity['value']); unit = quantity.get('unit')
        result['boq'] = {'original_value': quantity['value'], 'unit': unit, 'citation': boq['citation']}
        result['evidence_record_ids'].append(boq['id']); result['unit'] = unit
        result['item_ids'] = [r[0] for r in conn.execute('SELECT DISTINCT item_id FROM master_procurement_links WHERE project_id=? AND record_id=? AND field=?', (cfg['project_id'], boq['id'], 'quantity'))]
        if original < 0 or unit not in LENGTH_UNITS: raise ValueError('Only nonnegative BOQ length quantities with known units are supported')
        if not quantity.get('count_basis') or quantity['count_basis'] != plan.get('scope'):
            raise ValueError('BOQ scope must be documented and exactly match check scope')
        identity = plan.get('identity', {})
        if not {'service', 'size'} <= set(identity) or not plan.get('identity_basis'):
            raise ValueError('Explicit item service/size and source-based identity rationale required')
        for name, value in identity.items():
            if str(fields.get(name, {}).get('value', '')).strip().casefold() != str(value).strip().casefold():
                raise ValueError('BOQ item identity mismatch: '+name)
        coverage = plan.get('coverage', {})
        if not isinstance(coverage.get('complete'), bool) or not isinstance(coverage.get('missing'), list) or not coverage.get('basis'):
            raise ValueError('Explicit coverage, omitted scope and reviewed coverage basis required')
        if not plan.get('drawings'): raise ValueError('No drawing geometry selected')
        segments = []; horizontal = riser = 0.; counted = 0
        for selection in plan['drawings']:
            try:
                path = _path(cfg, selection['file'])
                source = next((s for s in states if s['path'] == path and s['status'] == 'STORED'), None)
                if not source: raise ValueError('Drawing is missing, unreadable or has no stored geometry: '+selection['file'])
                if not selection.get('sha256') or source['source_sha'] != selection['sha256']:
                    raise ValueError('Drawing hash changed; re-review scope and revision')
                if selection.get('scope') != plan['scope'] or selection.get('identity') != identity:
                    raise ValueError('Drawing scope/item identity does not match this BOQ check')
                if not selection.get('identity_basis') or not selection.get('revision') or not selection.get('revision_basis'):
                    raise ValueError('Documented drawing identity and applicable revision basis required')
                records = [items.core_fact(conn, rid) for rid in source['record_ids']]
                heads = [r for r in records if r['kind'] == 'cad_header']
                if len(heads) != 1: raise ValueError('No supported ASCII DXF header')
                actual_unit = heads[0]['record']['data']['units']
                if actual_unit not in LENGTH_UNITS or actual_unit != selection.get('units'):
                    raise ValueError('Unknown or inconsistent DXF units')
                entities = {r['citation']['handle']: r for r in records if r['kind'] == 'cad_entity'}
                revision_ref = entities.get(selection.get('revision_handle'))
                revision_text = revision_ref['record']['data'].get('text') if revision_ref else None
                if not revision_text or not re.search(r'\bREVISION\s*:\s*'+re.escape(selection['revision'])+r'(?![\w.-])', revision_text, re.I):
                    raise ValueError('Applicable revision not verified against the selected title entity')
                if selection.get('scale') != 1: raise ValueError('Only calibrated 1:1 model-space geometry is supported')
                calibration = selection.get('calibration', {})
                ref = entities.get(calibration.get('handle')); label = entities.get(calibration.get('label_handle'))
                geom = ref['record']['data'].get('geometry') if ref else None
                label_text = label['record']['data'].get('text') if label else None
                expected = number(calibration.get('length')); cal_unit = calibration.get('unit')
                if not geom or not label_text or expected <= 0 or cal_unit not in LENGTH_UNITS:
                    raise ValueError('Independent calibration LINE and documented length label required')
                if calibration.get('label') != label_text or not re.search(r'(?<![\d.])'+re.escape(str(calibration['length']))+r'\s*'+re.escape(cal_unit)+r'\b', label_text):
                    raise ValueError('Calibration value/unit not present in exact cited label')
                if not math.isclose(geom['length']*LENGTH_UNITS[actual_unit], expected*LENGTH_UNITS[cal_unit], rel_tol=1e-6, abs_tol=1e-9):
                    raise ValueError('Calibration/scale mismatch; no adjustment toward BOQ permitted')
                result['evidence_record_ids'] += [heads[0]['id'], revision_ref['id'], ref['id'], label['id']]
                result['drawing_references'].append({'file': selection['file'], 'sha256': source['source_sha'],
                    'revision': selection['revision'], 'revision_basis': selection['revision_basis'],
                    'scope': selection['scope'], 'units': actual_unit, 'scale': 1,
                    'calibration': calibration, 'handles': selection.get('handles', []),
                    'identity': identity, 'identity_basis': selection['identity_basis']})
                if not selection.get('handles') or not selection.get('layer'):
                    raise ValueError('Explicit comparable handles and item layer required')
                for handle in selection['handles']:
                    record = entities.get(handle)
                    if not record:
                        result['limitations'].append('Missing selected handle '+handle); continue
                    result['evidence_record_ids'].append(record['id'])
                    geometry = record['record']['data'].get('geometry')
                    if handle == calibration['handle'] or record['record']['source'].get('layer') != selection['layer']:
                        result['limitations'].append('Unverified item layer/identity for handle '+handle); continue
                    if not geometry:
                        result['limitations'].append('Unsupported selected handle '+handle+': '+record['record']['data'].get('unsupported_reason', 'no geometry')); continue
                    if geometry['component'] == 'riser' and not selection.get('risers_verified'):
                        result['limitations'].append('Unverified drop/riser '+handle); continue
                    points = [[x*LENGTH_UNITS[actual_unit] for x in geometry[k]] for k in ('start', 'end')]
                    if any(_overlap(points, old) for old in segments):
                        result['duplicate_handles'].append(handle)
                        result['limitations'].append('Duplicate/overlapping view excluded: '+handle); continue
                    segments.append(points); counted += 1
                    length = geometry['length']*LENGTH_UNITS[actual_unit]/LENGTH_UNITS[unit]
                    if geometry['component'] == 'horizontal': horizontal += length
                    else: riser += length
            except (ValueError, KeyError, TypeError) as exc:
                result['limitations'].append(str(exc))
        if counted:
            result.update(drawing_quantity=round(horizontal+riser, 9), horizontal_quantity=round(horizontal, 9),
                          verified_riser_quantity=round(riser, 9))
            complete = coverage['complete'] and not coverage['missing'] and not result['limitations']
            if complete:
                difference = result['drawing_quantity']-original
                allowance = max(tolerance['absolute'], abs(original)*tolerance['relative'])
                result.update(difference=round(difference, 9), allowance=allowance,
                              status='close_within_review_tolerance' if abs(difference) <= allowance+1e-9 else 'material_discrepancy')
            else:
                result['status'] = 'partial_check'
                result['limitations'].append('No full-BOQ difference or conclusion for incomplete coverage')
    except (ValueError, KeyError, TypeError) as exc:
        result['limitations'].append(str(exc))
    result['evidence_record_ids'] = sorted(set(result['evidence_record_ids']))
    return result


def evaluate(conn, cfg, states, options):
    result = []
    for plan in options.get('quantity_checks', []):
        tolerance = options.get('quantity_tolerances', {}).get(plan.get('item_type'),
                     options.get('quantity_tolerances', {}).get('default', {'relative': .10, 'absolute': 0}))
        tolerance = {'relative': number(tolerance.get('relative', .10)), 'absolute': number(tolerance.get('absolute', 0)),
                     'basis': 'Configurable screening tolerance; not engineering acceptance'}
        if tolerance['relative'] < 0 or tolerance['absolute'] < 0: raise ValueError('Negative review tolerance')
        relevant = {plan.get('boq', {}).get('file')} | {s.get('file') for s in plan.get('drawings', [])}
        source_basis = [[s['file_id'], s['basis'], s['status']] for s in states
                        if any(p and _path(cfg, p) == s['path'] for p in relevant)]
        basis = key([plan, tolerance, source_basis, sha(Path(__file__))])
        previous = next((p for p in reversed(items.history(conn, cfg, ACTION)) if p['basis'] == basis), None)
        if previous and all(conn.execute('SELECT 1 FROM records WHERE id=?', (rid,)).fetchone() for rid in previous['result']['evidence_record_ids']):
            result.append(previous['result']); continue
        measured = measure(conn, cfg, states, plan, tolerance)
        items.audit(conn, cfg, ACTION, {'basis': basis, 'plan': plan, 'result': measured})
        result.append(measured)
    return result
