"""One generic integration fixture against the selected installed Master CLI.

Human dispositions below are explicitly synthetic test assertions, not approvals
of any real project. Installation files are read only; fixture state stays outside them. No historical project is touched.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from openpyxl import Workbook, load_workbook
from docx import Document
from reportlab.pdfgen.canvas import Canvas

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--master',type=Path,default=Path(__file__).resolve().parents[2])
parser.add_argument('--fixture',type=Path,required=True)
parser.add_argument('--outputs',type=Path,required=True)
parser.add_argument('--resume-fixture',action='store_true',help='Reuse the same synthetic source files after a code correction')
test_options=parser.parse_args()
DEV=test_options.master.resolve();BASE=test_options.fixture.resolve();OUT=test_options.outputs.resolve()
if BASE.is_relative_to(DEV) or OUT.is_relative_to(DEV):raise ValueError('Test data must stay outside the installed skill')
sys.path.insert(0,str(DEV/'scripts'))
from master_project.procurement import prepare, snapshot, _last_state
from master_project.memory import connect
from master_project.procurement_geometry import measure, ACTION
from master_project import procurement_items

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def command(action, *args, cfg=None):
    argv=[sys.executable,'-X','utf8','-B',str(DEV/'scripts/master.py')]
    if cfg:argv+=['--config',str(cfg)]
    process=subprocess.run(argv+['procurement',action]+list(args),text=True,encoding='utf-8',capture_output=True,timeout=120)
    if process.returncode:raise RuntimeError(process.stderr+'\n'+process.stdout)
    return json.loads(process.stdout)

def blocked(action,*args,cfg):
    argv=[sys.executable,'-X','utf8','-B',str(DEV/'scripts/master.py'),'--config',str(cfg),'procurement',action]+list(args)
    p=subprocess.run(argv,text=True,encoding='utf-8',capture_output=True,timeout=120)
    assert p.returncode!=0 and 'FOR ISSUE blocked' in p.stderr+p.stdout,(p.returncode,p.stdout,p.stderr)
    return p.stderr+p.stdout

def save_request(name,data):
    p=BASE/(name+'.json');p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return str(p)

def count_state(cfg):
    with sqlite3.connect(cfg['database']) as db:
        return {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('records','runs','master_procurement_links','master_procurement_sources')} | {
          'measurement_events':db.execute('SELECT count(*) FROM master_operator_events WHERE action=?',(ACTION,)).fetchone()[0]}

def build():
    if BASE.exists():raise FileExistsError('Preserve prior fixture; use resume mode for debugging, never overwrite')
    src=BASE/'sources';src.mkdir(parents=True)
    wb=Workbook();ws=wb.active;ws.title='BOQ'
    ws.append(['Item No','Item Type','Description','Service','Size','Material','Pipe Schedule','Pressure Class','Connection','Quantity (m)','Unit','Scope','Body Material'])
    ws.append(['B01','Pipe','Pipe near check','CHW','DN25','Steel','40','PN16','Welded',40,None,'Level 1',None])
    ws.append(['B02','Pipe','Pipe large check','CHW','DN32','Steel','40','PN16','Welded',40,None,'Level 2',None])
    ws.append(['B03','Pipe','Pipe partial check','CHW','DN40','Steel','40','PN16','Welded',40,None,'Level 3',None])
    ws.append(['B04','Valve','Isolation valve','CHW','DN50',None,None,'PN16','Flanged',8,'ea','Level 4','Iron'])
    wb.save(src/'BOQ.xlsx')
    (src/'equipment_schedule.csv').write_text('Tag,Item Type,Description,Service,Quantity,Unit\nP-01,Pump,Water pump,CHW,2,ea\n',encoding='utf-8')
    (src/'unreadable_drawing.dwg').write_bytes(b'UNSUPPORTED GENERIC TEST SOURCE - NOT A REAL DWG')
    # A valid ASCII DXF export: coordinates are millimetres, not written totals.
    groups=[(0,'SECTION'),(2,'HEADER'),(9,'$ACADVER'),(1,'AC1015'),(9,'$INSUNITS'),(70,4),(0,'ENDSEC'),
            (0,'SECTION'),(2,'ENTITIES')]
    def line(handle,layer,x,y,length,z=0,end_z=None):
        groups.extend([(0,'LINE'),(5,handle),(100,'AcDbEntity'),(8,layer),(100,'AcDbLine'),
                       (10,x),(20,y),(30,z),(11,x+length),(21,y),(31,z if end_z is None else end_z)])
    def text(handle,content):
        groups.extend([(0,'TEXT'),(5,handle),(100,'AcDbEntity'),(8,'NOTES'),(100,'AcDbText'),
                       (10,0),(20,-5000),(30,0),(40,100),(1,content)])
    line('A0','CALIBRATION',0,-1000,1000)
    text('A1','CALIBRATION 1000 mm');text('A2','REVISION: R1')
    line('B1','CHW_DN25',0,0,37000)
    line('B2','CHW_DN32',0,10000,370000)
    line('B3','CHW_DN40',0,20000,36000)
    line('B4','CHW_DN40',36000,20000,0,0,4000)
    line('B5','CHW_DN25',37000,0,-37000) # Deliberate duplicate view, excluded unless selected.
    groups.extend([(0,'ARC'),(5,'B6'),(100,'AcDbEntity'),(8,'CHW_DN25'),(100,'AcDbCircle'),
                   (10,50000),(20,0),(30,0),(40,500),(100,'AcDbArc'),(50,0),(51,90)])
    groups.extend([(0,'ENDSEC'),(0,'EOF')])
    dxf=src/'mechanical_drawing_R1.dxf';dxf.write_text('\n'.join(str(v) for pair in groups for v in pair)+'\n',encoding='utf-8')
    pdf=src/'mechanical_specification.pdf';canvas=Canvas(str(pdf))
    for i,line_text in enumerate(['SECTION 23 05 00 General Mechanical Requirements',
        '1.1 COMMON REQUIREMENTS','A. All assemblies shall be inspected before installation.',
        'B. Valve body material shall be bronze.', 'C. Pump casing shall be corrosion resistant.']):
        canvas.drawString(40,770-i*25,line_text)
    canvas.save()
    checks=[]
    for i,(size,handle,scope) in enumerate([('DN25','B1','Level 1'),('DN32','B2','Level 2'),('DN40','B3','Level 3')],2):
        identity={'service':'CHW','size':size}
        checks.append({'id':'check-'+str(i),'item_type':'pipe','boq':{'file':'BOQ.xlsx','sheet':'BOQ','row':i},
            'scope':scope,'identity':identity,'identity_basis':'Exact BOQ size/service and reviewed CAD layer assignment; synthetic fixture',
            'coverage':{'complete':i!=4,'missing':[] if i!=4 else ['Drops/risers are not measured'],
                        'basis':'Explicit fixture scope per BOQ row and named layer; no other runs in the selected level'},
            'drawings':[{'file':dxf.name,'sha256':digest(dxf),'revision':'R1','revision_handle':'A2',
                'revision_basis':'Title TEXT handle A2 explicitly identifies R1; synthetic applicable revision',
                'scope':scope,'identity':identity,'identity_basis':'Reviewed layer CHW_'+size+' assigned to same BOQ line',
                'layer':'CHW_'+size,'handles':[handle],'units':'mm','scale':1,
                'calibration':{'handle':'A0','length':1000,'unit':'mm','label_handle':'A1','label':'CALIBRATION 1000 mm'}}]})
    options={'quantity_checks':checks,'quantity_tolerances':{'pipe':{'relative':.1,'absolute':0}},
             'specification_rules':[{'id':'general-mechanical','basis':'Common installation section applies as candidate to CHW equipment and materials',
                'items':{'systems':['CHW']},'requirements':{'sections':['^23 05 00$'],'technical_categories':['Installation']}}]}
    return src,options

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    if test_options.resume_fixture:
        src=BASE/'sources';options=json.loads((BASE/'options.json').read_text(encoding='utf-8'))
    else:src,options=build()
    # A corrupt Office source exercises source-local failure isolation.
    bad=src/'unreadable_schedule.xlsx'
    if not bad.exists():bad.write_bytes(b'SYNTHETIC CORRUPT XLSX - NO ZIP CONTENT')
    originals={str(p):digest(p) for p in src.iterdir()}
    first=command('run','--root',str(src),'--state',str(BASE/'state'),'--request',save_request('options',options))
    cfgpath=first['config'];cfg=prepare(config_path=cfgpath)
    (BASE/'first-result.json').write_text(json.dumps(first,indent=2),encoding='utf-8')
    view=snapshot(cfg)
    assert len(view['items'])==5,len(view['items'])
    checks=view['quantity_checks']
    assert [c['drawing_quantity'] for c in checks]==[37,370,36],checks
    assert [c['status'] for c in checks]==['close_within_review_tolerance','material_discrepancy','partial_check'],checks
    assert checks[0]['difference']==-3 and checks[1]['difference']==330 and checks[2]['difference'] is None
    assert all(c['boq']['original_value']==40 and c['unit']=='m' for c in checks)
    assert any(g['status']=='File present but unreadable or unsupported' for g in view['gaps'])
    assert any(g.get('error_type')=='BadZipFile' for g in view['gaps']),view['gaps']
    assert all(any('All assemblies' in c['text'] for c in item['clauses']) for item in view['items'])
    with sqlite3.connect(cfg['database']) as db:
        assert db.execute("SELECT count(*) FROM records WHERE kind='cad_entity'").fetchone()[0]>=9
        assert db.execute("SELECT count(*) FROM records WHERE kind='specification'").fetchone()[0]>0
    valve=next(i for i in view['items'] if i['category']=='valve')
    pump=next(i for i in view['items'] if i['category']=='pump')
    clause=next(c for c in valve['clauses'] if 'bronze' in c['text'])
    command('interpret','--request',save_request('interpret',{'item_id':valve['id'],'record_id':clause['record_id'],
        'fields':{'body_material':{'value':'bronze','unit':None}},'excerpt':clause['text'],
        'basis':'Synthetic test: literal material in exact valve clause; candidate interpretation'}),cfg=cfgpath)
    valve=snapshot(cfg,item_ids=[valve['id']])['items'][0]
    selected=next(f for f in valve['facts'] if f['field']=='body_material' and f['value']=='bronze')
    statement='SYNTHETIC TEST ONLY: use the specification body material and BOQ valve quantity; leave pressure class unresolved.'
    for field,link in [('body_material',selected['link_id']),('quantity',next(f['link_id'] for f in valve['facts'] if f['field']=='quantity')),('pressure_class',None)]:
        args=['--item',valve['id'],'--field',field,'--statement',statement,'--actor','Synthetic fixture user']
        if link:args+=['--source-link',link]
        command('decide',*args,cfg=cfgpath)
    # Main reads the pump clauses and records exact applicability for this fixture.
    for clause in pump['clauses']:
        command('link','--item',pump['id'],'--record',clause['record_id'],'--relation','direct',
            '--basis','Synthetic fixture: read and selected exact pump/general installation clause',cfg=cfgpath)
    before=count_state(cfg)
    resumed=command('run',cfg=cfgpath)
    after=count_state(cfg)
    assert before==after,(before,after)
    assert resumed['processed_sources']==0,resumed
    valve=snapshot(cfg,item_ids=[valve['id']])['items'][0]
    assert valve['selected']['body_material']['value']=='bronze'
    assert valve['selected']['quantity']['value']==8
    assert 'pressure_class' not in valve['selected'] and 'pressure_class' in valve['unresolved_fields']
    only_valve=snapshot(cfg,item_ids=[valve['id']])
    error=blocked('issue','--item',valve['id'],'--fingerprint',only_valve['fingerprint'],
                  '--statement','SYNTHETIC: attempt issue unresolved valve','--actor','Synthetic fixture user',cfg=cfgpath)
    both=snapshot(cfg,item_ids=[valve['id'],pump['id']])
    issued=command('issue','--item',valve['id'],'--item',pump['id'],'--exclude-item',valve['id'],
        '--fingerprint',both['fingerprint'],'--statement','SYNTHETIC: confirm the pump only; explicitly exclude the unresolved valve',
        '--actor','Synthetic fixture user',cfg=cfgpath)
    assert issued['excluded_item_ids']==[valve['id']] and {d['category'] for d in issued['deliveries']}=={'pump'}
    # Inspect actual generated OOXML, not only return values or source code.
    deliveries={d['category']:d for d in resumed['deliveries']}
    for category,delivery in deliveries.items():
        wb=load_workbook(delivery['xlsx'],data_only=False)
        ws=wb['Items'];headers=[c.value for c in ws[4]]
        rows=[dict(zip(headers,r)) for r in ws.iter_rows(min_row=5,values_only=True)]
        if category=='valve':
            assert rows[0]['Material']=='bronze',rows
            assert rows[0]['Written quantity']=='8' and rows[0]['Unit']=='ea'
            assert rows[0]['Pressure class'].startswith('PENDING'),rows
        if category=='pipe':
            assert all(r['Written quantity']=='40' and r['Unit']=='m' for r in rows)
            check_rows=list(wb['BOQ drawing checks'].iter_rows(min_row=2,values_only=True))
            assert {r[7] for r in check_rows}=={'close_within_review_tolerance','material_discrepancy','partial_check'}
        assert not any(c.data_type=='f' for s in wb for r in s for c in r)
        wb.close()
        doc=Document(delivery['docx']);text='\n'.join(p.text for p in doc.paragraphs)
        assert 'All assemblies shall be inspected before installation.' in text
        assert 'mechanical_specification.pdf' in text and 'physical original PDF page (one-based)' in text
        assert '23 05 00' in text and '1.1.A' in text
        if category=='valve':assert 'bronze' in text and 'pressure_class: PENDING' in text
        for key,extension in [('xlsx','xlsx'),('docx','docx')]:
            shutil.copy2(delivery[key],OUT/(category+'-review.'+extension))
    for key,extension in [('xlsx','xlsx'),('docx','docx')]:
        shutil.copy2(issued['deliveries'][0][key],OUT/('pump-confirmed-scope.'+extension))
    # Repeat unchanged work once: same extraction rows and same rendered files.
    steady=count_state(cfg);again=command('run',cfg=cfgpath)
    assert count_state(cfg)==steady
    assert all(d.get('reused') for d in again['deliveries']),again['deliveries']
    # Targeted remaining branches use the same stored source slice, no reingestion.
    conn=connect(cfg)
    branches={}
    try:
        states=_last_state(conn,cfg);tolerance=checks[0]['tolerance'];plan=deepcopy(options['quantity_checks'][0])
        plan['drawings'][0]['handles']=['B1','B5']
        duplicate=measure(conn,cfg,states,plan,tolerance)
        assert duplicate['drawing_quantity']==37 and duplicate['status']=='partial_check' and duplicate['duplicate_handles']==['B5']
        branches['duplicate_view']=duplicate['status']
        plan=deepcopy(options['quantity_checks'][0]);plan['drawings'][0]['units']='m'
        mismatch=measure(conn,cfg,states,plan,tolerance);assert mismatch['status']=='unable_to_verify'
        branches['wrong_units']=mismatch['status']
        plan=deepcopy(options['quantity_checks'][0]);plan['drawings'][0]['handles']=['B6']
        unsupported=measure(conn,cfg,states,plan,tolerance);assert unsupported['status']=='unable_to_verify'
        branches['unsupported_arc']=unsupported['status']
        plan=deepcopy(options['quantity_checks'][0]);plan['drawings'][0]['scope']='whole project'
        mismatch=measure(conn,cfg,states,plan,tolerance);assert mismatch['status']=='unable_to_verify'
        branches['wrong_scope']=mismatch['status']
        plan=deepcopy(options['quantity_checks'][2]);plan['drawings'][0]['handles']=['B3','B4'];plan['drawings'][0]['risers_verified']=True
        plan['coverage']['complete']=True;plan['coverage']['missing']=[]
        riser=measure(conn,cfg,states,plan,tolerance)
        assert riser['horizontal_quantity']==36 and riser['verified_riser_quantity']==4 and riser['drawing_quantity']==40
        branches['verified_riser_separate']=True
        new_facts=deepcopy(valve['facts'])
        next(f for f in new_facts if f['field']=='body_material')['citation']['sha256']='0'*64
        event=next(e for e in reversed(valve['decisions']) if e['field']=='body_material')
        assert event['field_basis']!=procurement_items.decision_basis(new_facts,'body_material',[])
        branches['changed_source_invalidates_field_choice']=True
        from master_project.procurement_rules import candidate_links
        limited=candidate_links(conn,cfg,states,{**options,'specification_limit':1})
        assert limited['omitted'] and all(v['selected']<=1 for v in limited['evaluated'].values())
        branches['selection_limit_discloses_omitted_record_ids']=limited['omitted']
        from master_project.procurement_documents import chosen
        conditional={'selected':{},'facts':[{'field':'size','value':'DN99','unit':None,'relation':'conditional'}]}
        assert chosen(conditional,'size')[0]=='UNKNOWN'
        branches['conditional_fact_never_implicitly_selected']=True
    finally:conn.close()
    assert originals=={str(p):digest(p) for p in src.iterdir()},'Fixture original sources changed'
    result={'status':'PASS','fixture':'Generic isolated synthetic data; never real project approval','config':cfgpath,
        'database':cfg['database'],'actual_entry_point':str(DEV/'scripts/master.py'),
        'measurements':checks,'record_counts_unchanged_on_resume':steady,'branches':branches,
        'unresolved_issue_block':error,'excluded_item_scope_issue':issued,'review_outputs':deliveries,
        'original_source_hashes':originals,'rendered_file_reuse':True,
        'source_choice_in_xlsx_and_docx':True,'unit_retention':True,'visual_review':'Pending render inspection'}
    (OUT/'execution-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','counts':steady,'measurements':[(c['drawing_quantity'],c['status']) for c in checks],
                      'outputs':str(OUT),'branches':branches},indent=2))

if __name__=='__main__':run()

