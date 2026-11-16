"""Audited equipment intake only, through existing master adapters; no matching/stage completion."""
from pathlib import Path
import json,re,math
from .common import read,write,sha,key,resolve
from .memory import Memory,project_lock
from .limited_scope import need,_file,_path,_source,_lookup,_append,_envelope,_limitation,snapshot,warning_inventory
OP='06:mep-equipment-matcher.import-json'

def upstream(cfg,m):
    from .engine import stage_signature,jobs_for,job_fingerprint
    from .discovery import discover
    from .evidence import valid_artifacts,valid_persisted
    inv=discover(cfg)
    for stage in ('01','02'):
        e=m.latest(stage)
        need(e and e['status']=='COMPLETED' and e['fingerprint']==stage_signature(cfg,m,stage,inv),'Current Stage01/02 prerequisite required')
        for j in jobs_for(cfg,stage):
            e=m.cache(stage,j['id'],job_fingerprint(cfg,m,j,inv))
            need(e and valid_artifacts(e['payload']) and valid_persisted(m,e['payload']),'Unchanged upstream outputs required')
    return inv

def _cad_cell(native,cell):
    i=cell.get('native_row_index')
    need(type(i) is int and 0<=i<len(native),'Invalid native row index')
    row=native[i]
    need(row['Handle']==cell['handle'] and row['Text']==cell['raw_text'] and cell['worksheet_row']==i+2,'Changed CAD cell text/handle/worksheet locator')
    need(all(math.isclose(float(row[k.upper()]),float(cell['coordinates'][k]),rel_tol=1e-12,abs_tol=1e-6) for k in ('x','y','z')),'Changed native coordinates')
    return row

def validate_item(cfg,m,item):
    src,original=_source(m,item['original']);p=_file(cfg,item['package'],True);package=read(p)
    doc=package.get('document',{})
    need(package.get('schema_version') in ('mep-equipment-observations/1','mep-evidence/1') and package.get('records'),'Equipment observation package required')
    need(doc.get('sha256')==src['sha256'] and _path(cfg,doc['path'])==original,'Original source identity mismatch')
    need(item.get('role') in ('drawing','schedule','electrical','bms') and item.get('slot'),'Explicit equipment role/slot required; BOQ outside this contract')
    warnings=warning_inventory(package)
    need(item.get('retained_warning_digest')==key(warnings) and item.get('warning_policy')=='retain_all_unreviewed_no_coverage_claim','Exact retained warning audit required')
    provenance=item['provenance'];kind=provenance['kind'];native=None;workbook=None
    if kind=='cad':
        need(original.suffix.lower() in ('.dwg','.dxf'),'CAD provenance needs original CAD source')
        native_package=read(_file(cfg,provenance['rows'],True));native=native_package['rows']
        dxf=_file(cfg,provenance['dxf'],True);_file(cfg,provenance['workbook'],True)
        conversion=read(_file(cfg,provenance['conversion'],True))
        need(native_package['source_file_id']==src['file_id'] and native_package['source_sha256']==src['sha256'],'Native rows original mismatch')
        need(native_package['export_dxf_sha256']==sha(dxf) and conversion['source_sha256']==src['sha256'] and conversion['export_sha256']==sha(dxf),'Native conversion/export hash relationship mismatch')
        for d in provenance.get('supporting_artifacts',[]):_file(cfg,d,True)
    elif kind=='xlsx':
        need(original.suffix.lower()=='.xlsx','Only native XLSX tabular source supported; no inferred legacy XLS adapter')
        from openpyxl import load_workbook
        workbook=load_workbook(original,data_only=False,read_only=True)
    else:raise ValueError('Unsupported equipment provenance kind')
    footprints=[]
    try:
        for i,r in enumerate(package['records']):
            data=r.get('data',{});source=r.get('source',{});review=r.get('review',{})
            need(r.get('kind')=='equipment' and isinstance(r.get('raw_text'),str) and source.get('method'),'Nonempty source-linked equipment record required')
            need(review.get('status') in ('unreviewed','needs_review') and data.get('physical_instance_confirmed') is not True and data.get('physical_quantity_confirmed') is not True,'Equipment intake cannot assert engineering acceptance')
            need(data.get('discipline') in item['allowed_disciplines'] and data.get('role')==item['role'],'Record discipline/role outside declared scope')
            need(data.get('identity_kind') in ('reference','type','group','instance'),'Explicit candidate identity kind required')
            if kind=='cad':
                index=source.get('native_row_index',source.get('row',0)-2)
                need(type(index) is int and 0<=index<len(native),'Invalid native annotation index')
                row=native[index]
                need(row['Handle']==source.get('handle') and row['Layer']==source.get('layer') and source.get('row')==index+2,'CAD entity lineage mismatch')
                need(r['raw_text']==(row.get('Text') or '') and str(data.get('tag') or '') in r['raw_text'],'Tag/raw annotation source mismatch')
                coords=source.get('coordinates',{})
                need(all(math.isclose(float(row[k.upper()]),float(coords[k]),rel_tol=1e-12,abs_tol=1e-6) for k in ('x','y','z')),'Annotation coordinate mismatch')
                for param in data.get('parameters',[]):
                    cells=param.get('source_cells',[]);need(cells,'Scheduled parameter requires native source-cell proof')
                    for c in cells:_cad_cell(native,c)
                    if param.get('unit'):
                        need(any(str(param['unit']).casefold() in str(v.get('Text','')).casefold() for v in native if v.get('Container')==row.get('Container')),'Printed parameter unit evidence missing')
                    values=list(dict.fromkeys(c['raw_text'] for c in cells))
                    need(param.get('raw_values')==values and param.get('value')==(values[0] if len(values)==1 else None),'Parameter raw values changed')
                if data.get('quantity') is not None:
                    proof=next((q for q in item.get('quantity_proofs',[]) if q['record_index']==i),None)
                    need(proof,'Explicit declared quantity proof required; no assumed quantity')
                    value=_cad_cell(native,proof['cell']);header=native[proof['header_native_row_index']]
                    need(value['Text']==str(data['quantity']) and re.sub('[^A-Z]','',header.get('Text','').upper()) in ('QTY','QYT','QUANTITY'),'Quantity/printed header proof mismatch')
                footprints.append([src['file_id'],row['Handle'],data['tag']])
            else:
                sheet=source.get('sheet');need(sheet in workbook.sheetnames and type(source.get('row')) is int,'Actual worksheet and row required')
                bindings=next((b for b in item.get('cell_bindings',[]) if b['record_index']==i),None)
                need(bindings and bindings.get('fields'),'Explicit tabular field/cell bindings required')
                for field,address in bindings['fields'].items():
                    cell=workbook[sheet][address];value=cell.value
                    need(cell.row==source['row'],'Tabular binding outside declared source row')
                    need(not (isinstance(value,str) and value.startswith('=')),'Formula values remain unsupported/unresolved for equipment intake')
                    need(field in ('tag','quantity','description','floor','room') and data.get(field)==value,'Tabular field value/cell mismatch')
                need(set(data)-{'tag','quantity','description','floor','room','discipline','role','identity_kind','parameters'}==set() and not data.get('parameters'),'Tabular parameters need a separate verified adapter; unsupported fields remain blocked')
                need('tag' in bindings['fields'] and (data.get('quantity') is None or 'quantity' in bindings['fields']),'Tag/quantity cells required')
                footprints.append([src['file_id'],sheet,source['row'],data['tag']])
    finally:
        if workbook:workbook.close()
    return package,footprints

def record(cfg,path):
    p=_path(cfg,path);r=read(p);_envelope(cfg,r)
    need(r.get('schema_version')=='mep-equipment-scope/1' and r.get('allowed_operation')==OP and r.get('full_source_coverage') is False,'Unsupported equipment scope contract')
    need(r.get('technical_findings_promoted') is False and r.get('limitations') and r.get('context_limitation_ids'),'Unreviewed coverage limitations and acceptance required')
    need(p.is_relative_to(Path(cfg['output_directory'])),'Receipt must remain in project outputs')
    with project_lock(cfg):
        m=Memory(cfg,writable=True)
        try:
            upstream(cfg,m);basis=snapshot(cfg,m)
            for identity in r['context_limitation_ids']:need(OP in _limitation(cfg,m,identity,basis)['allowed_operations'],'Current human acceptance for equipment operation required')
            unique=set();footprints=set()
            for item in r['items']:
                identity=(item['original']['file_id'],item['slot']);need(identity not in unique,'Duplicate source/slot');unique.add(identity)
                package,points=validate_item(cfg,m,item)
                for point in points:
                    keypoint=key(point);need(keypoint not in footprints,'Overlapping source observation views');footprints.add(keypoint)
            return _append(m,'equipment_evidence_scope',r,p,basis)
        finally:m.close()

def assess_job(cfg,m,job):
    request=read(_path(cfg,job['scoped_request']));payload=_lookup(m,'equipment_evidence_scope',request['receipt_id']);r=payload['receipt']
    need(payload['basis']==snapshot(cfg,m),'Equipment receipt stale after source/version changes')
    need(request['project_id']==cfg['project_id'] and request['scope_id']==cfg['scope']['id'] and request['operation']==OP,'Foreign equipment request')
    for identity in r['context_limitation_ids']:need(OP in _limitation(cfg,m,identity,payload['basis'])['allowed_operations'],'Equipment acceptance missing/retired')
    item=r['items'][request['item_index']]
    need(job['skill']=='mep-equipment-matcher' and job['command']=='import-json' and job.get('source_file_ids')==[item['original']['file_id']],'Only exact equipment JSON intake permitted')
    need([str(_path(cfg,v)) for v in job['inputs']]==[str(_path(cfg,item['package']['path']))],'Intake package outside audited item')
    need(job['options']=={'file-id':item['original']['file_id'],'role':item['role'],'slot':item['slot']},'Intake role/slot/source mismatch')
    validate_item(cfg,m,item)
    return {'eligible':True,'eligibility_kind':'EQUIPMENT_IMPORT_ONLY','operation':OP,'receipt_id':request['receipt_id'],'item_index':request['item_index'],'item':item,'full_source_coverage':False,'engineering_approval':False,'limitations':r['limitations']}

def validate_import(m,job,response,scoped):
    item=scoped['item'];package=read(_file(m.cfg,item['package'],True));row=m.conn.execute('SELECT * FROM eq_imports WHERE id=?',(response.get('import_id'),)).fetchone()
    need(row and row['project_id']==m.cfg['project_id'] and row['file_id']==item['original']['file_id'] and row['role']==item['role'] and row['slot']==item['slot'],'Returned import identity/role/slot mismatch')
    need(row['status'] in ('processed','partial') and json.loads(row['issues_json'])==package.get('issues',[]),'Retained import issues changed')
    rows=m.conn.execute('SELECT raw_json FROM eq_occurrences WHERE import_id=? ORDER BY rowid',(row['id'],)).fetchall()
    need([json.loads(r[0]) for r in rows]==package['records'],'Imported equipment payload/count differs from audited package')
    return [{'table':'eq_imports','id':row['id']}]

def execute(cfg,plan_path):
    from .engine import run_job
    p=_path(cfg,plan_path);plan=read(p);_envelope(cfg,plan)
    with project_lock(cfg):
        m=Memory(cfg,writable=True)
        try:
            inv=upstream(cfg,m);jobs=plan['jobs'];need(jobs and len({j['id'] for j in jobs})==len(jobs),'Unique explicit import jobs required')
            # Eligibility checks before first write; no matching command or formal stage event.
            for job in jobs:assess_job(cfg,m,job)
            results=[]
            for job in jobs:
                try:results.append(run_job(cfg,m,'06',job,inv))
                except Exception as exc:results.append({'job':job['id'],'status':'FAILED','reason':str(exc)})
            output={'project_id':cfg['project_id'],'scope_id':cfg['scope']['id'],'actor':plan['actor'],'reason':plan['reason'],'engineering_approval':False,'results':results,'operation_status':'COMPLETED_UNREVIEWED' if all(r['status']=='COMPLETED' for r in results) else 'INCOMPLETE','formal_stage_completion':False,'matching_executed':False}
            target=_path(cfg,plan['result_path']);need(target.is_relative_to(Path(cfg['output_directory'])),'Execution result must remain in project outputs');write(target,output)
            audit=_append(m,'equipment_scope_execution',output,target,snapshot(cfg,m))
            return {**output,'audit':audit,'result_path':str(target)}
        finally:m.close()
