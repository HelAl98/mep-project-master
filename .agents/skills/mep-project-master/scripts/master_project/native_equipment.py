"""B-01 query-only projection of native evidence. No schema, matching or approval writes."""
import json
from .evidence_reader import decoded

CONTRACT='mep-equipment-profile/1'


def page(reader,items,limit,offset,*,gaps=()):
    reader.bounds(limit,offset)
    return {'status':'AVAILABLE' if items else 'NO_RECORDED_EVIDENCE','items':items[offset:offset+limit],
            'total':len(items),'limit':limit,'offset':offset,'next_offset':offset+limit if offset+limit<len(items) else None,
            'equipment_contract':CONTRACT,'coverage_limitations':list(gaps)}


def profiles(reader,family=None,history=False,reference=None):
    base=reader.occurrence_basis(history)
    if base is None:return None
    # Preserve one native observation per reference; repeated tags never merge instances.
    rows=reader.conn.execute('SELECT * FROM ('+base+') ORDER BY normalized_tag,id',reader.params()).fetchall()
    if len(rows)>10000:raise ValueError('Native profile projection exceeds 10000 observations; narrow native intake')
    result=[]
    for row in rows:
        r=dict(row);data=decoded(r.get('data_json'));category=reader.row('eq_categories',r.get('category_id')) or {}
        name=category.get('name') or data.get('category')
        if family is not None and str(name or '').casefold()!=family.casefold():continue
        if reference is not None and reference.casefold() not in {str(v or '').casefold() for v in (r['id'],r.get('normalized_tag'),r.get('original_tag'))}:continue
        kind={'type':'Type','group':'Group'}.get(r.get('identity_kind'),'Reference')
        result.append({'schema_version':CONTRACT,'id':r['id'],'family':name,'normalized_tag':r.get('normalized_tag'),
            'profile_status':'AVAILABLE' if name and r.get('normalized_tag') else 'INCOMPLETE_MISSING_RECORDED_FAMILY_OR_TAG',
            'original_tag':r.get('original_tag'),'original_tags':[r['original_tag']] if r.get('original_tag') else [],
            'identity_kind':kind,'description':data.get('description'),'native_target':{'table':'eq_occurrences','id':r['id']},
            'native_observation_ids':[r['id']],'is_active':bool(r['is_active']),'review_status':'Unreviewed',
            'identity_basis':'SOURCE_REFERENCE_ONLY; repeated tags remain separate candidate references; no physical-instance approval inferred',
            'physical_quantity':None,'coverage_limitations':['No grouping or physical counts inferred.','Family is recorded native category, not new semantic classification.'],
            'provenance':reader.provenance('eq_occurrences',r,decoded(r.get('source_json')),r['file_id'],r['version_id'])})
    return result


def selected_observations(reader,reference,history=False):
    sql=reader.selection(reference,history)
    return [] if sql is None else [dict(r) for r in reader.conn.execute('SELECT * FROM ('+sql+') ORDER BY id',reader.params(reference))]


def context(reader,reference,role,history,limit,offset):
    rows=selected_observations(reader,reference,history);initial={r['id'] for r in rows};byid={r['id']:r for r in rows}
    links={}
    # Only explicit native relationship endpoints, never equal tags or arbitrary match pairs.
    if reader.has('eq_relationships','id','project_id','occurrence_id','target_occurrence_id','kind','evidence_json'):
        for link in reader.conn.execute('SELECT * FROM eq_relationships WHERE project_id=? ORDER BY id',(reader.cfg['project_id'],)):
            if link['occurrence_id'] not in initial and link['target_occurrence_id'] not in initial:continue
            other=link['target_occurrence_id'] if link['occurrence_id'] in initial else link['occurrence_id']
            targets=selected_observations(reader,other,history)
            for target in targets:
                byid[target['id']]=target;links.setdefault(target['id'],[]).append(dict(link))
    items=[]
    for row in byid.values():
        if role and row['role']!=role:continue
        if row['role'] not in ('boq','electrical','bms','drawing','schedule'):continue
        data=decoded(row['data_json']);obs=reader.observation(row)
        items.append({'evidence_id':row['id'],'profile_id':reference,'role':row['role'],
            'raw_text':data.get('description') or obs['raw_text'],'recorded_fields':data,
            'relationship':'native_recorded_relationship' if row['id'] in links else 'same_source_observation',
            'relationship_basis':{'native_relationships':links.get(row['id'],[]),'scope':'Recorded endpoints only; current applicability UNKNOWN'},
            'relationship_status':'Pending','item_code':data.get('item_number'),'description':data.get('description'),
            'quantity_as_printed':data.get('quantity'),'unit_as_printed':data.get('quantity_unit'),
            'installation_location':data.get('installation_location'),'area_served':data.get('area_served'),
            'provenance':obs['provenance']})
    return page(reader,items,limit,offset,gaps=['No unrecorded BOQ/electrical/BMS associations inferred; missing counterparts are coverage gaps.'])


def specifications(reader,reference,section,applicability,history,limit,offset,evidence_ids):
    if not isinstance(evidence_ids,(list,tuple)) or len(evidence_ids)>300 or any(not isinstance(v,str) or not v for v in evidence_ids):
        raise ValueError('At most 300 exact specification core record IDs')
    if len(set(evidence_ids))!=len(evidence_ids):raise ValueError('Duplicate specification evidence IDs')
    observations=selected_observations(reader,reference,history);occ_ids={r['id'] for r in observations}
    if not observations:raise ValueError('Specification selection requires an available equipment source reference')
    links={};gaps=[]
    if reader.has('eq_entity_sources','project_id','entity_id','occurrence_id') and reader.has('tr_links','project_id','entity_id','requirement_id','id','basis_hash') and reader.has('tr_requirements','project_id','id','core_record_id'):
        for r in reader.conn.execute('''SELECT l.*,q.core_record_id FROM tr_links l JOIN tr_requirements q
            ON q.id=l.requirement_id AND q.project_id=l.project_id WHERE l.project_id=? ORDER BY l.id''',(reader.cfg['project_id'],)):
            members={v[0] for v in reader.conn.execute('SELECT occurrence_id FROM eq_entity_sources WHERE project_id=? AND entity_id=?',(reader.cfg['project_id'],r['entity_id']))}
            if not members&occ_ids:continue
            if not r['core_record_id']:gaps.append('Recorded technical link without a core clause locator is not projected');continue
            links.setdefault(r['core_record_id'],[]).append(dict(r))
    wanted=set(evidence_ids)|set(links);items=[]
    for identity in sorted(wanted):
        record=reader.row('records',identity)
        if not record or record.get('kind')!='specification':
            if identity in evidence_ids:raise ValueError('Explicit clause is not available native specification evidence: '+identity)
            gaps.append('Unavailable linked core clause: '+identity);continue
        citation=reader.get_provenance(identity,table='records')['items']
        if not citation:raise ValueError('Clause has no registered project source: '+identity)
        prov=citation[0];original=prov.get('original_source') or {}
        heads=reader.source_version_basis([original.get('file_id')]);head=heads.get(original.get('file_id')) or {}
        if not history and (head.get('version_id')!=original.get('id') or head.get('status') in ('missing','error','excluded')):
            if identity in evidence_ids:raise ValueError('Explicit clause cites inactive/unavailable source head: '+identity)
            gaps.append('Historical linked clause excluded: '+identity);continue
        if not history and reader.has('activations','logical_key','version_id'):
            version=reader.row('versions',record['version_id']) or {}
            active=reader.conn.execute('SELECT version_id FROM activations WHERE logical_key=? ORDER BY rowid DESC LIMIT 1',(version.get('logical_key'),)).fetchone()
            if active and active[0]!=record['version_id']:raise ValueError('Specification extraction is historical: '+identity)
        payload=decoded(record['payload_json']);src=payload.get('source',{});data=payload.get('data',{})
        saved_section=src.get('spec_section') or data.get('spec_section')
        if section is not None and str(saved_section)!=str(section):continue
        if applicability is not None and applicability.casefold()!='pending':continue
        items.append({'evidence_id':identity,'profile_id':reference,'exact_original_paragraph_text':record['raw_text'],
            'section':saved_section,'section_title':data.get('section_title'),'clause':src.get('clause'),
            'paragraph_number':src.get('paragraph'),'physical_pdf_page':src.get('pdf_page'),
            'verified_printed_page':src.get('printed_page') if src.get('printed_page_verified') is True else None,
            'printed_page_as_recorded':src.get('printed_page'),'recorded_fragments':data.get('fragments'),
            'classification':'unreviewed_requirement_paragraph_candidate','applicability_status':'Pending',
            'relationship':'explicit_user_selected_clause' if identity in evidence_ids else 'native_recorded_equipment_requirement_link',
            'native_links':links.get(identity,[]),'native_link_currency':'UNKNOWN_NOT_REVALIDATED','condition':None,
            'applicability_scope':'Explicit selection or recorded entity link only; no approved applicability inferred',
            'provenance':prov})
    return page(reader,items,limit,offset,gaps=[*gaps,'Unlinked fragments remain unselected; selections and native links are Pending, never reviewed approvals.'])
