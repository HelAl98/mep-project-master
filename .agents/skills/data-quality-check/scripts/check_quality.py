"""Evidence-linked MEP review findings, never engineering approval or an accuracy grade."""
import argparse
from collections import defaultdict
import copy
import itertools
import json
import math
from pathlib import Path
import re
import sys

DISCIPLINES = {'HVAC', 'Plumbing', 'Fire Fighting', 'Electrical', 'Low Current'}
# Small explicit dimensional table. No guessed units, density, motor efficiency, or voltage conversion.
UNITS = {
    'W': ('power', 1), 'kW': ('power', 1000), 'MW': ('power', 1000000),
    'm3/h': ('volume_flow', 1 / 3600), 'm\u00b3/h': ('volume_flow', 1 / 3600),
    'L/s': ('volume_flow', 0.001), 'l/s': ('volume_flow', 0.001), 'm3/s': ('volume_flow', 1),
    'Pa': ('pressure', 1), 'kPa': ('pressure', 1000), 'bar': ('pressure', 100000),
    'V': ('voltage', 1), 'kV': ('voltage', 1000), 'A': ('current', 1), 'Hz': ('frequency', 1),
    'mm': ('length', 0.001), 'cm': ('length', 0.01), 'm': ('length', 1),
    'm2': ('area', 1), 'm\u00b2': ('area', 1), 'm3': ('volume', 1), 'm\u00b3': ('volume', 1),
    '\u00b0C': ('temperature_celsius', 1), 'C': ('temperature_celsius', 1),
    'rpm': ('rotation_speed', 1), '%': ('percent', 1), '1': ('dimensionless', 1),
    'count': ('count', 1), 'text': ('text', 1),
}
EQUIPMENT_KINDS = {'equipment', 'equipment_candidate', 'tag_occurrence', 'equipment_tag', 'equipment_tag_occurrence'}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _missing(value):
    return value is None or value == ''


def _scope(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _validate(packages):
    if not isinstance(packages, list):
        raise ValueError('packages must be a list of mep-evidence/1 objects')
    for index, package in enumerate(packages):
        if not isinstance(package, dict) or package.get('schema_version') != 'mep-evidence/1':
            raise ValueError(f'Package {index} is not mep-evidence/1')
        document = package.get('document')
        if not isinstance(document, dict) or not isinstance(document.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', document['sha256']):
            raise ValueError(f'Package {index} requires the input source SHA-256')
        if not document.get('path') or not document.get('filename') or not document.get('media_type'):
            raise ValueError(f'Package {index} lacks source document identity')
        if not isinstance(package.get('records'), list):
            raise ValueError(f'Package {index} records must be a list')
        for record in package['records']:
            if not isinstance(record, dict) or not isinstance(record.get('source'), dict) or not isinstance(record.get('data'), dict):
                raise ValueError(f'Package {index} contains a record without source/data objects')


def check_quality(packages, config=None):
    """Return candidate findings with exact input refs. Mutates no packages or review states.

    Comparisons use explicit tag, discipline and scope. Without scope only the same source
    bytes can be compared. Repeated mentions are never converted to physical quantities.
    """
    _validate(packages)
    config = copy.deepcopy(config or {})
    patterns = config.get('tag_patterns', {})
    if not isinstance(patterns, dict) or not isinstance(config.get('tag_mapping', {}), dict):
        raise ValueError('tag_patterns and tag_mapping must be objects')
    try:
        patterns = {discipline: re.compile(pattern) for discipline, pattern in patterns.items()}
    except (TypeError, re.error) as error:
        raise ValueError(f'Invalid project tag pattern: {error}') from error
    tags = config.get('tag_mapping', {})
    findings = []
    quantities = defaultdict(list)
    mentions = defaultdict(list)
    parameters = defaultdict(list)
    inventories = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    equipment_index = defaultdict(list)
    count = 0

    def add(code, message, references, **details):
        # Deduplicate identical evidence references while retaining each input record identity.
        distinct = []
        seen = set()
        for reference in references:
            key = (reference['package_index'], reference['record_index'])
            if key not in seen:
                seen.add(key)
                distinct.append(copy.deepcopy(reference))
        findings.append({'code': code, 'status': 'candidate', 'severity': 'review', 'message': message,
                         'references': distinct, 'details': details})

    for pi, package in enumerate(packages):
        document = package['document']
        for ri, record in enumerate(package['records']):
            count += 1
            data = record['data']
            reference = {'package_index': pi, 'record_index': ri, 'document': copy.deepcopy(document),
                         'source': copy.deepcopy(record['source'])}
            discipline = data.get('discipline') or document.get('discipline')
            tag = data.get('tag')
            if isinstance(tag, str):
                tag = tags.get(tag, tag)
            elif tag is not None:
                add('invalid_tag', 'Equipment tag is not text.', [reference], value=tag)
                tag = None
            explicit_scope = data.get('scope')
            scope = _scope(explicit_scope) if not _missing(explicit_scope) else 'source:' + document['sha256']
            kind = record.get('kind')
            is_equipment = kind in EQUIPMENT_KINDS
            occurrence_only = bool(data.get('occurrence_only') or data.get('candidate') or kind != 'equipment')
            is_parameter = kind == 'parameter'
            if not (is_equipment or is_parameter or data.get('parameters')):
                continue
            if discipline not in DISCIPLINES:
                add('unknown_discipline', 'Discipline requires explicit project mapping.', [reference], value=discipline)
            if is_equipment:
                if _missing(tag):
                    add('missing_tag', 'Equipment evidence has no explicit tag.', [reference])
                elif discipline in patterns and not patterns[discipline].fullmatch(tag):
                    add('invalid_tag', 'Tag does not match the supplied project discipline pattern.', [reference], tag=tag)
                quantity = data.get('quantity')
                if quantity is not None and (not _number(quantity) or quantity < 0):
                    add('invalid_quantity', 'Quantity must be an explicitly extracted finite nonnegative number.', [reference], value=quantity)
                if tag:
                    key = (scope, discipline, tag)
                    mentions[key].append(reference)
                    equipment_index[key].append(reference)
                    if _number(quantity) and quantity >= 0 and not occurrence_only:
                        quantities[key].append((quantity, reference, data.get('quantity_unit')))
                    # Only explicit inventories are compared; annotation mentions supply no absent-set proof.
                    role = data.get('role')
                    if role in ('drawing', 'schedule') and not _missing(explicit_scope) and not occurrence_only:
                        inventories[(scope, discipline)][role][tag].append(reference)
            extracted = data.get('parameters', [])
            if not isinstance(extracted, list):
                add('invalid_parameter', 'parameters must be a list of named facts.', [reference])
                extracted = []
            if is_parameter:
                extracted = [data] + extracted
            required = config.get('required_parameters', {}).get(discipline, []) if is_equipment else []
            names = {p.get('name') for p in extracted if isinstance(p, dict) and isinstance(p.get('name'), str)}
            for required_name in required:
                if required_name not in names:
                    add('missing_parameter', 'An explicitly configured required parameter is absent.', [reference], name=required_name)
            for parameter in extracted:
                if not isinstance(parameter, dict) or not isinstance(parameter.get('name'), str) or not parameter['name'].strip():
                    add('invalid_parameter', 'Parameter requires an explicit name.', [reference])
                    continue
                name = parameter['name']
                value = parameter.get('value')
                unit = parameter.get('unit')
                if _missing(value):
                    add('missing_parameter', 'Parameter value is absent.', [reference], name=name)
                elif not _number(value) and not (unit == 'text' and isinstance(value, str)):
                    add('invalid_parameter', 'Numeric parameter is not a finite number; textual facts require unit=text.', [reference], name=name, value=value)
                if _missing(unit):
                    add('missing_unit', 'Parameter has no explicit unit.', [reference], name=name)
                elif not isinstance(unit, str) or unit not in UNITS:
                    add('unknown_unit', 'Unit is outside the small verified dimensional table; no equality assumed.', [reference], name=name, unit=unit)
                fact_scope = parameter.get('scope', explicit_scope)
                fact_scope_key = _scope(fact_scope) if not _missing(fact_scope) else 'source:' + document['sha256']
                fact_tag = parameter.get('tag', tag)
                fact_tag = tags.get(fact_tag, fact_tag) if isinstance(fact_tag, str) else None
                fact_discipline = parameter.get('discipline', discipline)
                if fact_tag:
                    parameters[(fact_scope_key, fact_discipline, fact_tag, name)].append((parameter, reference))

    for (scope, discipline, tag), references in mentions.items():
        per_document = defaultdict(list)
        for reference in references:
            per_document[reference['document']['sha256']].append(reference)
        for duplicates in per_document.values():
            if len(duplicates) > 1:
                add('repeated_tag_mentions', 'Repeated tag evidence requires review; mention count is not equipment quantity.', duplicates,
                    tag=tag, discipline=discipline, occurrence_count=len(duplicates))
    for (_, discipline, tag), entries in quantities.items():
        for (left, lref, lunit), (right, rref, runit) in itertools.combinations(entries, 2):
            if lunit != runit:
                add('incomparable_quantity', 'Quantities use different or missing quantity units.', [lref, rref], tag=tag,
                    left_unit=lunit, right_unit=runit)
            elif not math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-9):
                add('quantity_mismatch', 'Explicit quantities disagree for the same scoped equipment tag.', [lref, rref],
                    tag=tag, discipline=discipline, values=[left, right])
    for (scope, discipline), roles in inventories.items():
        if 'drawing' not in roles or 'schedule' not in roles:
            continue
        for present_role, missing_role in (('drawing', 'schedule'), ('schedule', 'drawing')):
            for tag in roles[present_role].keys() - roles[missing_role].keys():
                evidence = roles[present_role][tag] + list(itertools.chain.from_iterable(roles[missing_role].values()))
                add('missing_equipment', 'Tag is absent from the supplied comparable inventory; completeness requires engineering review.',
                    evidence, tag=tag, discipline=discipline, present_role=present_role, missing_role=missing_role)
    for (_, discipline, tag, name), entries in parameters.items():
        for (left, lref), (right, rref) in itertools.combinations(entries, 2):
            lu, ru = left.get('unit'), right.get('unit')
            lv, rv = left.get('value'), right.get('value')
            comparable = (isinstance(lu, str) and isinstance(ru, str) and lu in UNITS and ru in UNITS
                          and UNITS[lu][0] == UNITS[ru][0]
                          and left.get('operator', '=') in ('=', '==') and right.get('operator', '=') in ('=', '=='))
            if not comparable:
                add('incomparable_parameter', 'Scoped facts cannot be equated: unknown/different dimensions or non-equality operators.',
                    [lref, rref], tag=tag, name=name, units=[lu, ru])
                continue
            if lu == ru == 'text' and isinstance(lv, str) and isinstance(rv, str):
                equal = lv == rv
            elif _number(lv) and _number(rv):
                equal = math.isclose(lv * UNITS[lu][1], rv * UNITS[ru][1], rel_tol=1e-6, abs_tol=1e-9)
            else:
                continue
            if not equal:
                add('conflicting_parameter', 'Comparable scoped parameter values disagree; retained units and source facts need review.',
                    [lref, rref], tag=tag, discipline=discipline, name=name,
                    values=[{'value': lv, 'unit': lu}, {'value': rv, 'unit': ru}])
    for condition in config.get('cross_discipline_conditions', []):
        required = ('from_tag', 'from_discipline', 'requires_tag', 'required_discipline')
        if not isinstance(condition, dict) or any(not condition.get(key) for key in required):
            raise ValueError('Cross-discipline conditions require from_tag/from_discipline/requires_tag/required_discipline')
        from_tag = tags.get(condition['from_tag'], condition['from_tag'])
        target = tags.get(condition['requires_tag'], condition['requires_tag'])
        for (scope, discipline, tag), references in equipment_index.items():
            if tag != from_tag or discipline != condition['from_discipline'] or scope.startswith('source:'):
                continue
            if condition.get('scope') is not None and scope != _scope(condition['scope']):
                continue
            if (scope, condition['required_discipline'], target) not in equipment_index:
                add('cross_discipline_missing_equipment', 'An explicitly configured cross-discipline equipment condition is unmet.', references,
                    from_tag=tag, requires_tag=target, required_discipline=condition['required_discipline'])
    return {'status': 'review_required' if findings else 'no_findings_in_checked_subset', 'findings': findings,
            'packages_checked': len(packages), 'records_checked': count,
            'limitations': ['Candidate findings require engineering review; absence of findings is not approval.',
                            'Only supplied evidence is checked. No inferred physical quantities or complete drawing inventories.',
                            'Cross-document comparisons require explicit equal scope, discipline and tag.',
                            'Revision selection is the caller responsibility; activate the intended revisions before comparison.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', nargs='+', help='mep-evidence/1 JSON files')
    parser.add_argument('--config', help='Project tag patterns, mapping and explicit expectations JSON')
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        packages = [json.loads(Path(p).read_text(encoding='utf-8-sig')) for p in args.packages]
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig')) if args.config else None
        result = check_quality(packages, config)
        encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            with Path(args.output).open('x', encoding='utf-8') as target:
                target.write(encoded + '\n')
        else:
            print(encoded)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
