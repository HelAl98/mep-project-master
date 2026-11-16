"""Windows-compatible local document-control CLI; no cloud services."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from .common import dump, key, now
from .db import Registry
from .exports import export_snapshot
from .scan import scan_project, refresh_relationships


def _existing(path, skills_root=None):
    if not Path(path).is_file():
        raise ValueError('Database does not exist; scan the project first')
    return Registry(path,skills_root)


def _output(snapshot,db,requested=None):
    target=Path(requested) if requested else Path(db).resolve().parent/'registry-output'/('p-'+key(snapshot['project']['id'])[:12])/uuid.uuid4().hex
    return export_snapshot(snapshot,target)


def _demo(output,skills_root=None):
    from reportlab.pdfgen.canvas import Canvas
    from openpyxl import Workbook
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    (output/'.mep-registry-output.json').write_text(dump({'generated_output':True,'synthetic':True,'status':'incomplete'}),encoding='utf-8')
    root=output/'synthetic-source'; root.mkdir()
    def pdf(name,pages):
        canvas=Canvas(str(root/name),pagesize=(612,792),invariant=1)
        for sheet_index,(number,revision,title) in enumerate(pages,1):
            for index,line in enumerate(['SYNTHETIC DEMONSTRATION ONLY - NOT PROJECT DATA',
                 'DRAWING NUMBER: '+number,'TITLE: '+title,'REVISION: '+revision,'DISCIPLINE: HVAC',
                 'DOCUMENT TYPE: Drawing','SHEET NUMBER: '+str(sheet_index),'SCALE: 1:100']):
                canvas.drawString(40,750-index*18,line)
            canvas.showPage()
        canvas.save()
    pdf('SYN-M-101_Rev-A.pdf',[('SYN-M-101','A','Synthetic ventilation plan')])
    pdf('SYN-M-101_Rev-B.pdf',[('SYN-M-101','B','Synthetic revised ventilation plan')])
    pdf('SYN-combined.pdf',[('SYN-E-201','A','Synthetic power plan'),('SYN-E-202','C','Synthetic lighting plan')])
    (root/'SYN-M-101_Rev-A.dwg').write_bytes(b'SYNTHETIC UNPARSED DWG FIXTURE; NOT A FUNCTIONING CAD FILE')
    (root/'SYN-scope.md').write_text('TITLE: Synthetic scope\nDOCUMENT TYPE: Scope of Work\nDISCIPLINE: BMS\n',encoding='utf-8')
    workbook=Workbook(); workbook.active.title='Metadata'
    workbook.active.append(['TITLE','Synthetic equipment schedule'])
    workbook.active.append(['DOCUMENT TYPE','Equipment Schedule'])
    workbook.active.append(['DISCIPLINE','HVAC'])
    workbook.save(root/'SYN-schedule.xlsx')
    db=output/'engineering.sqlite'
    first=scan_project(root,db,'synthetic-demo',{'revision_order':['A','B','C']},skills_root)
    registry=Registry(db,skills_root)
    try:
        revision=next(r for r in first['revisions'] if r['document_number']=='SYN-M-101' and r['revision']=='B')
        registry.review('synthetic-demo','revision',revision['revision_id'],'approve_applicability',
                        'Synthetic Demo Engineer','Synthetic workflow exercise only; not an approval of real project data')
    finally: registry.close()
    second=scan_project(root,db,'synthetic-demo',{'revision_order':['A','B','C']},skills_root)
    outputs=export_snapshot(second,output/'reports')
    result={'synthetic':True,'source_root':str(root),'database_path':str(db),'project_id':'synthetic-demo',
            'first_scan':first['summary'],'rescan':second['summary'],'outputs':outputs,
            'review_demo':'One explicit synthetic revision decision; relationships remain proposals'}
    (output/'demo-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'.mep-registry-output.json').write_text(dump({'generated_output':True,'synthetic':True,'status':'complete'}),encoding='utf-8')
    return result


def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root',help='Optional existing project .agents/skills directory')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('scan','rescan'):
        command=sub.add_parser(name,help='Register source files without changing them')
        command.add_argument('--root',required=True)
        command.add_argument('--db')
        command.add_argument('--project-id')
        command.add_argument('--config')
        command.add_argument('--output',help='New report directory; default beside database')
        command.add_argument('--no-export',action='store_true')
        command.add_argument('--fail-on-error',action='store_true')
    for name in ('export','issues','search','show','review'):
        command=sub.add_parser(name)
        command.add_argument('--db',required=True)
        command.add_argument('--project-id',required=True)
        if name=='export': command.add_argument('--output')
        if name in ('show','export'): command.add_argument('--history',action='store_true')
        if name=='issues': command.add_argument('--all',action='store_true',help='Include resolved/invalidated issues')
        if name=='search':
            command.add_argument('--query',required=True); command.add_argument('--limit',type=int,default=100)
            command.add_argument('--history',action='store_true',help='Include historical source observations')
        if name=='review':
            command.add_argument('--target-type',choices=['file','revision','relationship','observation','issue'],required=True)
            for option in ('target-id','decision','actor','reason'): command.add_argument('--'+option,required=True)
            command.add_argument('--value-json')
    demo=sub.add_parser('demo',help='Create an explicitly synthetic local workflow demonstration')
    demo.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    code=0
    try:
        if args.command=='demo':
            result=_demo(args.output,args.skills_root)
        elif args.command in ('scan','rescan'):
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig')) if args.config else None
            snapshot=scan_project(args.root,args.db,args.project_id,config,args.skills_root)
            outputs={} if args.no_export else _output(snapshot,snapshot['database_path'],args.output)
            result={k:snapshot[k] for k in ('project','database_path','summary','scan')}
            result['outputs']=outputs
            if args.fail_on_error and snapshot['summary']['errors']: code=1
        else:
            registry=_existing(args.db,args.skills_root)
            try:
                if args.command=='review':
                    value=json.loads(args.value_json) if args.value_json is not None else None
                    result=registry.review(args.project_id,args.target_type,args.target_id,args.decision,args.actor,args.reason,value)
                elif args.command=='search':
                    result={'project_id':args.project_id,'results':registry.search(args.project_id,args.query,args.limit,args.history)}
                else:
                    snapshot=registry.snapshot(args.project_id,history=getattr(args,'history',False))
                    if args.command=='show': result=snapshot
                    elif args.command=='issues':
                        result={'project_id':args.project_id,'issues':[i for i in snapshot['issues'] if args.all or i['status']=='open']}
                    else: result={'project_id':args.project_id,'outputs':_output(snapshot,args.db,args.output)}
            finally: registry.close()
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return code
    except KeyboardInterrupt:
        print('Interrupted; completed file transactions and scan history are retained. Rescan to continue.',file=sys.stderr)
        return 130
    except (ValueError,OSError,sqlite3.Error,KeyError) as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        return 2
