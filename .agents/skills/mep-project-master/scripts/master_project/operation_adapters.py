"""Native bridges and exact authorized execution, reusing master locks/adapters/audits."""
from copy import deepcopy
from pathlib import Path
import json
import uuid
import zipfile
import re

from .common import HOME,key,read,write,sha,now,resolve
from .memory import Memory,connect,project_lock
from .evidence import valid_artifacts,valid_persisted
from .evidence_reader import EvidenceReader
from .source_currency import stable_hash

AUDIT='operation_scope_execution_v1'
RECEIPT='mep-operation-receipt/1'


class ExistingMemory(Memory):
    """Reuse Memory methods WITHOUT its constructor's schema/stage initialization."""
    def __init__(self,cfg,writable=False):
        self.cfg,self.conn,self.writable=cfg,connect(cfg,writable),writable
        try:
            required={'id','project_id','scope_id','action','actor','reason','payload_json','created_at'}
            cols={r[1] for r in self.conn.execute('PRAGMA table_info(master_operator_events)')}
            triggers={r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='master_operator_events'")}
            if not required<=cols or not {'master_operator_no_update','master_operator_no_delete'}<=triggers:
                raise ValueError('Existing append-only master audit required; no initialization or migration allowed')
        except BaseException:self.conn.close();raise

    def event(self,stage,status,fingerprint,payload,job_id=None):
        if job_id is None:raise PermissionError('Operation bridge cannot append formal whole-stage transitions')
        return super().event(stage,status,fingerprint,payload,job_id)

    def persist_packages(self,manifests):
        if manifests:raise PermissionError('Approved/native procurement package persistence is outside operation adapters')


def _native_cfg(cfg,source_ids):
    value=deepcopy(cfg)
    for name in ('registry_config','matching_config','review_config','package_config','quality_config','skills_root'):
        if value.get(name):value[name]=str(resolve(Path(cfg['config_path']).parent,value[name]))
    value['scope']={**cfg.get('scope',{}),'file_ids':list(source_ids)}
    return value


def _ready_master(memory):
    c=memory.conn
    exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='master_schema'").fetchone()
    if not exists or [r[0] for r in c.execute('SELECT version FROM master_schema')]!=[1]:
        raise ValueError('Existing compatible initialized master schema required before native writes')
    for table in ('registry_migrations','registry_scan_files','master_events','master_packages','master_project_configs'):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():raise ValueError('Missing native prerequisite table: '+table)
    if [r[0] for r in c.execute('SELECT version FROM registry_migrations')]!=[1]:raise ValueError('Unsupported registry migration; no automatic upgrade')
    from .discovery import workflow
    if any(memory.latest(row['id']) is None for row in workflow()):raise ValueError('Existing formal master initialization required; operation layer will not create missing stage checkpoints')


def _ready_equipment(memory):
    names={r[0] for r in memory.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required={'eq_migrations','eq_categories','eq_imports','eq_occurrences','eq_parameters','eq_entities','eq_entity_sources',
              'eq_runs','eq_results','eq_matches','eq_relationships','eq_issues','eq_reviews','eq_fts'}
    if not required<=names or [r[0] for r in memory.conn.execute('SELECT version FROM eq_migrations')]!=[1]:
        raise ValueError('Existing equipment schema 1 required; operation must not initialize/migrate it')


def native_preview(cfg,reader,request,source_ids):
    """Read only; unsupported scope is never turned into a global job."""
    from .operation_workflow import requirements
    from .discovery import discover
    from .interfaces import build,reference
    from .engine import job_fingerprint
    action=request.get('action');operation=request['operation'];native={'adapter':action,'actions':[],'blockers':[],'unknown':[],'reused':False}
    narrowed=_native_cfg(cfg,source_ids)
    memory=None
    try:
        memory=ExistingMemory(narrowed);_ready_master(memory)
        if action in ('equipment_import','matching_proposals'):
            _ready_equipment(memory)
            planpath=resolve(Path(cfg['config_path']).parent,request.get('native_plan_path',''))
            if not planpath.is_file():raise ValueError('Explicit existing native execution plan required')
            native_plan=read(planpath)
            from .limited_scope import _envelope
            _envelope(cfg,native_plan)
            result_path=resolve(Path(cfg['config_path']).parent,native_plan.get('result_path',''))
            if not result_path.is_relative_to(Path(cfg['output_directory']).resolve()) or result_path.exists():
                raise ValueError('Native result needs a new explicit path inside the existing project output root')
            jobs=native_plan.get('jobs',[]) if action=='equipment_import' else [native_plan.get('job',{})]
            if not jobs or any(not j.get('source_file_ids') for j in jobs):raise ValueError('Native plan must declare exact nonempty source IDs')
            if any(not re.fullmatch(r'[A-Za-z0-9_-]+',j.get('id','')) for j in jobs):raise ValueError('Native job IDs must be safe existing task identifiers')
            actual={fid for j in jobs for fid in j['source_file_ids']}
            if actual!=set(source_ids):raise ValueError('Native plan sources differ from exact operation source scope')
            original_cfg=_native_cfg(cfg,cfg.get('scope',{}).get('file_ids',[]))
            memory.cfg=original_cfg
            if action=='equipment_import':
                from .equipment_scope import assess_job
                checked=[assess_job(original_cfg,memory,j) for j in jobs]
                native['source_specific_gate']='Exact existing equipment scope receipt, native mapping/cell/quantity/lineage validators and current source basis; no project-wide Stage01/02 completion waiver is persisted.'
            else:
                from .equipment_scope import upstream
                upstream(original_cfg,memory)  # Global matcher dataset has no narrow filter; keep this native guard.
                from .matching_scope import assess_job
                checked=[assess_job(original_cfg,memory,jobs[0])]
            native.update(plan_path=str(planpath),plan_sha256=sha(planpath),eligibility=checked,
                actions=[{'kind':'existing_native_plan','adapter':action,'jobs':jobs,'source_file_ids':source_ids,
                    'lock_owner':'native scope executor','formal_stage_completion':False}])
        else:
            job=deepcopy(request.get('native_job') or {})
            if action=='registry_rescan':
                if request.get('scope',{}).get('source_selection')!='registered_root' or cfg.get('scope',{}).get('file_ids'):
                    raise ValueError('Registry CLI scans the root: explicit full registered_root and unrestricted configured parent scope required')
                from .evidence import current_files
                heads=current_files(reader)
                if set(source_ids)!={r['file_id'] for r in heads}:raise ValueError('Registry rescan cannot narrow its source set')
                root=Path(cfg['source_directory']).resolve();paths=set()
                for path in root.rglob('*'):
                    if path.is_file():
                        if not path.resolve().is_relative_to(root):raise ValueError('Source link escapes registered root')
                        paths.add(path.relative_to(root).as_posix())
                        if len(paths)>10000:raise ValueError('Registry scope exceeds bounded root limit')
                if paths!={r['relative_path'].replace('\\','/') for r in heads}:
                    raise ValueError('Unregistered/new/removed root files need original Registry intake assessment; this rescan plan cannot silently expand')
                job={'id':job.get('id','operation-register'),'skill':'mep-document-registry','command':'rescan',
                    'source_file_ids':list(source_ids),'options':job.get('options',{})}
                if set(job['options'])-{'config'}:raise ValueError('Unsupported registry options')
                stage='01'
            else:
                allowed={('B','pdf-to-structured','extract'):'03',('B','drawing-analyzer','analyze'):'03',
                         ('B','specification-extractor','extract'):'04',('B','dwg-to-excel','ingest'):'03',
                         ('B','etl-pipeline','tabular'):'05',('D','data-quality-check','check'):'08'}
                stage=allowed.get((operation,job.get('skill'),job.get('command')))
                if not stage:raise ValueError('No safe isolated native adapter for this command; native DOC/DWG conversion and broad reviewer/map are not improvised')
                if not job.get('id') or set(job.get('source_file_ids',[]))!=set(source_ids):raise ValueError('Exact job/source IDs required')
                if job.get('kind')=='codex':raise ValueError('Instruction skill cannot be invoked as an executable agent')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',job.get('id','')):raise ValueError('Native job ID must contain only letters/numbers/hyphen/underscore')
            inventory=discover(narrowed)
            args,primary,inputs=build(narrowed,memory,job,inventory,Path(cfg['output_directory'])/'__read_only_operation_preview__')
            # build resolves known interfaces but never creates the preview directory or starts a command.
            sources={r['file_id']:r for r in __import__('master_project.evidence',fromlist=['current_files']).current_files(reader) if r['file_id'] in source_ids}
            if action!='registry_rescan':
                if len(source_ids)!=1 and job['skill']!='data-quality-check':raise ValueError('Extraction/tabular adapter needs one original source')
                represented=set()
                for path in inputs:
                    if path.suffix.lower()=='.json':
                        if path.stat().st_size>32*1024*1024:raise ValueError('Native evidence input exceeds bounded 32 MiB preflight')
                        package=read(path)
                        if package.get('schema_version')!='mep-evidence/1':raise ValueError('Native JSON input needs the existing mep-evidence/1 contract')
                        if package.get('document',{}).get('sha256') not in {r['sha256'] for r in sources.values()}:
                            raise ValueError('Derived/original SHA differs; use supported existing conversion/warning scope, never bypass native result validation')
                        document=package['document']
                        matches=[fid for fid,head in sources.items() if document.get('sha256')==head['sha256'] and
                            document.get('path') and Path(document['path']).resolve()==(Path(cfg['source_directory'])/head['relative_path']).resolve()]
                        if len(matches)!=1:raise ValueError('Ambiguous/missing original source path in native evidence package')
                        represented.add(matches[0])
                    elif job['skill'] in ('pdf-to-structured','etl-pipeline'):
                        original_paths={(Path(cfg['source_directory'])/r['relative_path']).resolve() for r in sources.values()}
                        if path.resolve() not in original_paths:raise ValueError('Native input is outside the selected original source')
                        if job['skill']=='pdf-to-structured' and path.suffix.lower()!='.pdf':raise ValueError('Native PDF extractor requires an actual registered PDF; no Word conversion adapter is invented')
                        if job['skill']=='etl-pipeline' and path.suffix.lower() not in ('.xlsx','.csv'):raise ValueError('Native tabular interface supports mapped XLSX/CSV only')
                        represented.update(fid for fid,head in sources.items() if path.resolve()==(Path(cfg['source_directory'])/head['relative_path']).resolve())
                    elif job['skill']=='dwg-to-excel':
                        raise ValueError('Mapped CAD export lineage requires existing audited equipment intake; no new unverified CAD adapter')
                if represented!=set(source_ids):raise ValueError('Native input packages do not exactly cover the declared original source identities')
                if job.get('scoped_request'):
                    from .limited_scope import job_eligibility
                    job_eligibility(narrowed,memory,stage,job)
            result_policy=None
            if operation=='B' and job['skill']=='specification-extractor':
                from .specification_layout import POLICY,LAYOUT_WARNING,validate_input
                validate_input(memory,job)
                result_policy=POLICY
                native.update(result_policy=POLICY,expected_layout_issues=[LAYOUT_WARNING],
                    warnings=['Native specification fragments may be retained UNREVIEWED with the exact layout warning; no full coverage, applicability approval, ETL or supplier release.'])
            fp=job_fingerprint(narrowed,memory,job,inventory,result_policy=result_policy)
            cached=memory.cache(stage,job['id'],fp)
            reused=bool(cached and valid_artifacts(cached['payload']) and valid_persisted(memory,cached['payload']))
            native.update(job=job,stage=stage,job_fingerprint=fp,reused=reused,
                actions=[{'kind':'existing_master_run_job','job':job,'argv_preview':args,'source_file_ids':source_ids,
                    'cached_event_id':cached['id'] if reused else None,'reused':reused,'formal_stage_completion':False}],
                input_artifacts=[{'path':str(p),'sha256':sha(p)} for p in inputs],
                skill_signatures=[{'name':r['name'],'signature':r['signature'],'available':r['available']} for r in inventory if r['name']==job['skill']])
    except (ValueError,OSError,KeyError,TypeError) as error:native['blockers'].append(str(error))
    finally:
        if memory:memory.close()
    return native


def _audit_rows(memory):
    from .limited_scope import _rows
    return [json.loads(r['payload_json'])['receipt'] for r in _rows(memory,AUDIT)]


def _append_receipt(memory,receipt,path,plan):
    from .limited_scope import _append
    return _append(memory,AUDIT,receipt,path,{'plan_fingerprint':plan['plan_fingerprint'],'source_version_basis':plan['fingerprint_basis']['source_version_basis']})


def _verify_outputs(receipt):
    for item in receipt.get('outputs',[]):
        path=Path(item['path'])
        if not path.is_file() or sha(path)!=item['sha256']:raise ValueError('Operation output missing/changed: '+str(path))
    if not receipt.get('outputs'):raise ValueError('Receipt has no verifiable persisted outputs')


def _verify_native_sources(cfg,plan):
    """Same live-source/archive contract for first execution AND successful replay."""
    for fid,version in plan['fingerprint_basis']['source_version_basis'].items():
        current=plan['fingerprint_basis']['source_currency'][fid]
        expected=current.get('live_sha256_at_assessment') or version['version']['sha256']
        original=Path(cfg['source_directory'])/version['relative_path']
        if stable_hash(original).get('sha256')!=expected:
            raise ValueError('Selected original bytes changed since explicit assessment: '+fid)
        archive=version['version'].get('archive_path')
        if not archive or stable_hash(archive).get('sha256')!=version['version']['sha256']:
            raise ValueError('Selected original archive integrity unavailable: '+fid)


def _verify_native_results(cfg,receipt):
    """Recheck original engine events/artifacts/persisted refs; no independent cache."""
    jobs=receipt.get('native_job_results')
    if not jobs:raise ValueError('Native success lacks bound job-result references; inspect legacy receipt, no automatic replay')
    m=ExistingMemory(cfg)
    try:
        verified=[]
        for result in jobs:
            row=m.conn.execute('SELECT * FROM master_events WHERE id=? AND project_id=? AND scope_id=?',
                (result.get('event_id'),cfg['project_id'],cfg.get('scope',{}).get('id','project'))).fetchone()
            if not row or row['status']!='COMPLETED' or row['job_id']!=result.get('job'):
                raise ValueError('Native completed job event unavailable/foreign: '+str(result.get('event_id')))
            payload=json.loads(row['payload_json'])
            if not valid_artifacts(payload):
                raise ValueError('Native job output artifacts missing/changed: '+str(row['id'])+' job '+str(row['job_id']))
            if not valid_persisted(m,payload):
                raise ValueError('Native job persisted evidence missing/historical: '+str(row['id']))
            verified.append({'event_id':row['id'],'job':row['job_id'],'stage':row['stage'],'job_fingerprint':row['fingerprint'],
                'artifacts':payload['artifacts'],'persisted_refs':payload.get('persisted_refs',[])})
        if receipt.get('native_dependencies') is not None and receipt['native_dependencies']!=verified:
            raise ValueError('Native successful receipt dependency identities changed')
        return verified
    finally:m.close()


def _basis_changes(original,fresh):
    from .operation_workflow import stable_work_basis
    left,right=stable_work_basis(original),stable_work_basis(fresh)
    return ', '.join(k for k in sorted(set(left)|set(right)) if left.get(k)!=right.get(k)) or 'eligibility'


def reusable_supplier(reader,compiled,descriptor):
    """Verify the existing P1-03 receipt/compilation/files; no generation or new approval."""
    if not descriptor:return None
    path=resolve(Path(reader.cfg['config_path']).parent,descriptor['path'])
    if not path.is_file() or sha(path)!=descriptor['sha256']:raise ValueError('Reusable supplier receipt missing/changed')
    receipt=read(path);root=path.parent.parent.resolve()
    original=root/'internal/compilation.json'
    if receipt.get('status')!='COMPLETED_DRAFT' or not original.is_file():raise ValueError('No complete existing P1-03 draft compilation')
    previous=read(original)
    material=lambda value:{k:v for k,v in value.items() if k not in ('content_fingerprint','currency_assessment')}
    if material(previous)!=material(compiled) or receipt.get('content_fingerprint')!=previous.get('content_fingerprint'):
        raise ValueError('Supplier compilation evidence/options/contract changed; do not reuse')
    outputs=[]
    expected={(f['family'],tuple(r['tag'] for r in f['equipment'])) for f in compiled['families']}
    actual=set()
    for package in receipt['packages']:
        directory=Path(package['path']).resolve()
        if not directory.is_relative_to(root):raise ValueError('Supplier package escapes its registered receipt root')
        manifest_path=directory/'internal/provenance-manifest.json';manifest=read(manifest_path)
        actual.add((package['family'],tuple(manifest['scope_tags'])))
        if manifest['content_fingerprint']!=previous['content_fingerprint'] or manifest.get('draft_only') is not True:raise ValueError('Supplier provenance manifest mismatch')
        for file in package['files']:
            f=Path(file['path']).resolve()
            if not f.is_relative_to(directory) or not f.is_file() or sha(f)!=file['sha256']:raise ValueError('Supplier document missing/changed')
            outputs.append({'path':str(f),'sha256':file['sha256'],'role':'REUSED_DRAFT_SUPPLIER_DOCUMENT'})
        outputs.append({'path':str(manifest_path),'sha256':sha(manifest_path),'role':'REUSED_INTERNAL_PROVENANCE'})
    if actual!=expected:raise ValueError('Reusable package equipment scope differs')
    _supplier_formats(outputs)
    return {'receipt_path':str(path),'receipt_sha256':sha(path),'outputs':outputs,'original_content_fingerprint':previous['content_fingerprint'],
        'current_compilation_fingerprint':compiled['content_fingerprint'],
        'snapshot_metadata_changed':previous.get('currency_assessment')!=compiled.get('currency_assessment'),
        'basis':'All saved facts, source statuses, identities, options and review/limitation content match. Supplier files retain their original explicitly dated assessment.'}


def _supplier_formats(outputs):
    from pypdf import PdfReader
    for item in outputs:
        path=Path(item['path'])
        if path.suffix.lower() in ('.xlsx','.docx'):
            if not zipfile.is_zipfile(path):raise ValueError('Invalid office document container')
            with zipfile.ZipFile(path) as archive:
                expected='xl/workbook.xml' if path.suffix.lower()=='.xlsx' else 'word/document.xml'
                if expected not in archive.namelist():raise ValueError('Missing required Office document part')
        elif path.suffix.lower()=='.pdf':
            pdf=PdfReader(path)
            if not pdf.pages or 'DRAFT' not in (pdf.pages[0].extract_text() or ''):raise ValueError('Draft PDF missing pages/status')


def execute_operation(cfg,plan,*,authorized_plan_fingerprint,actor,reason,currency_snapshot=None,allow_native_processing=False,executor_role='main',runtime=None):
    from .operation_workflow import PLAN,identity,assess_operation,operation_reader
    if executor_role!='main':raise PermissionError('Only the main agent/operator may execute; subagent recommendations are read-only')
    if not actor or not reason or plan.get('schema_version')!=PLAN or identity(plan)!=plan.get('plan_fingerprint') or authorized_plan_fingerprint!=plan['plan_fingerprint']:
        raise PermissionError('Exact inspected plan authorization plus actor/reason required; preview is not authorization')
    if plan['project_id']!=cfg['project_id']:raise ValueError('Foreign operation plan')
    request=plan['fingerprint_basis']['request'];native=bool(plan['fingerprint_basis']['native_plan'])
    if native and not allow_native_processing:raise PermissionError('Explicit native-processing authorization required')
    if plan['eligibility'] not in ('READY','READY_WITH_LIMITATIONS'):raise ValueError('Operation is not eligible: '+plan['eligibility'])
    # One reservation in existing audit under the existing project lock prevents duplicate starts.
    with project_lock(cfg):
        with_reader=operation_reader(cfg,currency_snapshot)
        try:
            fresh,projection,compiled=assess_operation(with_reader,request)
            if native:_verify_native_sources(cfg,fresh)
            if fresh['plan_fingerprint']!=plan['plan_fingerprint'] or fresh['eligibility'] not in ('READY','READY_WITH_LIMITATIONS'):
                raise ValueError('Scoped work basis/eligibility changed ('+_basis_changes(plan,fresh)+'); inspect a fresh plan; blockers: '+str(fresh['reasons']['blockers']))
            out=Path(fresh['expected_outputs']['directory'])
            memory=ExistingMemory(cfg,writable=True)
            try:
                prior=[r for r in _audit_rows(memory) if r['plan_fingerprint']==fresh['plan_fingerprint']]
                completed=[r for r in prior if r['execution_state']=='SUCCEEDED']
                if completed:
                    saved=completed[-1]
                    if saved.get('verification',{}).get('completed') is not True:raise ValueError('Successful receipt has incomplete output verification')
                    _verify_outputs(saved)
                    if native:_verify_native_results(cfg,saved)
                    return {**saved,'idempotent_reuse':True,'new_processing_actions':[],
                        'replay_verification':{'stable_work_basis_matches':True,'output_hashes_verified':True,
                            'native_sources_and_dependencies_verified':native,'new_execution':False}}
                if prior:raise ValueError('An interrupted/failed operation attempt exists; inspect its receipt and use a new explicit output/attempt scope')
                if out.exists():raise FileExistsError('New operation output directory required; previous/partial results are not overwritten')
                receipt={'schema_version':RECEIPT,'operation_id':uuid.uuid4().hex,'project_id':cfg['project_id'],
                    'scope_id':cfg.get('scope',{}).get('id','project'),'operation':fresh['operation'],'operation_scope':request,
                    'plan_fingerprint':fresh['plan_fingerprint'],'actor':actor,'reason':reason,'engineering_approval':False,
                    'identity_assurance':'Operator authorization assertion, not independently authenticated identity',
                    'execution_state':'RUNNING','started_at':now(),'actual_source_ids':fresh['resolved_source_ids'],
                    'source_and_configuration_basis':fresh['fingerprint_basis'],'reused_evidence':fresh['reused_evidence'],
                    'new_processing_actions':[],'warnings':fresh['reasons']['warnings'],'limitations':fresh['source_limitations'],
                    'review_summary':fresh['review_summary'],'formal_stage_completion':False,'procurement_release_authorized':False,
                    'outputs':[],'verification':{'completed':False}}
                start=out/'start-receipt.json';with_reader.write_json(start,receipt)
                with_reader.close()  # Release SQLite read lock before the audit writer commits.
                _append_receipt(memory,receipt,start,fresh)
            finally:memory.close()
        finally:with_reader.close()
    # Native scoped executors own the same project lock; never nest locks or weaken their revalidation.
    try:
        native_plan=fresh['fingerprint_basis']['native_plan']
        if native_plan and native_plan['adapter'] in ('equipment_import','matching_proposals'):
            # Both native modules re-check their own exact source inventory/authorization/upstream state.
            if sha(native_plan['plan_path'])!=native_plan['plan_sha256']:raise ValueError('Native plan changed after authorization')
            if native_plan['adapter']=='equipment_import':
                # Replace only the coarse completion gate with the exact native source contract.
                # Existing assess_job + run_job still enforce source receipts/provenance, inputs,
                # warning disposition, matching config, import validation and immutable job audits.
                from .engine import run_job
                from .discovery import discover
                with project_lock(cfg):
                    with operation_reader(cfg,currency_snapshot) as reader:
                        checked,_,_=assess_operation(reader,request)
                        if checked['plan_fingerprint']!=fresh['plan_fingerprint']:raise ValueError('Native import basis changed after reservation')
                    narrowed=_native_cfg(cfg,fresh['resolved_source_ids']);m=ExistingMemory(narrowed,writable=True)
                    try:
                        native_jobs=read(native_plan['plan_path'])['jobs']
                        inventory=discover(narrowed)
                        results=[run_job(narrowed,m,'06',job,inventory) for job in native_jobs]
                        if any(r.get('status')!='COMPLETED' for r in results):raise ValueError('Native scoped import did not validate all required job outputs')
                        result={'operation_status':'COMPLETED_UNREVIEWED','results':results,'formal_stage_completion':False,
                            'engineering_approval_created':False,'source_specific_gate':native_plan['source_specific_gate']}
                        from .limited_scope import _append,snapshot
                        native_receipt=out/'native-import-receipt.json';write(native_receipt,{**result,'actor':actor,'reason':reason})
                        result['audit']=_append(m,'equipment_scope_execution',{**result,'actor':actor,'reason':reason},native_receipt,snapshot(cfg,m))
                        result['result_path']=str(native_receipt)
                    finally:m.close()
            else:
                from .matching_scope import execute
                result=execute(_native_cfg(cfg,cfg.get('scope',{}).get('file_ids',[])),native_plan['plan_path'])
            succeeded=result.get('operation_status')=='COMPLETED_UNREVIEWED'
            if not succeeded:raise ValueError('Native operation reports incomplete execution')
            receipt['new_processing_actions']=[{'adapter':native_plan['adapter'],'result':result}]
            receipt['native_job_results']=result['results'] if native_plan['adapter']=='equipment_import' else [result['job_result']]
        else:
            with project_lock(cfg):
                with operation_reader(cfg,currency_snapshot) as reader:
                    rechecked,_,_=assess_operation(reader,request)
                    if rechecked['plan_fingerprint']!=fresh['plan_fingerprint']:raise ValueError('Evidence changed after reservation; operation not executed')
                    if native_plan:
                        reader.close()  # Native job/audit writers must not compete with our read snapshot.
                        _verify_native_sources(cfg,fresh)
                        from .engine import run_job
                        from .discovery import discover
                        narrowed=_native_cfg(cfg,fresh['resolved_source_ids'])
                        m=ExistingMemory(narrowed,writable=True)
                        try:
                            policy=native_plan.get('result_policy')
                            if policy:m.operation_result_scope=('B','native_job')
                            result=run_job(narrowed,m,native_plan['stage'],native_plan['job'],discover(narrowed),**({'result_policy':policy} if policy else {}))
                        finally:m.close()
                        if result['status']!='COMPLETED':raise ValueError('Native job not completed')
                        receipt['native_job_results']=[result]
                        receipt['new_processing_actions']=[] if result.get('reused') else [result]
                        payload={'native_job_result':result,'full_source_coverage':False,'engineering_approval_created':False}
                        if result.get('validation'):
                            receipt['evidence_acceptance']=result['validation']
                            receipt['accepted_native_warnings']=result['validation']['accepted_issues']
                    elif fresh['operation']=='E':
                        reused=reusable_supplier(reader,compiled,request.get('reuse_supplier_receipt'))
                        if reused:
                            receipt['outputs'].extend(reused['outputs']);payload={'reused_supplier_package':reused}
                        else:
                            from .supplier_draft import generate_supplier_drafts
                            bound=fresh['fingerprint_basis']['supplier_runtime'] or {}
                            selected={k:bound[k] for k in ('node_executable','artifact_module_root') if k in bound}
                            if runtime is not None and runtime!=selected:raise PermissionError('Rendering runtime differs from the authorized plan')
                            result=generate_supplier_drafts(reader,request['supplier_options'],out/'supplier-drafts',**selected)
                            if result['status']!='COMPLETED_DRAFT':raise ValueError('Supplier generator not complete')
                            for package in result['packages']:
                                receipt['outputs'].extend({'path':f['path'],'sha256':f['sha256'],'role':'DRAFT_SUPPLIER_DOCUMENT'} for f in package['files'])
                            _supplier_formats(receipt['outputs'])
                            payload={'supplier_generation':result,'reviewed_annotations':fresh['review_summary'],'status':'DRAFT \u2014 FOR TECHNICAL REVIEW'}
                    else:payload={'projection':projection,'source_currency':fresh['source_currency'],'limitations':fresh['source_limitations'],
                        'declared_coverage_limitations':fresh['declared_coverage_limitations'],'reviewed_annotations':fresh['review_summary'],
                        'scope_only':True,'full_source_coverage':False,'engineering_approval_created':False}
                    data=out/'projection.json'
                    if native_plan:write(data,payload)  # Root was validated and created through reader safety before reservation.
                    else:reader.write_json(data,payload)
                    receipt['outputs'].append({'path':str(data),'sha256':sha(data),'role':'SCOPED_OPERATION_OUTPUT'})
        if native_plan and native_plan['adapter'] in ('equipment_import','matching_proposals'):
            data=out/'native-result.json';write(data,receipt['new_processing_actions'])
            receipt['outputs'].append({'path':str(data),'sha256':sha(data),'role':'NATIVE_VALIDATED_RESULT'})
            native_result=receipt['new_processing_actions'][0]['result']
            if native_result.get('result_path'):
                path=Path(native_result['result_path']);receipt['outputs'].append({'path':str(path),'sha256':sha(path),'role':'NATIVE_PERSISTED_RECEIPT'})
        _verify_outputs(receipt)
        if native:receipt['native_dependencies']=_verify_native_results(cfg,receipt)
        receipt.update(execution_state='SUCCEEDED',finished_at=now(),verification={'completed':True,'output_hashes_verified':True,
            'native_validators_retained':bool(native_plan),'whole_stage_completion_created_by_layer':False})
    except BaseException as error:
        receipt.update(execution_state='FAILED_PARTIAL',finished_at=now(),error=type(error).__name__+': '+str(error),
            partial_output_directory=str(out),verification={'completed':False})
        with project_lock(cfg):
            final=out/'failed-receipt.json';write(final,receipt)
            m=ExistingMemory(cfg,writable=True)
            try:_append_receipt(m,receipt,final,fresh)
            finally:m.close()
        raise
    with project_lock(cfg):
        final=out/'operation-receipt.json';write(final,receipt)
        m=ExistingMemory(cfg,writable=True)
        try:_append_receipt(m,receipt,final,fresh)
        finally:m.close()
    return receipt


def operation_receipts(cfg,*,operation=None,limit=25,offset=0):
    from .evidence_reader import EvidenceReader
    with EvidenceReader(cfg) as reader:
        reader.bounds(limit,offset)
        if not reader.has('master_operator_events','payload_json'):return {'schema_version':RECEIPT,'items':[],'total':0,'audit_available':False}
        rows=reader.conn.execute('SELECT payload_json FROM master_operator_events WHERE project_id=? AND scope_id=? AND action=? ORDER BY rowid',
            (cfg['project_id'],cfg.get('scope',{}).get('id','project'),AUDIT))
        values=[json.loads(r[0])['receipt'] for r in rows]
        values=[r for r in values if operation is None or r['operation']==operation]
        return {'schema_version':RECEIPT,'items':values[offset:offset+limit],'total':len(values),'limit':limit,'offset':offset,
            'next_offset':offset+limit if offset+limit<len(values) else None,'audit_available':True}
