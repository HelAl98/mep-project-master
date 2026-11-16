"""Exact-current-dataset matching authorization; native matcher only, no stage completion."""
import json
from pathlib import Path
from .common import read,write,key
from .memory import Memory,project_lock,tables
from .limited_scope import need,_file,_path,_lookup,_append,_envelope,_limitation,_rows,snapshot
from .equipment_scope import upstream,validate_item
OP='06:mep-equipment-matcher.match'

def dataset(cfg,m):
    from .evidence import current_files
    files={r['file_id']:r for r in current_files(m)};latest={}
    for row in m.conn.execute('SELECT * FROM eq_imports WHERE project_id=? ORDER BY rowid',(cfg['project_id'],)):
        if row['file_id'] in files and row['analysis_id']==files[row['file_id']]['analysis_id']:latest[(row['file_id'],row['slot'])]=dict(row)
    imports=sorted(latest.values(),key=lambda r:r['id']);ids={r['id'] for r in imports}
    occurrences=[dict(r) for r in m.conn.execute('SELECT * FROM eq_occurrences WHERE project_id=? ORDER BY id',(cfg['project_id'],)) if r['import_id'] in ids]
    oids={r['id'] for r in occurrences};parameters=[dict(r) for r in m.conn.execute('SELECT * FROM eq_parameters WHERE project_id=? ORDER BY id',(cfg['project_id'],)) if r['occurrence_id'] in oids]
    identity=[{'import_id':r['id'],'file_id':r['file_id'],'sha256':files[r['file_id']]['sha256'],'analysis_id':r['analysis_id'],'role':r['role'],'slot':r['slot']} for r in imports]
    reviews={t:[list(r) for r in m.conn.execute('SELECT * FROM '+t+' WHERE project_id=? ORDER BY rowid',(cfg['project_id'],))] for t in ('eq_reviews','registry_reviews')}
    return identity,key({'occurrences':occurrences,'parameters':parameters,'reviews':reviews}),imports,occurrences

def assess(cfg,m,r):
    _envelope(cfg,r)
    need(r.get('schema_version')=='mep-matching-scope/1' and r.get('operation')==OP and r.get('full_source_coverage') is False and r.get('technical_findings_promoted') is False,'Unsupported matching scope')
    need(r.get('limitations') and r.get('context_limitation_ids'),'Accepted explicit matching limitations required')
    basis=snapshot(cfg,m)
    for identity in r['context_limitation_ids']:need(OP in _limitation(cfg,m,identity,basis)['allowed_operations'],'Current acceptance does not authorize matching')
    cfgpath=_file(cfg,r['matching_config']);need(str(cfgpath)==cfg.get('matching_config'),'Matching configuration differs from audited file')
    config=read(cfgpath);need(config.get('auto_confirm') is False,'Automatic confirmation prohibited')
    identity,fingerprint,imports,occurrences=dataset(cfg,m)
    need(identity==r['imports'] and fingerprint==r['dataset_fingerprint'],'Current dataset/reviews differ from audited matching scope')
    equipment=_lookup(m,'equipment_evidence_scope',r['equipment_scope_id'])
    need(equipment['basis']==basis,'Upstream equipment source receipt stale')
    items={i['original']['file_id']:i for i in equipment['receipt']['items']}
    need({i['file_id'] for i in identity}==set(items),'Native matcher has no filter: extra/missing current source imports block scoped matching')
    for imported,ident in zip(imports,identity):
        item=items[ident['file_id']];need(ident['role']==item['role'] and ident['slot']==item['slot'] and ident['sha256']==item['original']['sha256'],'Scope source/role/slot mismatch')
        package,points=validate_item(cfg,m,item)
        need(json.loads(imported['manifest_json'])['config']==config,'All current imports require the exact native matching config')
        need(json.loads(imported['issues_json'])==package['issues'] and imported['status'] in ('processed','partial'),'Retained extraction issues or import status changed')
    allowed=set(r['allowed_disciplines'])
    need(occurrences and all(json.loads(o['data_json']).get('discipline') in allowed for o in occurrences),'Unrelated equipment discipline present')
    need(all(json.loads(o['raw_json'])['review']['status'] in ('unreviewed','needs_review') for o in occurrences),'Unexpected promoted input record')
    return {'eligible':True,'eligibility_kind':'MATCHING_PROPOSALS_ONLY','operation':OP,'source_file_ids':sorted(items),'imports':identity,'dataset_fingerprint':fingerprint,'limitations':r['limitations'],'full_source_coverage':False,'engineering_approval':False}

def record(cfg,path):
    p=_path(cfg,path);r=read(p);need(p.is_relative_to(Path(cfg['output_directory'])),'Matching receipt must be in project output')
    with project_lock(cfg):
        m=Memory(cfg,writable=True)
        try:
            upstream(cfg,m);result=assess(cfg,m,r);audit=_append(m,'matching_evidence_scope',r,p,snapshot(cfg,m));return {**audit,'eligibility':result}
        finally:m.close()

def assess_job(cfg,m,job):
    request=read(_path(cfg,job['scoped_request']));payload=_lookup(m,'matching_evidence_scope',request['receipt_id'])
    need(payload['basis']==snapshot(cfg,m),'Matching scope stale after source changes')
    result=assess(cfg,m,payload['receipt'])
    need(request.get('project_id')==cfg['project_id'] and request.get('scope_id')==cfg['scope']['id'] and request.get('operation')==OP,'Foreign matching request')
    need(job['skill']=='mep-equipment-matcher' and job['command']=='match' and job.get('options',{})=={} and not job.get('inputs'),'Only native matching, without extraction/filter overrides, is authorized')
    need(set(job['source_file_ids'])==set(result['source_file_ids']),'Matching job source IDs differ from audited set')
    return {**result,'receipt_id':request['receipt_id']}

def execute(cfg,plan_path):
    from .engine import run_job
    plan=read(_path(cfg,plan_path));_envelope(cfg,plan);target=_path(cfg,plan['result_path'])
    need(target.is_relative_to(Path(cfg['output_directory'])) and not target.exists(),'New output within project required')
    with project_lock(cfg):
        m=Memory(cfg,writable=True)
        try:
            inv=upstream(cfg,m);job=plan['job'];eligible=assess_job(cfg,m,job)
            need(not any(json.loads(row['payload_json'])['receipt'].get('matching_scope_id')==eligible['receipt_id'] for row in _rows(m,'matching_scope_execution')),'This one-operation matching authorization has already been used')
            oldruns=[r[0] for r in m.conn.execute('SELECT id FROM eq_runs WHERE project_id=?',(cfg['project_id'],))]
            need(oldruns==plan['prior_run_ids'],'Matching runs changed since execution plan')
            result=run_job(cfg,m,'06',job,inv);need(result['status']=='COMPLETED','Native matching operation incomplete')
            event=m.latest('06',job['id']);response=read(event['payload']['primary_output']);run=m.conn.execute('SELECT * FROM eq_runs WHERE id=?',(response.get('run_id'),)).fetchone()
            need(run and run['project_id']==cfg['project_id'],'Native matching run not persisted')
            need(dataset(cfg,m)[1]==eligible['dataset_fingerprint'],'Input dataset changed during matching')
            output={'project_id':cfg['project_id'],'scope_id':cfg['scope']['id'],'actor':plan['actor'],'reason':plan['reason'],'engineering_approval':False,'matching_scope_id':eligible['receipt_id'],'native_response':response,'job_result':result,'operation_status':'COMPLETED_UNREVIEWED','formal_stage_completion':False,'downstream_stages_started':False}
            write(target,output);audit=_append(m,'matching_scope_execution',output,target,snapshot(cfg,m));return {**output,'audit':audit,'result_path':str(target)}
        finally:m.close()
