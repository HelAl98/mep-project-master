"""P1-05 scope/eligibility projection over the existing master, not another stage engine."""
from datetime import datetime,timezone
from copy import deepcopy
import json
from pathlib import Path
import importlib.util
import hashlib

from .common import HOME,key,read,sha,now,resolve
from .evidence import current_files
from .evidence_reader import EvidenceReader,decoded
from .supplier_draft import SupplierDraftGenerator

SCOPE='mep-operation-scope/1'
PLAN='mep-operation-plan/1'
OUTCOMES=('READY','READY_WITH_LIMITATIONS','BLOCKED','REQUIRES_HUMAN_ACTION','UNKNOWN')
EVIDENCE={'registration','extraction','equipment','parameters','specification_candidates','boq_context','electrical_context','bms_context'}


def operations():return read(HOME/'assets/config/operations.json')


def requirements(operation):
    row=next((r for r in operations() if r['id']==operation),None)
    if row is None:raise ValueError('Operation must be A, B, C, D or E')
    return row


def stable_work_basis(plan):
    """Only native cache discovery is volatile; requested work/evidence stay hashed."""
    basis=deepcopy(plan['fingerprint_basis'])
    native=basis.get('native_plan')
    if isinstance(native,dict):
        native.pop('reused',None)
        for action in native.get('actions',[]):
            if action.get('kind')=='existing_master_run_job':
                action.pop('cached_event_id',None)
                action.pop('reused',None)
    return basis


def identity(plan):return key(stable_work_basis(plan))


def _page_all(call,*args,max_items=10000,**kwargs):
    from .supplier_draft import pages
    return pages(call,*args,max_items=max_items,**kwargs)


def _equipment(reader,scope):
    families=scope.get('families',[]);wanted=scope.get('equipment_references',[])
    if not families and not wanted:return []
    rows={}
    for family in families or [None]:
        def listing(**page):return reader.list_equipment(family,**page)['result']
        items,cov=_page_all(listing,max_items=1000)
        if cov['status']=='UNSUPPORTED':raise ValueError('Saved equipment family/identity contract unavailable')
        for row in items:
            if not {'id','family','normalized_tag'}<=set(row):raise ValueError('Reader exposes references without supported saved profile identity; explicit consolidation capability gap')
            if not row['family'] or not row['normalized_tag']:raise ValueError('Incomplete recorded equipment family/tag; no grouping or identity will be invented')
            rows[row['id']]=row
    selected=[];found=set()
    for row in rows.values():
        if wanted:
            aliases={str(v).casefold() for v in [row['id'],row['normalized_tag'],*(row.get('original_tags') or [])]}
            matches={v for v in wanted if str(v).casefold() in aliases}
            if not matches:continue
            found.update(matches)
        selected.append(row)
    if set(wanted)-found:raise ValueError('Unresolved equipment references; scope will not broaden: '+str(sorted(set(wanted)-found)))
    if not selected:raise ValueError('No current saved equipment in selected scope')
    return sorted(selected,key=lambda r:(r['family'],r['normalized_tag'],r['id']))


def source_ids(value):
    """Only explicit original-source provenance, never filenames/nearby labels or audit inventories."""
    result=set()
    def walk(v):
        if isinstance(v,dict):
            original=v.get('original_source')
            if isinstance(original,dict) and original.get('file_id'):result.add(original['file_id'])
            for k,item in v.items():
                if k not in ('project_source_limitations','accepted_limitation','saved_limitation','basis','registered_heads'):
                    walk(item)
        elif isinstance(v,list):
            for item in v:walk(item)
    walk(value)
    return result


def _extractions(reader,sources):
    if not reader.has('versions','id','metadata_json','logical_key','sha256','source_path','filename') or not reader.has('records','id','version_id','kind','raw_text','payload_json'):
        return [],'Core extraction/version contract unavailable'
    matches=[]
    active=None
    if reader.has('activations','logical_key','version_id'):
        active={r[0] for r in reader.conn.execute('SELECT a.version_id FROM activations a WHERE a.rowid=(SELECT max(b.rowid) FROM activations b WHERE b.logical_key=a.logical_key)')}
    for r in reader.conn.execute('SELECT id,logical_key,sha256,source_path,filename,metadata_json FROM versions ORDER BY id'):
        row=dict(r);nested=decoded(row['metadata_json']).get('metadata',{})
        original=nested.get('supplied_metadata',{}).get('original_source',{})
        fid=nested.get('file_id') or original.get('file_id')
        if not fid:
            prefix='registry:'+reader.cfg['project_id']+':'
            fid=row['logical_key'][len(prefix):] if row['logical_key'].startswith(prefix) else None
        if fid not in sources:continue
        if active is not None and row['id'] not in active:continue
        cited=original.get('sha256') or row['sha256']
        if cited!=sources[fid]['sha256']:continue
        kinds={r[0]:r[1] for r in reader.conn.execute('SELECT kind,count(*) FROM records WHERE version_id=? GROUP BY kind',(row['id'],))}
        if not kinds:continue
        record_hash=hashlib.sha256()
        for record in reader.conn.execute('SELECT id,kind,raw_text,payload_json FROM records WHERE version_id=? ORDER BY id',(row['id'],)):
            record_hash.update(json.dumps(dict(record),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
            record_hash.update(b'\n')
        matches.append({'file_id':fid,'version_id':row['id'],'original_sha256':cited,'derived_identity':
            {'path':row['source_path'],'sha256':row['sha256']} if original else None,'record_kinds':kinds,
            'record_count':sum(kinds.values()),'records_sha256':record_hash.hexdigest(),'activation_basis':'Latest saved working activation, not revision approval' if active is not None else 'UNKNOWN_NO_ACTIVATION_CONTRACT',
            'lineage_basis':'Exact saved original file ID/hash; no parser rerun',
            'coverage':'STORED_RECORDS_ONLY_NOT_COMPLETE_DOCUMENT_COVERAGE'})
    return matches,None


def _limitations(reader,requested_ids,used):
    # Reuse original audit records; never reinterpret their old native authorization as a new exemption.
    rows=[];known={};retired=set()
    if reader.has('master_operator_events','project_id','action','payload_json'):
        for r in reader.conn.execute("SELECT id,action,payload_json FROM master_operator_events WHERE project_id=? AND action IN ('accepted_source_limitation','retired_source_limitation') ORDER BY rowid",(reader.cfg['project_id'],)):
            payload=decoded(r['payload_json']);receipt=payload.get('receipt',{})
            if r['action']=='retired_source_limitation':retired.add(receipt.get('limitation_id'));continue
            known[r['id']]=(payload,receipt)
    for identity,(payload,receipt) in known.items():
        hosts={h['file_id'] for ref in receipt.get('references',[]) for h in ref.get('hosts',[]) if h.get('file_id')}
        related=sorted(hosts&used)
        rows.append({'audit_id':identity,'requested':identity in requested_ids,'retired':identity in retired,
            'related_host_file_ids':related,'scope_role':'CONTEXT_ONLY_NOT_AN_OPERATION_EXEMPTION',
            'outside_selected_sources':not bool(related),'allowed_native_operations':receipt.get('allowed_operations',[]),
            'references':receipt.get('references',[]),'native_authorization':'REQUIRES_UNCHANGED_ORIGINAL_NATIVE_VALIDATOR',
            'receipt_file':payload.get('receipt_file')})
    missing=sorted(set(requested_ids)-set(known))
    return rows,missing


def _reviews(reader,equipment,required,clause_ids,source_heads):
    histories={}
    references={x for row in equipment for x in (row['id'],row['normalized_tag'],row['family'])}
    references.update(clause_ids)
    for reference in sorted(references):
        def listing(**page):return reader.get_decision_history(reference,**page)['result']
        items,_=_page_all(listing,max_items=10000)
        for item in items:histories[item['decision']['id']]=item
    if required.get('document_revision'):
        from .human_decisions import events,validity
        all_events=events(reader)
        for event in all_events:
            original=(event['original_evidence_and_version_basis']['target'].get('provenance') or {}).get('original_source') or {}
            if event['decision_type']=='document_revision' and original.get('file_id') in source_heads:
                histories[event['id']]={'decision':event,'validity':validity(reader,event,all_events)}
    summaries=[{'id':d['id'],'type':d['decision_type'],'target':d['target'],'scope':d.get('scope'),'recorded_result':d['result'],
        'validity':item['validity'],'reviewed_assertion':d['assertion'] if item['validity']['status']=='Accepted' and not item['validity']['test_only'] else None,
        'independently_authenticated':False} for item in histories.values() for d in [item['decision']]]
    valid=[item['decision'] for item in histories.values() if item['validity']['status']=='Accepted' and not item['validity']['test_only']]
    missing=[]
    for kind in ('identity','quantity'):
        if required.get(kind):
            if not equipment:missing.append({'type':kind,'reason':'Explicit saved equipment targets required for this review condition'})
            for row in equipment:
                found=any(d['decision_type']==kind and d['target']['id']==row['id'] and
                    (kind!='quantity' or d['assertion'].get('quantity_kind')=='physical_count') for d in valid)
                if not found:missing.append({'type':kind,'target':row['id'],'reason':'Missing valid scoped human assertion; no confirmation is invoked'})
    if required.get('specification_applicability'):
        if not clause_ids:missing.append({'type':'specification_applicability','reason':'Explicit clause review IDs required; no blanket family approval'})
        if not equipment:missing.append({'type':'specification_applicability','reason':'Explicit saved equipment targets required'})
        for clause in clause_ids:
            for row in equipment:
                def applies(d):
                    s=d.get('scope') or {}
                    return d['decision_type']=='specification_applicability' and d['target']['id']==clause and (
                        s.get('family')==row['family'] if s.get('kind')=='family' else s.get('table')==row.get('native_target',{}).get('table','uc_profiles') and s.get('id')==row['id'])
                if not any(applies(d) for d in valid):missing.append({'type':'specification_applicability','target':clause,'equipment_id':row['id'],'reason':'No valid assertion for this exact clause and equipment scope'})
    return summaries,missing,valid


def _snapshot_compatible(reader,head):
    snapshot=reader.currency_sources.get(head['file_id'])
    if not snapshot:return {'state':'UNKNOWN','reason':'no_matching_explicit_assessment_entry'}
    if snapshot.get('recorded_sha256')!=head['sha256'] or snapshot.get('version_id',head['version_id'])!=head['version_id']:
        return {'state':'UNVERIFIED','reason':'assessment_registered_version_basis_mismatch'}
    return {'state':snapshot.get('currency','UNVERIFIED'),'reason':'saved_assessment_not_live_source_verification',
            'live_sha256_at_assessment':snapshot.get('live_sha256')}


def _validated_scope(reader,request):
    if request.get('schema_version')!=SCOPE or request.get('project_id')!=reader.cfg['project_id']:
        raise ValueError('Requires matching project and mep-operation-scope/1')
    route=requirements(request.get('operation'))
    scope=request.get('scope',{})
    if not isinstance(scope,dict) or set(scope)-{'source_file_ids','families','equipment_references','source_selection'}:
        raise ValueError('Unsupported scope fields; implicit widening prohibited')
    for name in ('source_file_ids','families','equipment_references'):
        if not isinstance(scope.get(name,[]),list) or any(not isinstance(v,str) or not v for v in scope.get(name,[])):
            raise ValueError('Scope identifiers must be explicit nonempty strings')
        if len(set(scope.get(name,[])))!=len(scope.get(name,[])):raise ValueError('Duplicate scope identifiers')
    if scope.get('source_selection','explicit') not in ('explicit','equipment_evidence','registered_root'):
        raise ValueError('Unsupported source selection criterion')
    if not any(scope.get(k) for k in ('source_file_ids','families','equipment_references')) and scope.get('source_selection')!='registered_root':
        raise ValueError('Explicit document/equipment scope required; no default whole project')
    action=request.get('action',route['default_action'])
    if action not in route['actions']:raise ValueError('Operation action has no supported adapter')
    if request.get('execution_mode','guided') not in ('guided','automatic'):raise ValueError('Mode is guided or automatic; one specifically authorized operation per call')
    required=request.get('required_evidence',[])
    if not isinstance(required,list) or set(required)-EVIDENCE:raise ValueError('Unsupported required evidence type; semantics must not be guessed')
    policy=request.get('currency_policy',{})
    age=policy.get('max_snapshot_age_seconds',900)
    if type(age) is not int or not 1<=age<=3600:raise ValueError('Native snapshot age policy must be 1..3600 seconds')
    if not isinstance(request.get('output_directory'),str):raise ValueError('Explicit output directory required')
    out=resolve(Path(reader.cfg['config_path']).parent,request['output_directory'])
    if not out.is_relative_to(Path(reader.cfg['output_directory']).resolve()) or out==Path(reader.cfg['output_directory']).resolve():
        raise ValueError('New operation output must be a subdirectory of the configured output root')
    if out.is_relative_to(Path(reader.cfg['source_directory']).resolve()) or out.is_relative_to(Path(reader.cfg['database']).resolve().parent) or out.is_relative_to(HOME):
        raise ValueError('Operation output overlaps protected source/state/master')
    return route,scope,action,out


def assess_operation(reader,request):
    route,scope,action,out=_validated_scope(reader,request)
    blocked=[];unknown=[];human=[];warnings=[]
    native=action not in ('reuse','draft')
    all_heads={r['file_id']:r for r in current_files(reader)}
    equipment=_equipment(reader,scope)
    direct=set(scope.get('source_file_ids',[]))
    if scope.get('source_selection')=='registered_root':
        if route['id']!='A':raise ValueError('registered_root is only supported for Register & Scope')
        direct=set(all_heads)
    if direct-set(all_heads):raise ValueError('Unregistered requested sources: '+str(sorted(direct-set(all_heads))))
    projection={'equipment':[],'links':[],'stored_findings':[],'structural_checks':[]}
    used=set();counts={'registration':len(direct),'extraction':0,'equipment':len(equipment),'parameters':0,
        'specification_candidates':0,'boq_context':0,'electrical_context':0,'bms_context':0}
    compiled=None
    if route['id']=='E':
        options=request.get('supplier_options')
        if not isinstance(options,dict):blocked.append('Supplier Draft v1 options required')
        else:
            compiled=SupplierDraftGenerator(reader,options).compile()
            actual={(r['family'],r['tag']) for f in compiled['families'] for r in f['equipment']}
            expected={(r['family'],r['normalized_tag']) for r in equipment}
            if not expected or actual!=expected:blocked.append('Supplier options and selected equipment differ; no wider family export authorized')
            used=source_ids([compiled['families'],list(compiled['provenance'].values())])
            observation_basis=[]
            for row in equipment:
                native_observations,cov=_page_all(reader.get_observations,row['id'],max_items=10000)
                used.update(source_ids(native_observations))
                observation_basis.append({'equipment_id':row['id'],'observation_ids':[r['evidence_id'] for r in native_observations],
                    'observations_sha256':key(native_observations),'coverage':cov})
                if cov['status']=='UNSUPPORTED' or not native_observations:warnings.append('Identity observation lineage is incomplete for '+row['id'])
            counts['parameters']=sum(len(f['parameters']) for f in compiled['families'])
            counts['specification_candidates']=sum(len(f['specifications']) for f in compiled['families'])
            for role in ('boq','electrical','bms'):
                counts[role+'_context']=sum(1 for f in compiled['families'] for c in f['optional_context'] if c['role']==role)
            projection={'content_fingerprint':compiled['content_fingerprint'],'equipment_observation_basis':observation_basis,'family_summaries':[
                {'family':f['family'],'tags':[r['tag'] for r in f['equipment']],'parameter_rows':len(f['parameters']),
                 'specification_clauses':len(f['specifications']),'incomplete':f['incomplete']} for f in compiled['families']]}
            if any(f['incomplete'] for f in compiled['families']):warnings.append('Incomplete source evidence retained; draft only, quantities/identity not approved')
    elif route['id'] in ('C','D') and action=='reuse':
        if not equipment:blocked.append('Selected current saved equipment references required for read-only consolidation/check')
        families=set()
        for row in equipment:
            reference=row['id']
            observations,cov=_page_all(reader.get_observations,reference,max_items=10000)
            parameters,pcov=_page_all(reader.get_parameters,reference,max_items=10000)
            findings,fcov=_page_all(reader.get_findings,reference,max_items=10000)
            projection['equipment'].append({'identity':row,'observations':observations,'parameters':parameters,
                'coverage':{'observations':cov,'parameters':pcov},'physical_quantity':None})
            projection['stored_findings'].extend(findings);used.update(source_ids([observations,parameters,findings]));counts['parameters']+=len(parameters)
            if pcov['status']=='UNSUPPORTED':warnings.append('Parameter contract unavailable for '+reference)
            for parameter in parameters:
                if not parameter['provenance'].get('original_source'):
                    projection['structural_checks'].append({'evidence_id':parameter['evidence_id'],'finding':'MISSING_ORIGINAL_SOURCE_LINK','status':'UNREVIEWED'})
                if parameter.get('unit') is None:
                    projection['structural_checks'].append({'evidence_id':parameter['evidence_id'],'finding':'UNIT_NOT_PRINTED_OR_NOT_EXPOSED','status':'UNREVIEWED_NOT_A_DESIGN_CONFLICT'})
            if route['id']=='D':
                # Literal comparisons only within the same saved equipment/context/unit.
                # Never compare unlike units or infer design equivalence/approval.
                comparable={}
                for parameter in parameters:
                    name=parameter.get('original_name');value=parameter.get('original_printed_value')
                    if not name or value is None:continue
                    group=key([name,parameter.get('unit'),parameter.get('component_or_operating_context')])
                    comparable.setdefault(group,[]).append(parameter)
                for items in comparable.values():
                    if len({key(v['original_printed_value']) for v in items})>1:
                        projection['structural_checks'].append({'equipment_id':reference,
                            'finding':'DIFFERENT_PRINTED_VALUES_SAME_SAVED_PARAMETER_CONTEXT',
                            'evidence_ids':[v['evidence_id'] for v in items],
                            'values':[{'value':v['original_printed_value'],'unit':v.get('unit'),'provenance':v['provenance']} for v in items],
                            'status':'UNREVIEWED_CANDIDATE_DIFFERENCE','meaning':'Literal source difference only; no unit conversion or engineering conflict decision'})
                for role in ('boq','electrical','bms'):
                    context,ccov=_page_all(reader.get_context,reference,role=role,max_items=10000)
                    projection['links'].extend(context);used.update(source_ids(context));counts[role+'_context']+=len(context)
                    if ccov['status']=='UNSUPPORTED':warnings.append('Unsupported context relation: '+role)
                group=(row.get('run_id',reference),row['family'])
                if group not in families:
                    selection={'evidence_ids':request['specification_evidence_ids']} if 'specification_evidence_ids' in request else {}
                    page=reader.get_specifications(reference,limit=request.get('candidate_limit',25),offset=0,**selection)
                    projection['links'].append({'family':row['family'],'specification_candidates_page':page,
                        'scope':'EXACT_NATIVE_REFERENCE_CANDIDATES_NOT_APPROVED_REQUIREMENTS' if row.get('native_target') else 'SAVED_FAMILY_CANDIDATES_NOT_APPROVED_REQUIREMENTS'})
                    counts['specification_candidates']+=page['total'] or 0;used.update(source_ids(page));families.add(group)
        warnings.append('Saved identities, quantities and link candidates remain unreviewed unless separately valid decisions exist')
        if not counts['parameters']:warnings.append('No equipment schedule parameters available')
    else:
        used=direct.copy()
    for evidence_type in request.get('required_evidence',[]):
        if evidence_type in ('boq_context','electrical_context','bms_context') and counts[evidence_type]==0 and equipment:
            role=evidence_type.removesuffix('_context');checks=[]
            for row in equipment:
                items,cov=_page_all(reader.get_context,row['id'],role=role,max_items=10000)
                counts[evidence_type]+=len(items);used.update(source_ids(items))
                checks.append({'equipment_id':row['id'],'role':role,'coverage':cov,'context_ids':[v['evidence_id'] for v in items],
                               'evidence_sha256':key(items),'meaning':'Candidate source context only; not approved mechanical BOQ/quantity coverage'})
            projection.setdefault('required_context_checks',[]).extend(checks)
    if used and direct and not used<=direct:blocked.append('Evidence depends on sources outside explicit authorization: '+str(sorted(used-direct)))
    if used and not direct and scope.get('source_selection')!='equipment_evidence':
        blocked.append('Equipment supporting-source closure requires explicit equipment_evidence selection or exact source IDs')
    selected=direct|used if direct else used
    if used-set(all_heads):unknown.append('Supporting evidence contains unregistered source identities; source closure is incomplete')
    if not selected:blocked.append('No exact registered source basis could be resolved')
    exclusions=request.get('excluded_sources',[])
    if not isinstance(exclusions,list) or any(not isinstance(e,dict) or not e.get('file_id') or not e.get('reason') for e in exclusions):
        raise ValueError('Every excluded source needs exact file_id and reason')
    if {e['file_id'] for e in exclusions}&selected:blocked.append('Excluded sources still occur in required evidence; exclusions are not exemptions')
    if {e['file_id'] for e in exclusions}-set(all_heads):blocked.append('Unknown excluded-source IDs; use explicit coverage limitations for unregistered missing material')
    parent=set(reader.cfg.get('scope',{}).get('file_ids',[]))
    if parent and not selected<=parent:blocked.append('Operation exceeds configured parent document scope')
    parents=set(reader.cfg.get('scope',{}).get('entity_ids',[]))
    if parents and not {r['id'] for r in equipment}<=parents:blocked.append('Operation exceeds configured parent equipment scope')
    sources={fid:all_heads[fid] for fid in sorted(selected) if fid in all_heads}
    extractions,gap=_extractions(reader,sources)
    counts['extraction']=sum(r['record_count'] for r in extractions);counts['registration']=len(sources)
    if route['id']=='B' and action=='reuse' and not extractions:
        blocked.append('No supported stored extraction for the declared source hashes; explicit native preparation/registration is required')
    if gap and route['id']=='B':unknown.append(gap)
    source_basis=reader.source_version_basis(sources)
    currencies={fid:_snapshot_compatible(reader,head) for fid,head in sources.items()}
    for fid,value in currencies.items():
        status=value['state']
        if native:
            if status!='CURRENT' and not (route['id']=='A' and action=='registry_rescan' and status=='MODIFIED'):
                blocked.append('Native processing needs a matching explicit current source basis: '+fid+' '+status)
        elif status in ('MODIFIED','MISSING'):
            if request.get('currency_policy',{}).get('allow_historical_draft_evidence') is True:
                warnings.append('Historical evidence only for changed/missing source '+fid+'; potentially outdated, never current/approved')
            else:blocked.append('Changed/missing selected source requires explicit historical-draft policy or source reassessment: '+fid)
        elif status not in ('CURRENT',):warnings.append('Source currency '+status+' for '+fid+'; no live verification inferred')
    dependencies=[]
    if reader.snapshot:
        for node in reader.currency_nodes.values():
            locator=node.get('locator') or {}
            if node.get('id') in {v['version_id'] for v in extractions} or (node.get('kind')=='artifact' and any(locator.get('path')==a.get('path') for a in request.get('artifacts',[]))):
                dependencies.append({'node_id':node['node_id'],'impact':node.get('impact','UNKNOWN'),'changed_source_ids':node.get('changed_source_ids',[])})
        if any(d['impact']=='UNKNOWN' for d in dependencies):warnings.append('Dependency lineage contains UNKNOWN paths; not certified current')
    if not reader.snapshot:warnings.append('No explicit Source Currency snapshot; evidence availability is not current-source certification')
    elif reader.snapshot_info.get('assessed_at'):warnings.append('Source states are as of '+reader.snapshot_info['assessed_at']+', not proof of live currency')
    if native:
        at=reader.snapshot_info.get('assessed_at')
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(at)).total_seconds()
            if age<0 or age>request.get('currency_policy',{}).get('max_snapshot_age_seconds',900):blocked.append('Native source assessment is future-dated or older than the explicit freshness policy')
        except (ValueError,TypeError):blocked.append('Native processing requires a usable explicit assessment timestamp')
    limitations,missing_limits=_limitations(reader,request.get('accepted_limitation_ids',[]),selected)
    if missing_limits:blocked.append('Unknown accepted-limitation audit IDs: '+str(missing_limits))
    if any(l['requested'] and l['retired'] for l in limitations):blocked.append('A requested source-limitation acceptance was retired')
    declared=request.get('coverage_limitations',[])
    if not isinstance(declared,list) or any(not isinstance(v,dict) or not v.get('reason') for v in declared):raise ValueError('Coverage limitations require explicit reasons')
    if declared or limitations:warnings.append('Coverage limitations retained in receipt; no blanket processing exemption or quantity approval')
    required=request.get('required_evidence',[])
    for kind in required:
        if not counts[kind]:blocked.append('Required evidence unavailable in declared scope: '+kind)
    approvals=request.get('approval_requirements',{})
    if set(approvals)-{'identity','quantity','specification_applicability','document_revision','procurement_release'} or any(type(v) is not bool for v in approvals.values()):
        raise ValueError('Approval requirements are explicit supported boolean fields')
    clause_ids=request.get('review_clause_ids',[])
    reviews,missing,valid_decisions=_reviews(reader,equipment,approvals,clause_ids,sources)
    human.extend(missing)
    if approvals.get('document_revision'):
        # Exact source/revision decisions are queried individually; matching source hash is never sufficient.
        for fid in sources:
            found=False
            for event in valid_decisions:
                original=event['original_evidence_and_version_basis']['target'].get('provenance') or {}
                if event['decision_type']=='document_revision' and (original.get('original_source') or {}).get('file_id')==fid:found=True
            if not found:human.append({'type':'document_revision','file_id':fid,'reason':'Explicit valid source-revision assertion required'})
    if request.get('delivery_mode','draft')!='draft' or approvals.get('procurement_release'):
        human.append({'type':'procurement_release','reason':'Approved procurement delivery is not implemented by these operations; separate human/native approval rules apply'})
    native_plan=None
    if native:
        from .operation_adapters import native_preview
        native_plan=native_preview(reader.cfg,reader,request,sorted(selected))
        blocked.extend(native_plan.get('blockers',[]));unknown.extend(native_plan.get('unknown',[]))
        warnings.extend(native_plan.get('warnings',[]))
    reused_supplier=None
    if compiled is not None and request.get('reuse_supplier_receipt'):
        from .operation_adapters import reusable_supplier
        try:reused_supplier=reusable_supplier(reader,compiled,request['reuse_supplier_receipt'])
        except (ValueError,OSError,KeyError) as error:blocked.append('Existing supplier draft cannot be reused: '+str(error))
    runtime_basis=None
    if compiled is not None and not request.get('reuse_supplier_receipt'):
        runtime=request.get('supplier_runtime',{})
        if set(runtime)!={'node_executable','artifact_module_root'}:
            blocked.append('New supplier rendering requires explicit bound bundled Node executable and artifact module root')
        else:
            runtime_basis={k:str(resolve(Path(reader.cfg['config_path']).parent,v)) for k,v in runtime.items()}
            package=Path(runtime_basis['artifact_module_root'])/'@oai/artifact-tool/package.json'
            if not Path(runtime_basis['node_executable']).is_file() or not package.is_file() or importlib.util.find_spec('reportlab') is None:
                blocked.append('Required existing supplier rendering dependency unavailable; no automatic installs')
            else:runtime_basis['artifact_package_metadata_sha256']=sha(package)
    registry_metadata=[]
    if route['id']=='A':
        for fid,head in sources.items():
            analysis=reader.row('registry_analyses',head['analysis_id']) or {}
            registry_metadata.append({'file_id':fid,'relative_path':head['relative_path'],'version':reader.version_identity(head['version_id']),
                'analysis_id':head['analysis_id'],'metadata_as_recorded':decoded(analysis.get('metadata_json')),
                'revision_approval_status':'SEPARATE_EXISTING_REVIEW_NOT_INFERRED','coverage':'REGISTERED_IDENTITY_NOT_EXTRACTION_COMPLETENESS'})
        projection={'document_register':registry_metadata}
    if route['id']=='B' and action=='reuse':projection={'stored_extractions':extractions,'coverage':'Only existing source-linked records; missing Xrefs/images remain unprocessed'}
    historical=[]
    if reader.has('master_events','project_id','scope_id','stage','job_id','status'):
        for stage in route['stages']:
            row=reader.conn.execute('SELECT id,status FROM master_events WHERE project_id=? AND scope_id=? AND stage=? AND job_id IS NULL ORDER BY rowid DESC LIMIT 1',
                (reader.cfg['project_id'],reader.cfg.get('scope',{}).get('id','project'),stage)).fetchone()
            historical.append({'stage':stage,'event_id':row['id'] if row else None,'recorded_status':row['status'] if row else 'NO_SAVED_EVENT',
                'meaning':'Historical formal status is preserved; not an operation eligibility prerequisite by itself'})
    artifact_basis=[]
    for descriptor in request.get('artifacts',[]):
        if not isinstance(descriptor,dict) or not descriptor.get('path') or not descriptor.get('sha256'):raise ValueError('Explicit artifact path/hash required')
        path=resolve(Path(reader.cfg['config_path']).parent,descriptor['path'])
        if not path.is_file() or sha(path)!=descriptor['sha256']:blocked.append('Missing/changed declared artifact: '+str(path))
        artifact_basis.append({**descriptor,'path':str(path)})
    if blocked:outcome='BLOCKED'
    elif unknown:outcome='UNKNOWN'
    elif human:outcome='REQUIRES_HUMAN_ACTION'
    elif warnings:outcome='READY_WITH_LIMITATIONS'
    else:outcome='READY'
    config_files=[]
    for name in ('registry_config','matching_config','review_config','package_config','quality_config'):
        if reader.cfg.get(name):
            path=resolve(Path(reader.cfg['config_path']).parent,reader.cfg[name])
            config_files.append({'name':name,'path':str(path),'sha256':sha(path) if path.is_file() else None})
            if native and not path.is_file():blocked.append('Missing native configuration dependency: '+name)
    if blocked:outcome='BLOCKED'
    implementation=[HOME/'scripts/master_project'/f for f in ('operation_workflow.py','operation_adapters.py','evidence_reader.py','native_equipment.py','human_decisions.py','source_currency.py')]
    implementation.append(HOME/'assets/config/operations.json')
    if route['id']=='E':implementation.extend([HOME/'scripts/master_project/supplier_draft.py',HOME/'scripts/master_project/supplier_schedule.mjs'])
    execution_basis={'request':request,'resolved_source_ids':sorted(selected),'equipment':[(r['id'],r['normalized_tag'],r['family']) for r in equipment],
        'source_version_basis':source_basis,'source_currency':currencies,'assessment':reader.snapshot_info,
        'reused_extractions':extractions,'projection_sha256':key(projection),'supplier_content_fingerprint':compiled['content_fingerprint'] if compiled else None,
        'limitations':limitations,'declared_coverage_limitations':declared,'review_decisions':reviews,'artifacts':artifact_basis,
        'native_plan':native_plan,'reused_supplier':reused_supplier,'supplier_runtime':runtime_basis,'output_directory':str(out),'configuration':{k:reader.cfg.get(k) for k in ('project_id','database','source_directory','output_directory','skills_root','scope','registry_config','matching_config','review_config','quality_config')},
        'configuration_files':config_files,'implementation':[(str(p.relative_to(HOME)),sha(p)) for p in implementation],
        'eligibility':outcome,'blockers':sorted(set(blocked)),'uncertain_dependencies':sorted(set(unknown)),'human_actions':human}
    result={'schema_version':PLAN,'project_id':reader.cfg['project_id'],'operation':route['id'],'operation_name':route['name'],
        'planned_at':now(),'eligibility':outcome,'reasons':{'blockers':sorted(set(blocked)),'uncertain':sorted(set(unknown)),'human_actions':human,'warnings':sorted(set(warnings))},
        'requested_scope':scope,'resolved_source_ids':sorted(selected),'evidence_counts':counts,'source_currency':currencies,
        'dependency_impacts':dependencies,'source_limitations':limitations,'declared_coverage_limitations':declared,
        'review_summary':reviews,'procurement_release_authorized':False,'engineering_approval_created':False,
        'historical_stage_context':historical,'formal_stage_completion':False,
        'actions':native_plan['actions'] if native_plan else [{'kind':'reuse_supplier_draft' if reused_supplier else ('supplier_draft' if action=='draft' else 'read_only_projection'),'sources':sorted(selected),'reuse_existing_evidence':True}],
        'sources_requiring_processing':sorted(selected) if native and not (native_plan or {}).get('reused') else [],
        'reused_evidence':{'stored_extractions':extractions,'equipment_ids':[r['id'] for r in equipment]},
        'expected_outputs':{'directory':str(out),'operation_receipt':'operation-receipt.json','data':'projection.json' if action=='reuse' else ('Supplier Draft default XLSX/PDF per family' if action=='draft' else 'Native adapter outputs and audit')},
        'fingerprint_basis':execution_basis,'plan_is_execution_authorization':False}
    result['plan_fingerprint']=identity(result)
    return result,projection,compiled


def plan_operation(cfg,request,*,currency_snapshot=None):
    with operation_reader(cfg,currency_snapshot) as reader:return assess_operation(reader,request)[0]


def operation_reader(cfg,currency_snapshot=None):
    try:return EvidenceReader(cfg,currency_snapshot)
    except (ValueError,OSError) as error:
        if not currency_snapshot:raise
        reader=EvidenceReader(cfg)
        reader.snapshot_info={'status':'UNAVAILABLE_OR_INCOMPATIBLE_SNAPSHOT','requested_path':str(Path(currency_snapshot).resolve()),
            'source_currency':'UNKNOWN','dependency_impact':'UNKNOWN','reason':str(error),'live_source_rehash_performed':False}
        return reader
