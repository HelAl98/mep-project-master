"""P1-04. Versioned granular assertions in the EXISTING append-only master audit.

No schema creation, source updates, approval-gate activation or model calls.
Terminal assertion is explicitly not independently authenticated identity.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .memory import connect

ACTION='granular_human_decision_v1'
CONTRACT='mep-human-decision/1'
PROPOSAL='mep-human-decision-proposal/1'
TYPES=('identity','quantity','specification_applicability','document_revision')
RESULTS=('Accepted','Rejected','Unresolved')
_SEAL=object()


def stamp():return datetime.now(timezone.utc).isoformat()


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def proposal_digest(value):return digest({k:v for k,v in value.items() if k!='proposal_sha256'})


def events(reader):
    if not reader.has('master_operator_events','id','project_id','scope_id','action','actor','reason','payload_json','created_at'):
        return []
    result=[]
    for row in reader.conn.execute('SELECT * FROM master_operator_events WHERE project_id=? AND action=? ORDER BY rowid',
                                   (reader.cfg['project_id'],ACTION)):
        value=json.loads(row['payload_json'])
        if value.get('schema_version')!=CONTRACT or value.get('id')!=row['id'] or value.get('project_id')!=reader.cfg['project_id']:
            raise ValueError('Malformed/unsupported granular audit event; manual inspection required')
        result.append(value)
    return result


def inspection(reader,ref):
    if not isinstance(ref,dict) or not isinstance(ref.get('table'),str) or not isinstance(ref.get('id'),str):
        raise ValueError('Every target/support reference requires an exact table and ID')
    response=reader.inspect_evidence(ref['id'],table=ref['table'])
    if response.get('schema_version')!='mep-evidence-reader/1' or response.get('status')!='AVAILABLE' or len(response['items'])!=1:
        raise ValueError('Unavailable or foreign-project evidence reference: '+encoded(ref))
    return response['items'][0]


def scope_inspection(reader,scope):
    if not isinstance(scope,dict) or scope.get('kind') not in ('family','type','item'):
        raise ValueError('Specification scope requires family/type/item')
    if scope['kind']=='family':
        if set(scope)-{'kind','family'}:raise ValueError('Family scope accepts only kind and family')
        if not isinstance(scope.get('family'),str) or not scope['family'].strip():raise ValueError('Explicit stored family required')
        rows=[];offset=0
        while True:
            response=reader.list_equipment(scope['family'],limit=200,offset=offset)
            page=response['result']
            if page['total'] is None or not 1<=page['total']<=10000:raise ValueError('Missing/over-limit stored family scope')
            rows.extend({k:v for k,v in r.items() if k!='provenance'} for r in page['items'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        return {'scope':scope,'members':rows}
    if set(scope)-{'kind','table','id'}:raise ValueError('Item/type scope accepts only kind, table and ID')
    item=inspection(reader,scope)
    if scope['kind']=='type':
        record=item['original_record']
        if str(record.get('kind') or record.get('identity_kind')).casefold()!='type':raise ValueError('Selected scope is not a recorded equipment type')
    return {'scope':scope,'evidence':item}


def basis(reader,target,support,scope=None):
    inspected=inspection(reader,target)
    facts=[inspection(reader,ref) for ref in support]
    sources={}
    for fact in [inspected,*facts]:
        prov=fact.get('provenance') or {}
        original=prov.get('original_source') or {}
        if original.get('file_id'):sources[original['file_id']]=original
    captured={'target':inspected,'supporting_evidence':facts,'scope':scope_inspection(reader,scope) if scope else None,
              'registered_source_heads':reader.source_version_basis(sources),
              'source_currency_assessment':reader.snapshot_info}
    return {**captured,'sha256':digest(captured)}


def quantity_evidence(item):
    """Explicit schedule quantities only, never occurrence counts/controllers/BOQ panels."""
    if item.get('source_role')!='schedule':return []
    parsed=item.get('parsed_original') or {};raw=item['original_record'];table=item['table']
    if table=='eq_parameters':
        payload=parsed.get('payload') or {};original=payload.get('original') or {}
        if str(original.get('name',raw.get('name'))).casefold() not in ('quantity','scheduled_quantity','equipment_quantity','physical_count'):return []
        return [(original.get('value',payload.get('value')),original.get('unit',payload.get('unit')))]
    if table=='uc_fields' and ((item.get('provenance') or {}).get('recorded_source') or {}).get('quantity_basis')=='explicit_equipment_schedule' and str(raw.get('name')).casefold() in ('quantity','scheduled_quantity','equipment_quantity','physical_count'):
        return [(v,raw.get('printed_unit')) for v in parsed.get('raw_values',[])]
    if table=='eq_occurrences':
        data=parsed.get('data') or {}
        return [(data.get('quantity'),data.get('quantity_unit'))] if data.get('quantity') is not None else []
    return []


def number(value):
    if isinstance(value,bool):raise ValueError('Boolean is not an engineering quantity')
    try:result=Decimal(str(value))
    except (InvalidOperation,ValueError):raise ValueError('Quantity must be an explicit finite decimal; no inferred sums or unit conversion')
    if not result.is_finite() or result<0:raise ValueError('Quantity must be nonnegative and finite')
    return result


def complete_source(item):
    prov=item.get('provenance') or {};original=prov.get('original_source') or {}
    return bool(original.get('file_id') and original.get('id') and original.get('sha256') and prov.get('lineage_status')=='RECORDED')


def check_request(request,b):
    kind,result=request['decision_type'],request['result'];target=request['target'];assertion=request.get('assertion',{})
    allowed={'identity':{'uc_profiles','eq_entities','eq_matches','eq_occurrences'},
             'quantity':{'uc_profiles','eq_entities','eq_occurrences'},
             'specification_applicability':{'records'},'document_revision':{'registry_revisions','versions'}}
    if target['table'] not in allowed[kind]:raise ValueError('Decision type and target table are incompatible')
    if result!='Accepted':return
    facts=b['supporting_evidence']
    if kind=='quantity':
        if assertion.get('quantity_kind') not in ('physical_count','scheduled_quantity') or not assertion.get('unit'):
            raise ValueError('Accepted quantity requires physical_count/scheduled_quantity and original printed unit')
        reviewed=number(assertion.get('quantity'))
        if assertion['quantity_kind']=='physical_count' and reviewed!=reviewed.to_integral_value():raise ValueError('Physical equipment count must be an integer')
        target_item=b['target'];related_ids={r['id'] for r in target_item.get('related_references',[]) if r['table']=='eq_occurrences'}
        if target_item['table']=='eq_occurrences':related_ids.add(target_item['id'])
        def associated(fact):
            raw=fact['original_record']
            return ((fact['table']=='eq_occurrences' and fact['id'] in related_ids) or
                    (fact['table']=='eq_parameters' and raw.get('occurrence_id') in related_ids) or
                    (fact['table']=='uc_fields' and raw.get('profile_id')==target_item['id']))
        candidates=[(v,u) for fact in facts if associated(fact) and complete_source(fact) for v,u in quantity_evidence(fact)]
        compatible=[]
        for value,unit in candidates:
            try:compatible.append(number(value)==reviewed and str(unit or '').strip().casefold()==str(assertion['unit']).strip().casefold())
            except ValueError:continue
        if not any(compatible):raise ValueError('No supporting explicit equipment-schedule quantity/unit equals the reviewed quantity. Tags, matches, electrical/BMS/controllers and BOQ quantities cannot establish this count.')
    elif kind=='identity':
        if assertion.get('identity_kind') not in ('Reference','Type','Group','Physical Instance'):raise ValueError('Explicit identity kind required')
        if not facts:raise ValueError('Identity acceptance needs explicit supporting evidence')
        associated_ids={r['id'] for r in b['target'].get('related_references',[]) if r['table']=='eq_occurrences'}
        if b['target']['table']=='eq_occurrences':associated_ids.add(b['target']['id'])
        if assertion['identity_kind']=='Physical Instance' and not any(f.get('source_role')=='schedule' and complete_source(f) and
            (f['id'] in associated_ids or f['original_record'].get('occurrence_id') in associated_ids) for f in facts):
            raise ValueError('Repeated labels/controller/panel references alone cannot establish a physical instance')
    elif kind=='specification_applicability':
        if assertion.get('applies') is not True or not b['scope']:raise ValueError('Accepted applicability requires one exact clause and explicit equipment scope')
        if b['target']['original_record'].get('kind')!='specification':raise ValueError('Target is not saved specification evidence')
    elif kind=='document_revision':
        record=b['target']['original_record'];revision=record.get('revision')
        if not revision or assertion.get('revision')!=revision:raise ValueError('Revision label is not established in this exact saved target; source hash is not revision approval')
        prov=b['target'].get('provenance') or {}
        if prov.get('derived_document'):raise ValueError('A derived conversion is not an original contractual revision')
    # Acceptance can be recorded against an uncertain basis, but can never be projected as currently valid.
    source_facts=[b['target'],*facts]
    if kind in ('identity','quantity'):source_facts=facts
    if not any(complete_source(f) for f in source_facts):
        raise ValueError('Accepted assertion needs registered source-linked evidence')


def prepare_decision(reader,request):
    if not isinstance(request,dict) or request.get('decision_type') not in TYPES or request.get('result') not in RESULTS:
        raise ValueError('Supported decision_type and Accepted/Rejected/Unresolved result required')
    if request.get('project_id')!=reader.cfg['project_id']:raise ValueError('Decision project mismatch')
    if not isinstance(request.get('reviewer'),str) or not request['reviewer'].strip() or not isinstance(request.get('rationale'),str) or not request['rationale'].strip():
        raise ValueError('Reviewer-provided label and rationale are required; neither is authentication')
    if not isinstance(request.get('assertion',{}),dict):raise ValueError('Assertion must be an object; original evidence is preserved separately')
    target=request.get('target');support=request.get('supporting_references',[])
    if not isinstance(support,list) or len(support)>50:raise ValueError('At most 50 explicit supporting references')
    if len({encoded(r) for r in support})!=len(support):raise ValueError('Duplicate supporting references')
    if request['decision_type']=='specification_applicability' and not request.get('scope'):raise ValueError('Clause applicability needs an explicit family/type/item scope')
    if request['decision_type']!='specification_applicability' and request.get('scope') is not None:
        raise ValueError('Only clause applicability uses a separate scope; other decisions use their exact target identity')
    b=basis(reader,target,support,request.get('scope'))
    check_request(request,b)
    record=b['target']['original_record']
    fid=((b['target'].get('provenance') or {}).get('original_source') or {}).get('file_id') or record.get('file_id')
    if request['decision_type']=='document_revision' and not fid:raise ValueError('Revision target has no registered original-file identity')
    key=digest([request['decision_type'],fid if request['decision_type']=='document_revision' else {'table':target['table'],'id':target['id']},request.get('scope')])
    previous=[e for e in events(reader) if e['target_key']==key]
    latest=previous[-1]['id'] if previous else None
    if request.get('previous_decision_id') not in (None,latest):raise ValueError('Previous decision is not the current decision for this target/type/scope')
    label=record.get('normalized_tag') or record.get('original_tag') or record.get('filename') or target['id']
    value={'schema_version':PROPOSAL,'project_id':reader.cfg['project_id'],'prepared_at':stamp(),
        'request':request,'target_key':key,'target_label':label,'previous_decision_id':latest,'basis':b,
        'authorization':'PROPOSAL ONLY \u2014 NOT A HUMAN DECISION','identity_assurance':'NOT_AUTHENTICATED',
        'source_status_note':'Validity is separate from acceptance; unknown/changed lineage remains uncertain.'}
    value['proposal_sha256']=proposal_digest(value)
    if len(encoded(value).encode('utf-8'))>16*1024*1024:raise ValueError('Proposal exceeds bounded 16 MiB; narrow supporting evidence')
    return value


class _HumanAssertion:
    __slots__=('proposal_sha256','channel','test_only','nonce','used','_seal')
    def __init__(self,proposal_sha256,channel,test_only=False,*,seal=None):
        if seal is not _SEAL:raise PermissionError('Authorization is issued only by explicit terminal interaction; a flag/name is insufficient')
        self.proposal_sha256=proposal_sha256;self.channel=channel;self.test_only=test_only
        self.nonce=uuid.uuid4().hex;self.used=False;self._seal=seal

    def __setattr__(self,name,value):
        if hasattr(self,'_seal'):raise PermissionError('Authorization attributes are immutable')
        object.__setattr__(self,name,value)


def authorize_in_terminal(proposal):
    """The human must run/interact with this terminal; agents must never fill the prompt."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise PermissionError('Human interactive terminal required; noninteractive agent/API flags cannot authorize recording')
    if proposal_digest(proposal)!=proposal.get('proposal_sha256'):raise ValueError('Proposal digest mismatch')
    request=proposal['request']
    print(encoded({'proposal_sha256':proposal['proposal_sha256'],'request':request,'previous_decision_id':proposal['previous_decision_id'],
        'basis_sha256':proposal['basis']['sha256'],'source_heads':proposal['basis']['registered_source_heads'],
        'identity_assurance':'Reviewer label is a recorded assertion, not independently authenticated identity.'}))
    phrase='RECORD '+proposal['proposal_sha256']
    if input('After inspecting the complete proposal, type '+phrase+' exactly: ').strip()!=phrase:raise PermissionError('Human confirmation not supplied; nothing recorded')
    return _HumanAssertion(proposal['proposal_sha256'],'local_interactive_terminal',seal=_SEAL)


def _fixture_authorization(proposal,cfg):
    """Test seam, never a real human authorization. Actual project IDs are rejected."""
    if cfg.get('decision_test_fixture') is not True or not str(cfg.get('project_id','')).startswith('FIXTURE_ONLY_'):
        raise PermissionError('Test authorization is restricted to explicitly labelled synthetic projects')
    return _HumanAssertion(proposal['proposal_sha256'],'synthetic_fixture_test',True,seal=_SEAL)


def record_decision(cfg,proposal,authorization,*,currency_snapshot=None):
    if not isinstance(authorization,_HumanAssertion) or authorization._seal is not _SEAL or authorization.used:
        raise PermissionError('No unused explicit human interaction authorization; no write attempted')
    if proposal.get('schema_version')!=PROPOSAL or proposal_digest(proposal)!=proposal.get('proposal_sha256') or authorization.proposal_sha256!=proposal['proposal_sha256']:
        raise PermissionError('Authorization does not cover this exact inspected proposal')
    if proposal.get('project_id')!=cfg['project_id']:raise ValueError('Authorized proposal project mismatch')
    if authorization.test_only and (cfg.get('decision_test_fixture') is not True or not str(cfg.get('project_id','')).startswith('FIXTURE_ONLY_')):
        raise PermissionError('Synthetic authorization cannot be used on an engineering project or its copy')
    object.__setattr__(authorization,'used',True)
    # No Memory/Registry/Database constructor: no migration or workflow initialization.
    conn=connect(cfg,writable=True)
    try:
        columns={r[1] for r in conn.execute('PRAGMA table_info(master_operator_events)')}
        required={'id','project_id','scope_id','action','actor','reason','payload_json','created_at'}
        triggers={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='master_operator_events'")}
        if not required<=columns or not {'master_operator_no_update','master_operator_no_delete'}<=triggers:
            raise ValueError('Existing append-only master audit infrastructure required; no automatic migration')
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION,sqlite3.SQLITE_RECURSIVE}
        conn.set_authorizer(lambda action,a,b,db,trigger:sqlite3.SQLITE_OK if action in allowed or
            (action==sqlite3.SQLITE_INSERT and a=='master_operator_events') else sqlite3.SQLITE_DENY)
        conn.execute('BEGIN IMMEDIATE')
        from .evidence_reader import EvidenceReader
        with EvidenceReader(cfg,currency_snapshot) as reader:
            fresh=prepare_decision(reader,proposal['request'])
            if fresh['basis']['sha256']!=proposal['basis']['sha256'] or fresh['target_key']!=proposal['target_key'] or fresh['previous_decision_id']!=proposal['previous_decision_id']:
                raise ValueError('Evidence/audit/source snapshot changed; prepare and inspect a new proposal')
        identity=uuid.uuid4().hex;created=stamp();request=proposal['request']
        event={'schema_version':CONTRACT,'id':identity,'project_id':cfg['project_id'],'decision_type':request['decision_type'],
            'target':request['target'],'target_key':proposal['target_key'],'target_label':proposal['target_label'],
            'scope':request.get('scope'),'result':request['result'],'assertion':request.get('assertion',{}),
            'reviewer_provided_identity':request['reviewer'],'rationale':request['rationale'],'created_at':created,
            'supporting_references':request.get('supporting_references',[]),'original_evidence_and_version_basis':proposal['basis'],
            'previous_decision_id':proposal['previous_decision_id'],'proposal_sha256':proposal['proposal_sha256'],
            'authorization':{'channel':authorization.channel,'nonce':authorization.nonce,'independently_authenticated':False,
                'assurance':'TEST ONLY \u2014 SIMULATED, NOT A HUMAN DECISION' if authorization.test_only else 'RECORDED HUMAN ASSERTION \u2014 NOT INDEPENDENTLY AUTHENTICATED',
                'test_only':authorization.test_only},'upstream_engineering_approval_created':False}
        conn.execute('INSERT INTO master_operator_events(id,project_id,scope_id,action,actor,reason,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (identity,cfg['project_id'],cfg.get('scope',{}).get('id','project'),ACTION,request['reviewer'],request['rationale'],encoded(event),created))
        conn.commit()
        return {'schema_version':'mep-human-decision-receipt/1','recorded_id':identity,'result':event['result'],'authorization':event['authorization'],
                'decision_validity':'Unknown Validity','validity_checked':False,'upstream_engineering_approval_created':False}
    except BaseException:
        conn.rollback();raise
    finally:conn.close()


def validity(reader,event,all_events=None):
    b=event['original_evidence_and_version_basis'];reasons=[];state=None
    try:
        current=basis(reader,event['target'],event['supporting_references'],event.get('scope'))
        # Currency snapshot identity may legitimately be refreshed; compare immutable evidence and registry basis separately.
        def stable(value,root=False):
            if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('source_currency_assessment','currency') and not (root and k=='sha256')}
            if isinstance(value,list):return [stable(x) for x in value]
            return value
        if stable(current,True)!=stable(b,True):state='Requires Revalidation';reasons.append('target_support_scope_or_registered_version_basis_changed')
        if not b['registered_source_heads']:reasons.append('no_registered_source_basis')
        for fact in [current['target'],*current['supporting_evidence']]:
            if fact is current['target'] and fact['table'] in ('uc_profiles','eq_entities','eq_matches') and current['supporting_evidence']:
                continue  # Aggregate target has no single original; its explicit source facts remain mandatory.
            prov=fact.get('provenance')
            if not prov:continue  # UC identity/relationship is supported by explicit cited source facts below.
            original=prov.get('original_source')
            if not original or prov.get('lineage_status')!='RECORDED':reasons.append('incomplete_original_source_lineage');continue
            head=current['registered_source_heads'].get(original.get('file_id')) or {}
            if head.get('version_id')!=original.get('id'):
                state='Requires Revalidation';reasons.append('cited_original_version_is_not_registered_head')
            curr=prov['currency'];source=curr.get('source_currency');impact=curr.get('dependency_impact')
            if source in ('MODIFIED','MISSING') or impact=='POTENTIALLY_OUTDATED':
                state='Requires Revalidation';reasons.append('changed_or_missing_supporting_source')
            elif source!='CURRENT' or impact!='UNAFFECTED_BY_DETECTED_SOURCE_CHANGES':reasons.append('unverified_source_or_unknown_dependency_impact')
        assessed=reader.snapshot_info.get('assessed_at')
        try:
            if not assessed or datetime.fromisoformat(assessed)<datetime.fromisoformat(event['created_at']):reasons.append('source_assessment_missing_or_predates_decision')
            elif datetime.fromisoformat(assessed)>datetime.now(timezone.utc):reasons.append('source_assessment_timestamp_in_future')
        except (ValueError,TypeError):reasons.append('unusable_source_assessment_timestamp')
    except (ValueError,KeyError,sqlite3.DatabaseError) as error:
        state='Requires Revalidation';reasons.append('basis_cannot_be_resolved:'+str(error))
    if state is None:state='Unknown Validity' if reasons else ('Unreviewed' if event['result']=='Unresolved' else event['result'])
    superseded=next((e['id'] for e in (all_events or events(reader)) if e.get('previous_decision_id')==event['id']),None)
    return {'decision_id':event['id'],'recorded_result':event['result'],'status':'Superseded' if superseded else ('Unreviewed' if event['result']=='Unresolved' else state),
        'basis_validity':state,'superseded_by':superseded,'reasons':sorted(set(reasons)),
        'validity_scope':'AS OF EXPLICIT CURRENCY SNAPSHOT AND THIS DATABASE READ; NOT LIVE SOURCE VERIFICATION',
        'source_assessment':reader.snapshot_info,'identity_independently_authenticated':False,
        'test_only':event['authorization'].get('test_only',False),'engineering_approval_inferred':False}


def related(event,reference):
    if reference is None:return True
    scope=event.get('scope') or {}
    return reference in (event['id'],event['target']['id'],event.get('target_label'),scope.get('id'),scope.get('family'))


def decision_history(reader,reference=None,*,decision_type=None,limit=25,offset=0):
    reader.bounds(limit,offset)
    if decision_type is not None and decision_type not in TYPES:raise ValueError('Unsupported decision type')
    all_events=events(reader)
    selected=[e for e in all_events if related(e,reference) and (decision_type is None or e['decision_type']==decision_type)]
    items=[{'decision':event,'validity':validity(reader,event,all_events)} for event in selected[offset:offset+limit]]
    return reader.envelope('human_decision_history',decision_contract=CONTRACT,result={'status':'AVAILABLE' if selected else 'NO_RECORDED_EVIDENCE',
        'items':items,'total':len(selected),'limit':limit,'offset':offset,'next_offset':offset+len(items) if offset+len(items)<len(selected) else None},
        existing_audit_available=reader.has('master_operator_events','payload_json'),upstream_decisions_are_independent=True)


def decision_validity(reader,decision_id):
    all_events=events(reader);event=next((e for e in all_events if e['id']==decision_id),None)
    return reader.envelope('human_decision_validity',status='AVAILABLE' if event else 'NOT_FOUND',
        result=validity(reader,event,all_events) if event else None)


def prepare_successor(reader,decision_id,*,result,reviewer,rationale,assertion=None):
    previous=next((e for e in events(reader) if e['id']==decision_id),None)
    if not previous:raise ValueError('Decision not found in this project')
    request={'project_id':reader.cfg['project_id'],'decision_type':previous['decision_type'],'target':previous['target'],
        'scope':previous.get('scope'),'assertion':previous['assertion'] if assertion is None else assertion,'result':result,
        'reviewer':reviewer,'rationale':rationale,'supporting_references':previous['supporting_references'],'previous_decision_id':decision_id}
    return prepare_decision(reader,request)


def pending_targets(reader,*,family=None,limit=25,offset=0):
    """Bounded equipment identity/quantity queue. Clause/revision targets use inspect/prepare explicitly."""
    reader.bounds(limit,offset);rows=[];index=0
    while True:
        page=reader.list_equipment(family,limit=200,offset=index)['result']
        if page['total'] is None:return reader.envelope('pending_reviews',result=page)
        if page['total']>10000:raise ValueError('Pending review scope exceeds 10000; select a family')
        rows.extend(page['items'])
        if page['next_offset'] is None:break
        index=page['next_offset']
    all_events=events(reader);items=[]
    for row in rows:
        states={}
        for kind in ('identity','quantity'):
            matching=[e for e in all_events if e['decision_type']==kind and related(e,row['id'])]
            states[kind]=validity(reader,matching[-1],all_events)['status'] if matching else 'Unreviewed'
        if any(s not in ('Accepted','Rejected') for s in states.values()):
            items.append({'equipment_reference':row.get('normalized_tag'),'target_id':row['id'],'family':row.get('family'),
                'identity_kind_as_recorded':row.get('identity_kind'),'decision_states':states,
                'scope_notice':'Only identity/quantity queue; choose exact clauses/revisions for separate applicability/revision inspection'})
    return reader.envelope('pending_reviews',result={'status':'AVAILABLE' if items else 'NO_RECORDED_EVIDENCE','items':items[offset:offset+limit],
        'total':len(items),'limit':limit,'offset':offset,'next_offset':offset+limit if offset+limit<len(items) else None})
