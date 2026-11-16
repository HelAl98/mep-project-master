"""Append-only item/evidence indexes in the existing engineering SQLite DB."""
from collections import defaultdict
import json
import re
import uuid

from .common import encoded, key, now
from .procurement_evidence import classify, norm, DEFINING, EQUIPMENT

TABLES={
 'master_procurement_sources':'''id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_id TEXT NOT NULL,
 source_sha TEXT NOT NULL, basis TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL''',
 'master_procurement_items':'''id TEXT PRIMARY KEY, project_id TEXT NOT NULL, category TEXT NOT NULL,
 identity_json TEXT NOT NULL, created_at TEXT NOT NULL''',
 'master_procurement_links':'''id TEXT PRIMARY KEY, project_id TEXT NOT NULL, item_id TEXT NOT NULL,
 record_id TEXT NOT NULL REFERENCES records(id), field TEXT, relation TEXT NOT NULL,
 basis TEXT NOT NULL, created_at TEXT NOT NULL''',
}

def schema(conn):
    for table,definition in TABLES.items():
        conn.execute('CREATE TABLE IF NOT EXISTS '+table+'('+definition+')')
        for operation in ('UPDATE','DELETE'):
            conn.execute('CREATE TRIGGER IF NOT EXISTS '+table+'_'+operation+' BEFORE '+operation+' ON '+table+
                " BEGIN SELECT RAISE(ABORT,'Append-only procurement history'); END")
        conn.execute('CREATE TRIGGER IF NOT EXISTS '+table+'_INSERT BEFORE INSERT ON '+table+
            " WHEN EXISTS(SELECT 1 FROM "+table+" WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Immutable procurement ID'); END")
    conn.commit()

def insert(conn,table,values):
    if conn.execute('SELECT 1 FROM '+table+' WHERE id=?',(values['id'],)).fetchone():return
    names=list(values)
    conn.execute('INSERT INTO '+table+'('+','.join(names)+') VALUES('+','.join('?' for _ in names)+')',[values[k] for k in names])

def audit(conn,cfg,action,payload,actor='Main Agent',reason='Requested mechanical procurement workflow'):
    event={'id':uuid.uuid4().hex,'project_id':cfg['project_id'],'scope_id':cfg.get('scope',{}).get('id','project'),
           'action':action,'actor':actor,'reason':reason,'payload_json':encoded(payload),'created_at':now()}
    insert(conn,'master_operator_events',event)
    return event['id']

def history(conn,cfg,action):
    return [json.loads(r[0]) for r in conn.execute('SELECT payload_json FROM master_operator_events WHERE project_id=? AND action=? ORDER BY rowid',
                                                  (cfg['project_id'],action))]

def identity(cfg,record,record_id):
    fields=record['data'].get('fields',{})
    get=lambda f:fields.get(f,{}).get('value')
    category=classify(get('item_type'))
    if category=='other':category=classify(get('description'))
    tag=str(get('tag') or '').strip()
    kind={'reference':'Reference','type':'Type','group':'Group','instance':'Individual unit candidate',
          'physical instance':'Individual unit candidate'}.get(str(get('identity_kind') or '').strip().casefold(),'Reference')
    if category=='other' and tag:category=classify(tag)
    # Preserve numeric punctuation: 1.5, 15 and 1/5 must NEVER share a signature.
    attribute=lambda v:' '.join(str(v).strip().casefold().split()) if v is not None else ''
    attrs={f:attribute(get(f)) for f in set(DEFINING.get(category,('service','size','material','subtype')))|{'body_material'}}
    if not attrs.get('material') and attrs.get('body_material'):attrs['material']=attrs['body_material']
    required=DEFINING.get(category,('service','size','material','subtype'))
    missing=[f for f in required if not attrs.get(f)]
    loc=record['source']
    if tag:
        # Only exact tag plus compatible explicitly recorded system/service is a shared reference.
        from .procurement_evidence import helper
        native=helper(cfg['skills_root'],'mep-equipment-matcher','equipment_matcher/common.py')
        signature=['tag',native.tag(tag,native.default_config()),attribute(get('service')),kind]
        missing=[]
    else:
        # Extra characteristics and literal subtype/description conservatively prevent
        # merging a butterfly/gate valve or differing coating/thickness by omission.
        excluded={'tag','quantity','quantity_unit','description','item_number','location','duty'}
        attrs.update({f:attribute(data['value'])+'|'+attribute(data.get('unit'))
                      for f,data in fields.items() if f not in excluded and f not in attrs})
        if not get('subtype'):attrs['description_qualifier']=attribute(get('description'))
        signature=['material',category,attrs]
        if missing:signature+=['incomplete-source-reference',record['document_file_id'],loc.get('sheet'),loc.get('row'),loc.get('paragraph')]
    ident={'tag':tag or None,'kind':kind if tag else 'Material group' if not missing else 'Material reference',
           'attributes':attrs,'missing':missing,'item_number':get('item_number'),
           'description':get('description'),'service':get('service')}
    return key([cfg['project_id'],signature]),category,ident

def add_link(conn,cfg,item_id,record_id,field=None,relation='supported',basis='Exact stored source row'):
    if relation not in ('supported','candidate','direct','conditional'):raise ValueError('Unknown relationship')
    row=conn.execute('SELECT kind,payload_json FROM records WHERE id=?',(record_id,)).fetchone()
    if row is None:raise ValueError('Unknown core evidence record')
    if field is not None and field not in json.loads(row['payload_json']).get('data',{}).get('fields',{}):
        raise ValueError('Field is not present in the cited core evidence')
    if not conn.execute('SELECT 1 FROM master_procurement_items WHERE id=? AND project_id=?',(item_id,cfg['project_id'])).fetchone():
        raise ValueError('Unknown project item')
    value={'id':key([cfg['project_id'],item_id,record_id,field,relation,basis]),'project_id':cfg['project_id'],
           'item_id':item_id,'record_id':record_id,'field':field,'relation':relation,'basis':basis,'created_at':now()}
    insert(conn,'master_procurement_links',value);return value['id']

def index_records(conn,cfg,source,record_ids,scope=None):
    from .procurement_evidence import role_for
    # Power/control references describe a mechanical purchase item; never create
    # standalone electrical/BMS purchase scopes from these references implicitly.
    if role_for(source) in ('electrical','bms'):return
    for record_id in record_ids:
        row=conn.execute('SELECT payload_json FROM records WHERE id=?',(record_id,)).fetchone()
        record=json.loads(row[0])
        if not record.get('data',{}).get('fields'):continue
        record['document_file_id']=source['file_id']
        item_id,category,ident=identity(cfg,record,record_id)
        scope=scope or {}
        if scope.get('categories') and category not in scope['categories']:continue
        if scope.get('system') and norm(ident.get('service'))!=norm(scope['system']):continue
        if scope.get('tags') and norm(ident.get('tag')) not in {norm(t) for t in scope['tags']}:continue
        insert(conn,'master_procurement_items',{'id':item_id,'project_id':cfg['project_id'],'category':category,
              'identity_json':encoded(ident),'created_at':now()})
        for field in record['data']['fields']:add_link(conn,cfg,item_id,record_id,field)

def core_fact(conn,record_id):
    row=conn.execute('''SELECT r.*,v.filename,v.source_path,v.sha256,v.revision,v.archive_path,v.metadata_json
                       FROM records r JOIN versions v ON r.version_id=v.id WHERE r.id=?''',(record_id,)).fetchone()
    if not row:raise ValueError('Missing referenced evidence '+record_id)
    raw=dict(row);record=json.loads(row['payload_json']);source=record['source']
    raw['record']=record
    raw['citation']={'record_id':record_id,'version_id':row['version_id'],'filename':row['filename'],
        'path':row['source_path'],'sha256':row['sha256'],'revision':row['revision'],
        'archive_path':row['archive_path'],'pdf_page':source.get('pdf_page'),
        'page_basis':'physical original PDF page (one-based)' if source.get('pdf_page') else source.get('page_basis','Page unavailable'),
        'sheet':source.get('sheet'),'row':source.get('row'),'cell':source.get('cell'),
        'paragraph':source.get('paragraph'),'section':source.get('spec_section'),
        'clause':source.get('clause'),'heading':record.get('data',{}).get('section_title'),
        'drawing_number':source.get('drawing_number'),'handle':source.get('handle'),'layer':source.get('layer'),'bbox':source.get('bbox')}
    return raw

def field_basis(facts,field):
    return key(sorted((f['link_id'],f['citation']['sha256'],f['value'],str(f['unit'])) for f in facts if f['field']==field))

def project(conn,cfg,source_state,scope=None,item_ids=None,checks=None,clause_selection=None):
    scope=scope or {};current_ids=set();gaps=[];roles=set();source_basis=[]
    checks=checks or [];clause_selection=clause_selection or {}
    for source in source_state:
        source_basis.append([source['file_id'],source['source_sha'],source['basis'],source['status']])
        current_ids.update(source.get('record_ids',[]))
        roles.add(source.get('role'))
        gaps+=source.get('gaps',[])
    for role in ('boq','schedule','drawing','specification'):
        if role not in roles:gaps.append({'status':'Not provided in the available files','type':role,'affects':role+' evidence, coverage and comparison'})
    from .procurement_evidence import helper
    normalizer=helper(cfg['skills_root'],'mep-equipment-matcher','equipment_matcher/common.py')
    normalization_config=normalizer.config(cfg.get('matching_config'))
    cache={}
    all_items=[];decisions=history(conn,cfg,'procurement_field_decision_v1')
    for row in conn.execute('SELECT * FROM master_procurement_items WHERE project_id=? ORDER BY category,id',(cfg['project_id'],)):
        ident=json.loads(row['identity_json']);facts=[];clauses=[];context=[]
        for link in conn.execute('SELECT * FROM master_procurement_links WHERE item_id=? AND project_id=? ORDER BY rowid',(row['id'],cfg['project_id'])):
            if link['record_id'] not in current_ids:continue
            if link['record_id'] not in cache:cache[link['record_id']]=core_fact(conn,link['record_id'])
            raw=cache[link['record_id']];record=raw['record'];citation=raw['citation']
            if link['field'] is not None:
                field=record.get('data',{}).get('fields',{}).get(link['field'])
                if not field:continue
                facts.append({'link_id':link['id'],'record_id':link['record_id'],'field':link['field'],
                    **field,'relation':link['relation'],'basis':link['basis'],'citation':citation})
            elif raw['kind']=='specification':
                if link['basis'].startswith('Auto specification:') and link['id'] not in clause_selection.get('link_ids',[]):continue
                clauses.append({'record_id':link['record_id'],'link_id':link['id'],'text':record['raw_text'],
                               'relation':link['relation'],'basis':link['basis'],'citation':citation})
            else:
                context.append({'record_id':link['record_id'],'text':record['raw_text'],'relation':link['relation'],
                                'basis':link['basis'],'citation':citation})
        if not facts:continue
        if item_ids is not None and row['id'] not in item_ids:continue
        if scope.get('categories') and row['category'] not in scope['categories']:continue
        if scope.get('tags') and norm(ident['tag']) not in {norm(t) for t in scope['tags']}:continue
        if scope.get('system') and norm(ident.get('service'))!=norm(scope['system']):continue
        byfield=defaultdict(list)
        for f in facts:byfield[f['field']].append(f)
        findings=[];selected={};review_history=[];latest={}
        item_checks=[c for c in checks if row['id'] in c.get('item_ids',[])]
        for event in decisions:
            if event['item_id']!=row['id']:continue
            valid=event['field_basis']==decision_basis(facts,event['field'],item_checks)
            e={**event,'validity':'Current recorded choice' if valid else 'Requires Revalidation'}
            review_history.append(e);latest[event['field']]=e
        for field,event in latest.items():
            if event['validity']=='Current recorded choice' and event.get('link_id'):
                found=next((f for f in byfield[field] if f['link_id']==event['link_id']),None)
                if found:selected[field]=found
        unresolved=[field for field,event in latest.items() if event.get('disposition')=='leave_unresolved']
        stale=[field for field,event in latest.items() if event['validity']=='Requires Revalidation']
        for field in sorted(set(unresolved+stale)):
            selected.pop(field,None)
            findings.append({'field':field,'kind':'explicit_unresolved' if field in unresolved else 'stale_decision',
                'values':byfield.get(field,[]),'status':'Pending',
                'decision_needed':'This field was left unresolved or its decision basis changed; choose current evidence or exclude this item from issue.'})
        for field,fs in byfield.items():
            if field in ('description','item_type','tag','quantity_unit','item_number'):continue
            needs_unit=field in ('quantity','motor_power','voltage','flow','head')
            missing_units=[f for f in ([selected[field]] if field in selected else fs) if not f.get('unit')] if needs_unit else []
            if missing_units:
                findings.append({'field':field+'_unit','kind':'missing_information','values':missing_units,
                    'status':'Field not found in the sources reviewed',
                    'decision_needed':'Establish the printed unit before treating numerical values as comparable.'})
            values={(encoded(f['value']),str(f.get('unit')),str(f.get('context'))) for f in fs if f['relation'] in ('supported','direct')}
            candidates=[f for f in fs if f['relation'] in ('candidate','conditional')]
            if len(values)>1:
                supported=[f for f in fs if f['relation'] in ('supported','direct')]
                compatible=True;disagreement=False
                for other in supported[1:]:
                    left=normalizer.parameter({'name':field,'value':supported[0]['value'],'unit':supported[0].get('unit')},normalization_config)
                    right=normalizer.parameter({'name':field,'value':other['value'],'unit':other.get('unit')},normalization_config)
                    conflicts,unknown=normalizer.compatible_parameters({field:left},{field:right},normalization_config)
                    compatible=compatible and not unknown and other.get('context')==supported[0].get('context') and not missing_units
                    disagreement=disagreement or bool(conflicts)
                if field=='quantity':
                    compatible=compatible and bool(supported[0].get('count_basis')) and len({f.get('count_basis') for f in supported})==1
                if disagreement or not compatible:
                    findings.append({'field':field,'kind':'comparable_disagreement' if compatible else 'uncertain_association',
                        'values':fs,'decision_needed':'Choose the source value for this item and field, clarify the technical basis, or leave unresolved.',
                        'status':'Resolved by recorded field choice' if field in selected else 'Pending',
                        'comparison_method':'existing matcher parameter normalization; original values and units retained'})
            if candidates:findings.append({'field':field,'kind':'uncertain_association','values':candidates,
                'decision_needed':'Confirm that this evidence describes this item and the same operating/component basis.',
                'status':'Resolved by recorded field choice' if field in selected else 'Pending'})
        required=('description','quantity')+tuple(DEFINING.get(row['category'],()))
        for field in required:
            if field=='material' and 'body_material' in byfield:continue
            if field not in byfield:findings.append({'field':field,'kind':'missing_information','values':[],
                'decision_needed':'Supply or identify the missing field; do not infer zero or approval.','status':'Field not found in the sources reviewed'})
        if not clauses:findings.append({'field':'specifications','kind':'missing_information','values':[],
            'status':'Field not found in the sources reviewed','decision_needed':'Select relevant original clauses or retain the gap.'})
        # Deduplicate one clause per original core record; explicit direct selection supersedes a candidate display.
        dedup={}
        for cl in clauses:
            old=dedup.get(cl['record_id'])
            if old is None or cl['relation']=='direct':dedup[cl['record_id']]=cl
        omitted=clause_selection.get('omitted',{}).get(row['id'],[])
        if omitted:
            findings.append({'field':'specification_coverage','kind':'selection_limited','values':[],'status':'Pending',
                'decision_needed':str(len(omitted))+' matching clauses were not reviewed; narrow scope or raise the explicit selection limit.',
                'omitted_record_ids':omitted})
        for check in item_checks:
            if check['status']!='close_within_review_tolerance':
                findings.append({'field':'quantity_check','kind':check['status'],'values':byfield.get('quantity',[]),
                    'status':'Resolved by recorded field choice' if 'quantity' in selected else 'Pending',
                    'decision_needed':'Review measured coverage and choose the procurement quantity source; the BOQ value is never overwritten.',
                    'check_id':check['check_id']})
        current_description=next((f['value'] for f in facts if f['field']=='description'),ident.get('description'))
        item={'id':row['id'],'category':row['category'],'tag':ident['tag'],'identity_kind':ident['kind'],
              'description':current_description,'identity_missing':ident['missing'],
              'facts':facts,'clauses':list(dedup.values()),'context':context,'findings':findings,'selected':selected,'decisions':review_history,
              'unresolved_fields':unresolved,'stale_fields':stale,'quantity_checks':item_checks,'omitted_clause_ids':omitted,
              'written_quantities':[f for f in facts if f['field']=='quantity'],'calculated_quantity':None,
              'physical_quantity':None,'review_status':'Pending' if any(f['status']=='Pending' or f['kind']=='missing_information' for f in findings) else 'Unreviewed'}
        all_items.append(item)
    if item_ids is not None and set(item_ids)!={i['id'] for i in all_items}:raise ValueError('Requested item scope has absent/inactive/foreign items')
    buckets=defaultdict(list)
    for item in all_items:
        attrs=json.loads(conn.execute('SELECT identity_json FROM master_procurement_items WHERE id=?',(item['id'],)).fetchone()[0])['attributes']
        if not item['tag'] and attrs.get('size'):
            buckets[(item['category'],attrs.get('service'),attrs['size'])].append(item)
    for bucket in buckets.values():
        if len(bucket)>100:
            gaps.append({'status':'Field not found in the sources reviewed','type':'association_scope',
                         'affects':'More than 100 potentially related items; Main must narrow candidate review'})
            continue
        for index,left in enumerate(bucket):
            for right in bucket[index+1:]:
                for item,other in ((left,right),(right,left)):
                    item['findings'].append({'field':'item_association','kind':'uncertain_association',
                        'values':[f for i in (item,other) for f in i['facts'] if f['field'] in ('description','size','material','body_material','pressure_class','connection')],
                        'candidate_item_id':other['id'],'status':'Pending',
                        'decision_needed':'Keep these differing/incomplete material references separate, or explicitly associate the relevant source evidence before selecting field values.'})
    used_paths={f['citation']['path'] for i in all_items for f in i['facts']}
    used_paths|={c['citation']['path'] for i in all_items for c in i['clauses']+i['context']}
    selected_basis=[b for b in source_basis if any(s['file_id']==b[0] and s['path'] in used_paths for s in source_state)]
    value={'schema_version':'mep-procurement-view/1','project_id':cfg['project_id'],'project_name':cfg['project_name'],
           'items':all_items,'gaps':gaps,'source_basis':sorted(selected_basis),'scope':scope,
           'quantity_takeoff':'Only explicit BOQ-scoped calibrated ASCII DXF LINE checks; no full-project takeoff or tag counting.',
           'quantity_checks':[c for c in checks if item_ids is None or set(c.get('item_ids',[])) & {i['id'] for i in all_items}],
           'specification_selection':clause_selection,
           'design_review_complete':False}
    value['fingerprint']=key(value)
    return value


def decision_basis(facts,field,checks):
    original=field_basis(facts,field)
    return key([original,checks]) if field=='quantity' and checks else original


def issue_blockers(view):
    """Scoped procurement release, not an upstream engineering certification."""
    blockers=[]
    if not view.get('configuration_current',True):
        blockers.append({'item_id':'scope','field':'configuration','reason':'Resume after configuration changes'})
    for item in view['items']:
        for finding in item['findings']:
            # Separate material references remain separate, not implicitly merged.
            if finding['field']=='item_association':continue
            if finding['status']!='Resolved by recorded field choice':
                blockers.append({'item_id':item['id'],'field':finding['field'],'reason':finding['decision_needed']})
        if any(c['relation']!='direct' for c in item['clauses']):
            blockers.append({'item_id':item['id'],'field':'specification_applicability',
                             'reason':'Candidate/conditional clauses must be reviewed before issue'})
    return blockers
