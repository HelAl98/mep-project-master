"""Mechanical procurement convenience operations within the existing Master.

No second scheduler: Registry, native adapters and ETL own source work; this facade
indexes item links, reuses core evidence and existing master audit/lock facilities.
"""
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .common import HOME, encoded, key, now, read, resolve, sha, write
from .memory import Memory, connect, project_lock
from .source_currency import load_config, stable_hash
from .procurement_evidence import helper, package_for, role_for, classify
from . import procurement_items as items

ACTION='mechanical_procurement_work_v1'

def _main(executor_role):
    if executor_role!='main':raise PermissionError('Only the Main Agent may write procurement state')

def _registry(skills):
    scripts=str(Path(skills)/'mep-document-registry/scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from mep_registry.scan import scan_project, choose_database
    return scan_project,choose_database

def prepare(root=None,*,config_path=None,state=None):
    """Resolve one existing project DB, or explicit native initialization paths."""
    root=Path(root or Path.cwd()).resolve(strict=True)
    if not root.is_dir():raise ValueError('Project root must be a directory')
    if config_path:
        cfg=load_config(config_path)
        for name in ('skills_root','registry_config','matching_config','review_config','package_config','quality_config'):
            if cfg.get(name):cfg[name]=str(resolve(Path(cfg['config_path']).parent,cfg[name]))
        return cfg
    state=Path(state).resolve() if state else root.parent/(root.name+'-mep')
    candidates=[root/'rules/master.json',state/'rules/master.json']
    existing=[p for p in candidates if p.is_file()]
    if len(existing)>1:
        configs=[load_config(p) for p in existing]
        if len({c['database'] for c in configs})>1:raise ValueError('Multiple project configurations; Main must resolve the intended existing DB')
    if existing:return load_config(existing[0])
    if state.is_relative_to(root):raise ValueError('Keep new state/output outside original sources')
    _,choose=_registry(HOME.parent)
    found=choose(root)
    db=found if found.is_file() else state/'state/engineering.sqlite'
    pid='mechanical-'+key(str(root))[:16]
    if db.is_file():
        from contextlib import closing
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
            projects=conn.execute('SELECT id,root_path FROM registry_projects').fetchall()
        matching=[p[0] for p in projects if Path(p[1]).resolve()==root]
        if len(matching)!=1:raise ValueError('Existing DB has no unique project for this root; do not create a competing database')
        pid=matching[0]
    cfg=read(HOME/'assets/config/project.example.json')
    cfg.update(project_id=pid,project_name=root.name,source_directory=str(root),database=str(db),
               output_directory=str(state/'outputs'),skills_root=str(HOME.parent))
    cfg['procurement']={'scope':{},'mappings':{},'automatic_until_human_decision':True}
    cfgpath=state/'rules/master.json';write(cfgpath,cfg);cfg['config_path']=str(cfgpath)
    return cfg

def _options(conn,cfg):
    options=dict(cfg.get('procurement',{}))
    if 'scope' not in options:
        parent=cfg.get('scope',{})
        options['scope']={k:v for k,v in {'system':parent.get('system'),'categories':parent.get('categories')}.items() if v}
    for event in items.history(conn,cfg,'procurement_options_v1'):
        options.update(event['options'])
    return options

def _last_state(conn,cfg):
    runs=items.history(conn,cfg,ACTION)
    states=json.loads(encoded(runs[-1].get('sources',[]))) if runs else []
    for interpretation in items.history(conn,cfg,'procurement_interpretation_v1'):
        for source in states:
            if interpretation['original_record_id'] in source['record_ids'] and interpretation['source_sha']==source['source_sha']:
                source['record_ids']=list(dict.fromkeys(source['record_ids']+interpretation['record_ids']))
    return states

def _snapshot(conn,cfg,scope=None,item_ids=None):
    options=_options(conn,cfg)
    runs=items.history(conn,cfg,ACTION);last=runs[-1] if runs else {}
    view=items.project(conn,cfg,_last_state(conn,cfg),scope if scope is not None else options.get('scope'),item_ids,
                       last.get('quantity_checks',[]),last.get('clause_selection',{}))
    view['configuration_current']=last.get('options_basis')==key(options)
    view['issue_blockers']=items.issue_blockers(view)
    view.pop('fingerprint',None);view['fingerprint']=key(view)
    return view

def snapshot(cfg,*,scope=None,item_ids=None):
    conn=connect(cfg)
    try:
        result=_snapshot(conn,cfg,scope,item_ids)
        result['source_currency_basis']='Saved work snapshot; issue/decision operations also check their live originals'
        return result
    finally:conn.close()

def _verify_citations(citations):
    for cit in citations:
        for field in ('path','archive_path'):
            check=stable_hash(cit[field])
            if check.get('sha256')!=cit['sha256']:raise ValueError('Source evidence requires revalidation: '+cit['filename'])

def _existing_core(conn,file,path):
    """Reuse exact same-byte native evidence from earlier workflows without parsing again."""
    rows=conn.execute('''SELECT r.payload_json,v.metadata_json,v.id FROM records r
                         JOIN versions v ON v.id=r.version_id
                         WHERE v.source_path=? AND v.sha256=? ORDER BY r.id LIMIT 100001''',
                         (str(path.resolve()),file['sha256'])).fetchall()
    if not rows or len(rows)>100000:return None
    records=[json.loads(r['payload_json']) for r in rows]
    allowed=('pdf-to-structured/','specification-extractor/','drawing-analyzer/',
             'master-procurement-native-paragraph/','master-procurement-recognized-header/2',
             'master-procurement-explicit-table/2')
    records=[r for r in records if r['source'].get('method','').startswith(allowed)]
    if not records:return None
    document=json.loads(rows[0]['metadata_json']);issues=[]
    for version in {r['id'] for r in rows}:
        for run in conn.execute('SELECT issues_json FROM runs WHERE version_id=?',(version,)):
            issues+=json.loads(run[0]).get('extraction_issues',[])
    return {'schema_version':'mep-evidence/1','document':document,'records':records,
            'issues':list({encoded(i):i for i in issues}.values())}

def _add_clause_candidates(conn,cfg,source_state,options):
    record_ids={r for s in source_state for r in s.get('record_ids',[])}
    clauses=[];paragraphs=[];references=[]
    from .procurement_rules import candidate_links
    selection=candidate_links(conn,cfg,source_state,options)
    interdisciplinary={r for s in source_state if s.get('role') in ('electrical','bms') for r in s.get('record_ids',[])}
    for rid in record_ids:
        row=conn.execute("SELECT kind,raw_text,payload_json FROM records WHERE id=?",(rid,)).fetchone()
        if row and row['kind']=='specification' and not row['raw_text'].strip().upper().startswith('SECTION '):
            clauses.append((rid,row['raw_text']))
        elif row and row['kind'] in ('paragraph','line'):paragraphs.append((rid,row['raw_text']))
        if row:
            fields=json.loads(row['payload_json']).get('data',{}).get('fields',{})
            if rid in interdisciplinary and fields.get('tag',{}).get('value'):references.append((rid,fields))
    for item in conn.execute('SELECT id,category,identity_json FROM master_procurement_items WHERE project_id=?',(cfg['project_id'],)):
        tag=json.loads(item['identity_json']).get('tag')
        if tag:
            import re
            exact=re.compile(r'(?<!\w)'+re.escape(tag)+r'(?!\w)',re.I)
            for rid,text in paragraphs+clauses:
                if exact.search(text):items.add_link(conn,cfg,item['id'],rid,relation='candidate',
                    basis='Literal tag mention in stored document; technical/discipline association unconfirmed')
            ident=json.loads(item['identity_json'])
            for rid,fields in references:
                if str(fields['tag']['value']).strip().casefold()!=tag.casefold():continue
                service=fields.get('service',{}).get('value')
                if service and ident.get('service') and str(service).casefold()!=str(ident['service']).casefold():continue
                relation='supported' if service and ident.get('service') and ident['kind']=='Reference' else 'candidate'
                for field in fields:
                    items.add_link(conn,cfg,item['id'],rid,field,relation,
                        'Exact tag and explicit service' if relation=='supported' else 'Exact tag; service/component basis still needs confirmation')
    return selection

def run_procurement(cfg,*,scope=None,options=None,executor_role='main'):
    _main(executor_role)
    root=Path(cfg['source_directory']).resolve(strict=True)
    out=Path(cfg['output_directory']).resolve()
    if out.is_relative_to(root) or out==root or out in root.parents:raise ValueError('Output must be separate from original sources')
    # Same native lock and DB as legacy stages, not an independent workflow database.
    with project_lock(cfg):
        scan,_=_registry(cfg['skills_root'])
        registry_rules=read(cfg['registry_config']) if cfg.get('registry_config') else None
        inventory=scan(root,cfg['database'],cfg['project_id'],registry_rules,cfg['skills_root'])
        memory=Memory(cfg,writable=True);items.schema(memory.conn)
        store=helper(cfg['skills_root'],'etl-pipeline','mep_store.py').Store(cfg['database'])
        states=[];processed=0;reused=0
        try:
            opts=_options(memory.conn,cfg)
            if options is not None:
                from .procurement_rules import validate_options
                validate_options(options)
                items.audit(memory.conn,cfg,'procurement_options_v1',{'options':options})
                opts.update(options);memory.conn.commit()
            if scope is not None:
                items.audit(memory.conn,cfg,'procurement_options_v1',{'options':{'scope':scope}})
                opts['scope']=scope
                memory.conn.commit()
            extraction_code=key([sha(Path(__file__).with_name('procurement_evidence.py')),sha(Path(__file__).with_name('procurement_geometry.py')),
                [(name,sha(Path(cfg['skills_root'])/name/'scripts'/script)) for name,script in [
                  ('pdf-to-structured','extract_pdf.py'),('specification-extractor','extract_specifications.py'),
                  ('drawing-analyzer','analyze_drawing.py'),('etl-pipeline','mep_store.py')]]])
            for file in inventory['files']:
                if cfg.get('scope',{}).get('file_ids') and file['file_id'] not in cfg['scope']['file_ids']:continue
                path=root/file['relative_path'];mapping=opts.get('mappings',{}).get(file['relative_path'],{})
                basis=key([file['sha256'],mapping,extraction_code,file.get('metadata'),role_for(file)])
                previous=memory.conn.execute('SELECT payload_json FROM master_procurement_sources WHERE project_id=? AND file_id=? AND basis=? ORDER BY rowid DESC LIMIT 1',
                                             (cfg['project_id'],file['file_id'],basis)).fetchone()
                old=json.loads(previous[0]) if previous else None
                if not path.is_file():
                    states.append({'file_id':file['file_id'],'source_sha':file.get('sha256'), 'basis':basis,'path':str(path),
                        'role':role_for(file),'status':'MISSING','record_ids':[],
                        'gaps':[{'status':'Source missing','file':str(path),'affects':'Source unavailable; independent items continue'}]})
                    continue
                # Negative deterministic results also reuse their exact source/code/mapping basis.
                # Dependency/access failures are retried; corrupt or unsupported unchanged bytes are not.
                if old and old['status']=='UNREADABLE' and all(g.get('error_type') in (None,'BadZipFile','UnicodeDecodeError','ValueError') for g in old.get('gaps',[])):
                    states.append(old);reused+=1;continue
                # Queryable records and verified archives are required for reuse, not JSON presence.
                if old and old['status']=='STORED' and all(store.conn.execute('SELECT 1 FROM records WHERE id=?',(r,)).fetchone() for r in old['record_ids']):
                    archive=stable_hash(file['archive_path'])
                    if archive.get('sha256')==file['sha256']:
                        items.index_records(memory.conn,cfg,file,old['record_ids'],opts.get('scope'))
                        memory.conn.commit()
                        states.append(old);reused+=1;continue
                state={'file_id':file['file_id'],'source_sha':file['sha256'],'basis':basis,'path':str(path),
                       'role':role_for(file),'status':'UNREADABLE','record_ids':[],'gaps':[]}
                try:
                    existing=_existing_core(store.conn,file,path) if not mapping else None
                    package,gap=package_for(file,path,cfg['skills_root'],mapping,existing)
                    if gap:state['gaps'].append(gap)
                    elif not package['records']:
                        state['gaps'].append({'status':'File present but unreadable or unsupported','file':str(path),
                            'affects':'No queryable extracted records; no stored extraction success claimed',
                            'reason':package['issues'] or 'No usable native content'})
                    else:
                        result=store.ingest(package)
                        # Actual ETL output is now queryable before we checkpoint/index it.
                        if any(not store.conn.execute('SELECT 1 FROM records WHERE id=?',(r,)).fetchone() for r in result['record_ids']):
                            raise ValueError('ETL returned non-queryable record IDs')
                        state.update(status='STORED',record_ids=result['record_ids'],run_id=result['run_id'])
                        state['gaps']+=[{'status':'File present but unreadable or unsupported' if any(w in str(i.get('code','')).casefold() for w in ('mapping','ocr','raster','unreadable')) else 'Field not found in the sources reviewed',
                           'file':str(path),'affects':'Extraction coverage / item links','reason':i} for i in package['issues']]
                        processed+=1
                except Exception as error:  # Isolate corrupt Office/PDF and parser failures to this source.
                    state['gaps'].append({'status':'File present but unreadable or unsupported','file':str(path),
                                         'affects':'This source only; independent work continues','reason':str(error),'error_type':type(error).__name__})
                items.insert(memory.conn,'master_procurement_sources',{'id':key([cfg['project_id'],file['file_id'],basis,state]),
                     'project_id':cfg['project_id'],'file_id':file['file_id'],'source_sha':file['sha256'],
                     'basis':basis,'payload_json':encoded(state),'created_at':now()})
                items.index_records(memory.conn,cfg,file,state['record_ids'],opts.get('scope'))
                memory.conn.commit();states.append(state)
            # Registry's current snapshot can omit deleted files: preserve missing-source distinction.
            present={s['file_id'] for s in states}
            for old_source in _last_state(memory.conn,cfg):
                if old_source['file_id'] not in present and not Path(old_source['path']).is_file():
                    states.append({**old_source,'status':'MISSING','record_ids':[],
                        'gaps':[{'status':'Source missing','file':old_source['path'],'affects':'Previously registered source is no longer available'}]})
            clause_selection=_add_clause_candidates(memory.conn,cfg,states,opts)
            from .procurement_geometry import evaluate
            quantity_checks=evaluate(memory.conn,cfg,states,opts)
            items.audit(memory.conn,cfg,ACTION,{'sources':states,'processed_sources':processed,'reused_sources':reused,
                'formal_stage_completion':False,'engineering_approval_created':False,'scope':opts.get('scope',{}),
                'options_basis':key(opts),'quantity_checks':quantity_checks,'clause_selection':clause_selection,
                'specialist_calls':[],'main_model':'Host runtime; no model assignment inferred by Python'})
            memory.conn.commit()
            view=_snapshot(memory.conn,cfg,scope)
            saved_findings={'view_fingerprint':view['fingerprint'],'gaps':view['gaps'],
                'findings':[{'item_id':i['id'],'field':f['field'],'kind':f['kind'],'status':f['status'],
                             'evidence_link_ids':[v['link_id'] for v in f['values']],
                             'decision_needed':f['decision_needed']}
                            for i in view['items'] for f in i['findings']]}
            previous_findings=items.history(memory.conn,cfg,'procurement_findings_v1')
            if not previous_findings or previous_findings[-1]['view_fingerprint']!=view['fingerprint']:
                items.audit(memory.conn,cfg,'procurement_findings_v1',saved_findings)
                memory.conn.commit()
        finally:store.close();memory.close()
        from .supplier_draft import render_procurement_items
        rendered=render_procurement_items(cfg,view,mode='review')
        questions=[{'item_id':i['id'],'item':i['tag'] or i['description'] or i['id'][:12],**finding}
                   for i in view['items'] for finding in i['findings']
                   if finding['status']!='Resolved by recorded field choice']
        return {'implemented_path':'master procurement items','status':'REVIEW_REQUIRED' if view['gaps'] or any(i['findings'] for i in view['items']) else 'DRAFT_READY',
            'items':len(view['items']),'processed_sources':processed,'reused_sources':reused,
            'fingerprint':view['fingerprint'],'deliveries':rendered,'database':cfg['database'],
            'config':cfg.get('config_path'),'gaps':view['gaps'],'decisions_needed':questions[:20],
            'quantity_checks':view['quantity_checks'],'specification_selection':view['specification_selection'],
            'issue_blockers':view['issue_blockers'],
            'additional_review_entries':max(0,len(questions)-20),'summary':
            'Available evidence was saved and review drafts prepared. Gaps and candidate links remain visible; no approval or physical quantity is inferred from repeated tags.'}

def decide(cfg,item_id,field,link_id,statement,actor,*,executor_role='main'):
    """Main records the user's exact chat disposition; no invented terminal confirmation."""
    _main(executor_role)
    if not isinstance(statement,str) or not statement.strip() or not isinstance(actor,str) or not actor.strip():
        raise ValueError('Actual human statement and attribution are required')
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            view=_snapshot(conn,cfg,item_ids=[item_id]);item=view['items'][0]
            fact=next((f for f in item['facts'] if f['link_id']==link_id and f['field']==field),None) if link_id else None
            if link_id and not fact:raise ValueError('Decision must select an actual current field evidence link')
            support=[f['citation'] for f in item['facts'] if f['field']==field]
            _verify_citations(support)
            payload={'schema_version':'mep-procurement-field-decision/1','item_id':item_id,'field':field,'link_id':link_id,
                     'statement':statement,'actor':actor,'field_basis':items.decision_basis(item['facts'],field,item.get('quantity_checks',[])),
                     'disposition':'select_source_value' if link_id else 'leave_unresolved',
                     'independently_authenticated':False,'created_at':now()}
            items.audit(conn,cfg,'procurement_field_decision_v1',payload,actor,statement);conn.commit()
            return payload
        finally:conn.close()

def link_evidence(cfg,item_id,record_id,*,field=None,relation='candidate',basis,executor_role='main'):
    _main(executor_role)
    if not str(basis).strip():raise ValueError('Association basis is required')
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            _snapshot(conn,cfg,item_ids=[item_id])
            active={r for s in _last_state(conn,cfg) for r in s.get('record_ids',[])}
            if record_id not in active:raise ValueError('Association needs current project evidence, not foreign/history data')
            _verify_citations([items.core_fact(conn,record_id)['citation']])
            lid=items.add_link(conn,cfg,item_id,record_id,field,relation,basis)
            items.audit(conn,cfg,'procurement_association_v1',{'item_id':item_id,'record_id':record_id,'field':field,
                'relation':relation,'basis':basis,'engineering_approval_created':False})
            conn.commit();return {'link_id':lid}
        finally:conn.close()

def configure(cfg,options,*,executor_role='main'):
    _main(executor_role)
    from .procurement_rules import validate_options
    validate_options(options)
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            items.audit(conn,cfg,'procurement_options_v1',{'options':options});conn.commit()
            return {'saved_options':options,'next':'Resume procurement; no user-managed intermediate files needed'}
        finally:conn.close()

def record_reasoning(cfg,receipt,*,executor_role='main'):
    """Audit native-host reasoning/fallback supplied by Main; never dispatch a model."""
    _main(executor_role)
    roles={'document_extractor','specification_analyst','cad_analyst','equipment_matcher','conflict_analyst','critical_reviewer'}
    if receipt.get('role') not in roles or not receipt.get('task_id') or not receipt.get('basis'):
        raise ValueError('Bounded configured role, task ID and evidence/question basis required')
    if receipt['role']=='critical_reviewer' and not receipt.get('explicit_user_request'):
        raise PermissionError('Critical review requires the actual explicit user request')
    if receipt.get('actual_model') and not receipt.get('runtime_evidence'):
        raise ValueError('A configured model is not verified runtime model evidence')
    if not receipt.get('runtime_evidence') and not receipt.get('fallback_reason'):
        raise ValueError('Record the supported Main fallback instead of inventing a model call')
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            active={r for s in _last_state(conn,cfg) for r in s.get('record_ids',[])}
            if not set(receipt.get('evidence_ids',[]))<=active:raise ValueError('Reasoning evidence must be current project records')
            payload={**receipt,'engineering_approval_created':False,'writer':'Main Agent'}
            items.audit(conn,cfg,'procurement_reasoning_v1',payload);conn.commit();return payload
        finally:conn.close()

def interpret(cfg,item_id,record_id,fields,excerpt,basis,*,executor_role='main'):
    """Main's bounded interpretation of stored text; no model call or hidden approval.

    Every selected value must literally occur in the cited excerpt. More complex
    semantic deductions stay unestablished instead of silently becoming facts.
    """
    _main(executor_role)
    if not fields or not isinstance(fields,dict) or not excerpt or not basis:
        raise ValueError('Exact fields, excerpt and interpretation basis required')
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            _snapshot(conn,cfg,item_ids=[item_id])
            active={r for s in _last_state(conn,cfg) for r in s.get('record_ids',[])}
            if record_id not in active:raise ValueError('Interpretation needs current stored project evidence')
            source=items.core_fact(conn,record_id)
            if excerpt not in source['record']['raw_text']:raise ValueError('Excerpt must be exact original text')
            for name,fact in fields.items():
                if not name or not isinstance(fact,dict) or fact.get('value') in (None,''):
                    raise ValueError('Interpretation field/value required')
                fact.setdefault('unit',None)
                import re
                literal=str(fact['value'])
                boundary=r'[\w.]' if re.match(r'^[+-]?\d',literal) else r'\w'
                if not re.search(r'(?<!'+boundary+')'+re.escape(literal)+r'(?!'+boundary+')',excerpt):
                    raise ValueError('Value must preserve its literal source wording')
                if fact.get('unit') and str(fact['unit']) not in excerpt:
                    raise ValueError('Unit must be explicitly present in the cited text')
            _verify_citations([source['citation']])
            record={'kind':'procurement_interpretation','raw_text':excerpt,
                'source':{**source['record']['source'],'method':'master-procurement-bounded-interpretation/1',
                          'original_record_id':record_id},
                'data':{'fields':fields,'original_record_id':record_id,'interpretation_basis':basis},
                'review':{'status':'unreviewed','issues':['INTERPRETATION_CANDIDATE_NOT_APPROVED']}}
            store=helper(cfg['skills_root'],'etl-pipeline','mep_store.py').Store(cfg['database'])
            try:
                result=store.ingest({'schema_version':'mep-evidence/1','document':json.loads(source['metadata_json']),
                                     'records':[record],'issues':[]})
            finally:store.close()
            for rid in result['record_ids']:
                for field in fields:items.add_link(conn,cfg,item_id,rid,field,'candidate',basis)
            payload={'item_id':item_id,'original_record_id':record_id,'source_sha':source['sha256'],
                     'record_ids':result['record_ids'],'basis':basis,'engineering_approval_created':False}
            items.audit(conn,cfg,'procurement_interpretation_v1',payload);conn.commit();return payload
        finally:conn.close()

def confirm_issue(cfg,item_ids,fingerprint,statement,actor,*,exclude_item_ids=None,executor_role='main'):
    _main(executor_role)
    if not item_ids or not isinstance(statement,str) or not statement.strip() or not isinstance(actor,str) or not actor.strip():
        raise ValueError('Exact item scope and actual human issue confirmation required')
    with project_lock(cfg):
        conn=connect(cfg,writable=True)
        try:
            view=_snapshot(conn,cfg,item_ids=item_ids)
            if view['fingerprint']!=fingerprint:raise ValueError('Reviewed scope/information changed; request a fresh human confirmation')
            excluded=set(exclude_item_ids or [])
            if not excluded<=set(item_ids) or excluded==set(item_ids):raise ValueError('Exclusions must leave a nonempty subset of the reviewed scope')
            reviewed_fingerprint=fingerprint
            if excluded:view=_snapshot(conn,cfg,item_ids=[i for i in item_ids if i not in excluded])
            blockers=items.issue_blockers(view)
            if blockers:raise ValueError('FOR ISSUE blocked for selected scope: '+encoded(blockers))
            citations=[f['citation'] for i in view['items'] for f in i['facts']]+[c['citation'] for i in view['items'] for c in i['clauses']]
            for item in view['items']:
                for check in item.get('quantity_checks',[]):
                    citations += [items.core_fact(conn,rid)['citation'] for rid in check['evidence_record_ids']]
            _verify_citations(citations)
            item_ids=[i['id'] for i in view['items']];fingerprint=view['fingerprint']
            confirmation={'item_ids':item_ids,'fingerprint':fingerprint,'statement':statement,'actor':actor,
                'excluded_item_ids':sorted(excluded),'reviewed_fingerprint':reviewed_fingerprint}
            items.audit(conn,cfg,'procurement_issue_authorization_v1',confirmation,actor,statement)
            conn.commit()
            from .supplier_draft import render_procurement_items
            deliveries=render_procurement_items(cfg,view,mode='issue',issue_confirmation=confirmation)
            payload={'schema_version':'mep-procurement-issue-confirmation/1','item_ids':item_ids,
                'fingerprint':fingerprint,'statement':statement,'actor':actor,'deliveries':deliveries,
                'independently_authenticated':False,'excluded_item_ids':sorted(excluded),'unresolved_included_items':False,
                'engineering_approval_inferred':False}
            items.audit(conn,cfg,'procurement_issue_confirmation_v1',payload,actor,statement);conn.commit()
            return {'mode':'issue',**payload}
        finally:conn.close()
