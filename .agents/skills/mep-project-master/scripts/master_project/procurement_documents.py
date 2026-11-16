"""Item presentation extension at the existing supplier rendering boundary."""
from collections import defaultdict
from pathlib import Path
import json
import re

from .common import encoded, key, sha, write

def locator(citation):
    bits=[citation['filename']]
    if citation.get('pdf_page'):bits+=['page '+str(citation['pdf_page']),citation['page_basis']]
    else:bits+=[citation.get('page_basis') or 'Page unavailable']
    for field in ('sheet','row','cell','paragraph','section','clause','heading','drawing_number','handle','revision'):
        if citation.get(field) is not None:bits.append(field+' '+str(citation[field]))
    return '; '.join(bits)

def chosen(item,field):
    if field in set(item.get('unresolved_fields',[])+item.get('stale_fields',[])):
        return 'PENDING \u2014 no agreed value','Explicitly unresolved or requires revalidation'
    if field=='quantity_unit':
        if 'quantity' in item['selected']:return item['selected']['quantity'].get('unit') or 'UNKNOWN','Unit of chosen quantity source'
        units={f.get('unit') for f in item['facts'] if f['field']=='quantity'}
        if len(units)==1:return next(iter(units)) or 'UNKNOWN','Original quantity unit'
        if units:return 'PENDING: '+' / '.join(str(u or 'UNKNOWN') for u in sorted(units,key=str)),'Unresolved quantity units'
    if field in item['selected']:return item['selected'][field]['value'],'Selected by recorded field decision'
    values=[f for f in item['facts'] if f['field']==field and f['relation'] in ('supported','direct')]
    distinct={encoded([f['value'],f.get('unit'),f.get('context')]) for f in values}
    if len(distinct)==1:return values[0]['value'],'Unreviewed source value'
    if values:return 'PENDING: '+' / '.join(str(f['value']) for f in values),'Unresolved difference'
    return 'UNKNOWN','Field not found in the sources reviewed'

def _literal(cell,value):
    if value is None:return
    cell.value=str(value)
    cell.data_type='s'  # A project string beginning with =,+,-,@ is never executed.

def workbook(view,category,group,path,label):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    wb=Workbook();ws=wb.active;ws.title='Items'
    headers=['Item ID','Description','Tag','Service','Size','Material','Pressure class','Pipe schedule',
             'Connection','Written quantity','Unit','Review status','Source refs']
    ws.append([view['project_name']+' \u2014 '+category+' technical schedule'])
    ws.append([label]);ws.append(['Unknown quantities remain UNKNOWN; written source quantities are not a calculated physical count.'])
    ws.append(headers)
    for item in group:
        val=lambda f:chosen(item,f)[0]
        material_field='material' if 'material' in item['selected'] or 'material' in item.get('unresolved_fields',[]) or 'material' in item.get('stale_fields',[]) else 'body_material' if any(f['field']=='body_material' for f in item['facts']) else 'material'
        material=val(material_field)
        q=val('quantity');bases=[f.get('count_basis') for f in item['written_quantities'] if f.get('count_basis')]
        ws.append([item['id'][:12],val('description'),item['tag'] or '',val('service'),val('size'),material,
                   val('pressure_class'),val('pipe_schedule'),val('connection'),q,val('quantity_unit'),
                   item['review_status'],'; '.join(sorted({f['citation']['filename'] for f in item['facts']}))])
    for row in (1,2,3):ws.merge_cells(start_row=row,start_column=1,end_row=row,end_column=len(headers))
    if any(i.get('quantity_checks') for i in group):
        check_sheet=wb.create_sheet('BOQ drawing checks')
        check_sheet.append(['Item ID','BOQ original','Unit','Measured portion','Horizontal','Verified risers','Difference full scope','Status',
            'Coverage','Missing scope','Tolerance relative','Tolerance absolute','Drawing references','Measurement basis'])
        for item in group:
            for check in item.get('quantity_checks',[]):
                boq=check.get('boq') or {}
                check_sheet.append([item['id'],boq.get('original_value'),boq.get('unit'),check['drawing_quantity'],
                    check['horizontal_quantity'],check['verified_riser_quantity'],check['difference'],check['status'],
                    'Complete declared scope' if check['coverage'].get('complete') and not check['limitations'] else 'Partial / unverified',
                    '; '.join(check['coverage'].get('missing',[])+check['limitations']),check['tolerance']['relative'],check['tolerance']['absolute'],
                    ' | '.join(d['file']+' rev '+d['revision']+' handles '+','.join(d['handles']) for d in check['drawing_references']),
                    check['measurement_basis']+'; screening tolerance is not engineering acceptance'])
    prop=wb.create_sheet('Properties')
    prop.append(['Item ID','Field','Original value','Original unit','Operating basis','Display selection','Association','Source filename','Locator','Source ref'])
    for item in group:
        for f in item['facts']:
            selected=item['selected'].get(f['field'],{}).get('link_id')==f['link_id']
            prop.append([item['id'],f['field'],f['value'],f.get('unit'),f.get('context'),
                        'Selected by recorded field decision' if selected else 'Competing / pending' if f['field'] in item['selected'] else 'Unreviewed',
                        f['relation'],f['citation']['filename'],locator(f['citation']),f['record_id']])
    pending=wb.create_sheet('Outstanding')
    pending.append(['Item ID','Field','Issue kind','Status','Decision needed','Values and sources'])
    for item in group:
        for f in item['findings']:
            pending.append([item['id'],f['field'],f['kind'],f['status'],f['decision_needed'],
                ' | '.join(str(v['value'])+' '+str(v.get('unit') or '')+' @ '+locator(v['citation']) for v in f['values'])])
    for gap in view['gaps']:pending.append(['Scope',gap.get('type') or gap.get('file'),gap['status'],'Pending',gap.get('affects'),str(gap.get('reason',''))])
    for sheet in wb:
        header_row=4 if sheet.title=='Items' else 1
        sheet.freeze_panes='C'+str(header_row+1)
        sheet.auto_filter.ref=sheet.cell(header_row,1).coordinate+':'+sheet.cell(sheet.max_row,sheet.max_column).coordinate
        sheet.sheet_view.showGridLines=False
        for row in sheet:
            for cell in row:
                _literal(cell,cell.value)
                cell.alignment=Alignment(vertical='top',wrap_text=True)
                cell.font=Font(name='Calibri',size=11)
        for cell in sheet[header_row]:
            cell.fill=PatternFill('solid',fgColor='163F4A');cell.font=Font(name='Calibri',size=11,bold=True,color='FFFFFF')
        from openpyxl.utils import get_column_letter
        for column in range(1,sheet.max_column+1):
            sheet.column_dimensions[get_column_letter(column)].width=24 if column<=7 else 36
        sheet.column_dimensions['A'].width=22
        sheet.print_options.horizontalCentered=True
        sheet.sheet_properties.pageSetUpPr.fitToPage=True
        sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
        sheet.print_title_rows=str(header_row)+':'+str(header_row)
    for index,width in enumerate([16,30,12,12,12,18,16,12,14,14,9,18,27],1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(index)].width=width
    for row,height in ((1,28),(2,24),(3,32),(4,32)):
        ws.row_dimensions[row].height=height
    for row in range(5,ws.max_row+1):ws.row_dimensions[row].height=60
    if 'BOQ drawing checks' in wb:
        check_sheet=wb['BOQ drawing checks']
        for index,width in enumerate([16,10,8,12,12,12,14,26,24,42,12,12,38,40],1):
            check_sheet.column_dimensions[get_column_letter(index)].width=width
        check_sheet.row_dimensions[1].height=38
        for row in range(2,check_sheet.max_row+1):check_sheet.row_dimensions[row].height=105
    wb.save(path)

def specifications(view,category,group,path,label):
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document=Document()
    sec=document.sections[0];sec.top_margin=sec.bottom_margin=Inches(.75)
    sec.left_margin=sec.right_margin=Inches(.8)
    for name in ('Normal','Title','Heading 1','Heading 2','Heading 3'):
        style=document.styles[name];style.font.name='Calibri';style.font.color.rgb=RGBColor(0,0,0)
        if name=='Normal':style.font.size=Pt(11);style.paragraph_format.space_after=Pt(7)
    for style in document.styles:
        ppr=style.element.find(qn('w:pPr'))
        if ppr is not None:
            for border in list(ppr.findall(qn('w:pBdr'))):ppr.remove(border)
    title=document.add_paragraph(view['project_name']+' '+category+' technical specifications','Title')
    title.paragraph_format.left_indent=Inches(0)
    title.paragraph_format.first_line_indent=Inches(0)
    document.add_paragraph(label)
    document.add_paragraph('Selected scope: '+', '.join(i['tag'] or i['id'][:12] for i in group))
    document.add_paragraph('Clauses retain their original wording. Pending fields and conditional associations remain visible; issue confirmation is scoped and does not certify complete design review.')
    clauses={}
    for item in group:
        for clause in item['clauses']:
            entry=clauses.setdefault(clause['record_id'],{**clause,'items':[]})
            entry['items'].append(item['tag'] or item['id'][:12])
            if clause['relation']=='direct':entry['relation']='direct'
    for section,relations in [('Directly relevant selected clauses',{'direct'}),('Conditional and uncertain clauses for review',{'candidate','conditional','supported'})]:
        if not any(c['relation'] in relations for c in clauses.values()):continue
        document.add_heading(section,1);found=False
        for clause in clauses.values():
            if clause['relation'] not in relations:continue
            found=True;cit=clause['citation']
            document.add_heading('Section '+str(cit.get('section') or 'unavailable')+' Clause '+str(cit.get('clause') or 'unavailable'),2)
            document.add_paragraph('Heading: '+str(cit.get('heading') or 'Heading unavailable')+
                                   '; relation: '+clause['relation']+'; items: '+', '.join(clause['items']))
            document.add_paragraph(clause['text'])
            document.add_paragraph(locator({**cit,'heading':None})+'; source ref '+clause['record_id'][:12])
        if not found:document.add_paragraph('No clauses established in this section from the sources reviewed.')
    if any(i['selected'] or i.get('unresolved_fields') or i.get('stale_fields') for i in group):
        document.add_heading('Field choices for this scope',1)
    for item in group:
        for field in sorted(set(item['selected'])|set(item.get('unresolved_fields',[]))|set(item.get('stale_fields',[]))):
            value,status=chosen(item,field)
            source=item['selected'].get(field)
            document.add_paragraph((item['tag'] or item['id'][:12])+' \u2014 '+field+': '+str(value)+
                (' '+str(source.get('unit') or '') if source else '')+'; '+status)
            if source:document.add_paragraph(locator(source['citation']))
    if any(f['status']!='Resolved by recorded field choice' for i in group for f in i['findings']):
        document.add_heading('Information still pending',1)
    for item in group:
        gaps=[f for f in item['findings'] if f['status']!='Resolved by recorded field choice']
        if gaps:document.add_paragraph((item['tag'] or item['id'][:12])+': '+', '.join(sorted({f['field'] for f in gaps})))
    if view['gaps']:document.add_heading('Project source limitations',1)
    for gap in view['gaps']:
        source=gap.get('type') or Path(gap.get('file') or '').name
        status='Extraction warning' if isinstance(gap.get('reason'),dict) and gap['reason'].get('code')=='specification_layout_review' else gap['status']
        document.add_paragraph(status+': '+str(source)+'; '+str(gap.get('affects','')))
    footer=sec.footer.paragraphs[0];footer.add_run(label+' | Page ')
    fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');footer._p.append(fld)
    document.save(path)

def render(cfg,view,*,mode='review'):
    if mode not in ('review','issue'):raise ValueError('Unknown procurement delivery mode')
    if mode=='issue':
        from .procurement_items import issue_blockers
        if issue_blockers(view):raise ValueError('Unresolved selected scope cannot be rendered FOR ISSUE')
    groups=defaultdict(list)
    for item in view['items']:groups[item['category']].append(item)
    deliveries=[]
    root=Path(cfg['output_directory'])/'mechanical-procurement'/mode
    if not groups:
        root.mkdir(parents=True,exist_ok=True)
        if not (root/('internal/'+view['fingerprint']+'.json')).exists():
            write(root/('internal/'+view['fingerprint']+'.json'),view)
        return []
    for category,group in groups.items():
        safe=re.sub(r'[^A-Za-z0-9_-]','_',category) or 'mechanical'
        # Known independent categories reuse their own unchanged result even if a
        # different source/category changed. Shared coverage gaps remain dependencies.
        group_fingerprint=key([view['project_id'],view['project_name'],category,group,view['gaps'],mode,sha(Path(__file__))])
        folder=root/safe/group_fingerprint[:20];receipt=folder/'internal/render-receipt.json'
        if receipt.is_file():
            saved=json.loads(receipt.read_text(encoding='utf-8'))
            if all(Path(f['path']).is_file() and sha(f['path'])==f['sha256'] for f in saved['files']):
                deliveries.append({**saved,'reused':True,'current_view_fingerprint':view['fingerprint']});continue
            raise ValueError('Existing procurement output damaged; preserve it and select a new attempt')
        folder.mkdir(parents=True,exist_ok=False)
        (folder/'.mep-registry-output.json').write_text(encoded({'generated_output':True}),encoding='utf-8')
        label='DRAFT \u2014 FOR TECHNICAL REVIEW' if mode=='review' else 'FOR ISSUE \u2014 USER CONFIRMED SELECTED SCOPE'
        xlsx=folder/'Technical Schedule.xlsx';docx=folder/'Technical Specifications.docx'
        workbook(view,category,group,xlsx,label);specifications(view,category,group,docx,label)
        write(folder/'internal/evidence-and-decisions.json',{'items':group,'gaps':view['gaps'],'view_fingerprint':view['fingerprint']})
        files=[{'path':str(p),'sha256':sha(p)} for p in (xlsx,docx)]
        saved={'category':category,'mode':mode,'xlsx':str(xlsx),'docx':str(docx),'files':files,
               'view_fingerprint':view['fingerprint'],'group_fingerprint':group_fingerprint,
               'visual_review':'Not performed by the deterministic writer; Main must render/inspect for the actual project'}
        write(receipt,saved);deliveries.append(saved)
    return deliveries

