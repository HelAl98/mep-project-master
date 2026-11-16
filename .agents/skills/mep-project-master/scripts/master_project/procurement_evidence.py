"""Source adapters for the Master's item path; raw facts belong to existing core ETL."""
import csv
import importlib.util
import json
from pathlib import Path
import re
import sys

from .common import key, sha

ALIASES = {
    'tag':['tag','equipment tag','equipment no','equipment id','\u0648\u0633\u0645','\u062a\u0627\u062c'],
    'item_type':['item type','type','category','\u0646\u0648\u0639 \u0627\u0644\u0628\u0646\u062f','\u0646\u0648\u0639'],
    'description':['description','item description','description of work','\u0627\u0644\u0648\u0635\u0641','\u0648\u0635\u0641 \u0627\u0644\u0628\u0646\u062f','\u0628\u064a\u0627\u0646'],
    'item_number':['item no','item number','item code','\u0631\u0642\u0645 \u0627\u0644\u0628\u0646\u062f'],
    'identity_kind':['identity kind','identity','reference type','\u0646\u0648\u0639 \u0627\u0644\u0647\u0648\u064a\u0629'],
    'service':['service','system','\u0627\u0644\u062e\u062f\u0645\u0629','\u0627\u0644\u0646\u0638\u0627\u0645'],
    'size':['size','diameter','nominal size','\u0627\u0644\u0645\u0642\u0627\u0633','\u0627\u0644\u0642\u0637\u0631'],
    'material':['material','\u0627\u0644\u062e\u0627\u0645\u0629','\u0627\u0644\u0645\u0627\u062f\u0629'],
    'body_material':['body material','\u0645\u0627\u062f\u0629 \u0627\u0644\u062c\u0633\u0645'],
    'pressure_class':['pressure class','pressure rating','rating','pn','\u062a\u0635\u0646\u064a\u0641 \u0627\u0644\u0636\u063a\u0637'],
    'pipe_schedule':['pipe schedule','schedule','\u0633\u0645\u0627\u0643\u0629 \u0627\u0644\u0645\u0648\u0627\u0633\u064a\u0631'],
    'connection':['connection','end type','connection type','\u0646\u0648\u0639 \u0627\u0644\u062a\u0648\u0635\u064a\u0644'],
    'quantity':['quantity','qty','\u0627\u0644\u0643\u0645\u064a\u0629','\u0643\u0645\u064a\u0629'],
    'quantity_unit':['quantity unit','unit','uom','\u0627\u0644\u0648\u062d\u062f\u0629'],
    'scope':['scope','quantity scope','\u0646\u0637\u0627\u0642 \u0627\u0644\u0643\u0645\u064a\u0629'],
    'thickness':['thickness','\u0633\u0645\u0643'],
    'location':['location','room','\u0627\u0644\u0645\u0648\u0642\u0639'],
    'motor_power':['motor power','motor kw','\u0642\u062f\u0631\u0629 \u0627\u0644\u0645\u0648\u062a\u0648\u0631'],
    'voltage':['voltage','\u0627\u0644\u062c\u0647\u062f'], 'flow':['flow','flow rate','\u0627\u0644\u062a\u062f\u0641\u0642'],
    'head':['head','\u0627\u0644\u0631\u0641\u0639'], 'control':['control','control requirement','\u0645\u062a\u0637\u0644\u0628 \u0627\u0644\u062a\u062d\u0643\u0645'],
    'duty':['duty','operating basis','\u062d\u0627\u0644\u0629 \u0627\u0644\u062a\u0634\u063a\u064a\u0644'],
    'subtype':['subtype','valve type','fitting type'], 'facing':['facing','\u0648\u062c\u0647 \u0627\u0644\u0641\u0644\u0627\u0646\u0634\u0629'],
}
TYPES = {
 'valve':r'valves?|butterfly|gate valve|ball valve|\u0635\u0645\u0627\u0645|\u0645\u062d\u0628\u0633',
 'pipe':r'pipes?|tubes?|\u0645\u0648\u0627\u0633\u064a\u0631|\u0645\u0627\u0633\u0648\u0631\u0629|\u0623\u0646\u0628\u0648\u0628|\u0627\u0646\u0628\u0648\u0628',
 'fitting':r'fittings?|elbows?|tees?|reducers?|\u0643\u0648\u0639|\u062a\u064a\u0647\u0627\u062a|\u0645\u062e\u0641\u0636',
 'flange':r'flanges?|\u0641\u0644\u0627\u0646\u0634',
 'gasket':r'gaskets?|\u062c\u0648\u0627\u0646',
 'bolt':r'bolts?|nuts?|washers?|\u0645\u0633\u0627\u0645\u064a\u0631|\u0635\u0627\u0645\u0648\u0644\u0629|\u0648\u0631\u062f',
 'coupling':r'couplings?|\u0643\u0648\u0628\u0644\u0646\u062c',
 'support':r'supports?|hangers?|\u062d\u0648\u0627\u0645\u0644|\u062a\u0639\u0644\u064a\u0642\u0627\u062a',
 'insulation':r'insulation|\u0639\u0632\u0644',
 'pump':r'pumps?|\u0637\u0644\u0645\u0628\u0629|\u0637\u0644\u0645\u0628\u0627\u062a|\u0645\u0636\u062e\u0629',
 'ahu':r'\bahu\b|air handling|\u0645\u0646\u0627\u0648\u0644\u0629 \u0647\u0648\u0627\u0621',
 'chiller':r'chillers?|\u0634\u064a\u0644\u0631',
 'fan':r'\bfans?\b|\u0645\u0631\u0648\u062d\u0629|\u0645\u0631\u0627\u0648\u062d',
 'accessory':r'accessor|\u0645\u0644\u062d\u0642',
}
EQUIPMENT={'pump','ahu','chiller','fan'}
DEFINING={
 'pipe':('service','size','material','pipe_schedule','connection'),
 'valve':('service','size','material','pressure_class','connection'),
 'fitting':('service','size','material','pressure_class','connection','subtype'),
 'flange':('size','material','pressure_class','connection','facing'),
 'gasket':('size','material','pressure_class','subtype'),
 'bolt':('size','material','subtype'),
 'coupling':('service','size','material','pressure_class','connection'),
 'support':('size','material','subtype'), 'insulation':('service','size','material','thickness'),
}

def norm(value):
    return re.sub(r'[^\w]+','',str(value or '').casefold(),flags=re.UNICODE)

def helper(skills,name,script):
    path=Path(skills)/name/'scripts'/script
    module_name='_master_procurement_'+key(str(path))[:12]
    if module_name in sys.modules:return sys.modules[module_name]
    spec=importlib.util.spec_from_file_location(module_name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module;spec.loader.exec_module(module)
    return module

def classify(text):
    for category,pattern in TYPES.items():
        if re.search(pattern,str(text or ''),re.I):return category
    return 'other'

def role_for(file):
    meta=file.get('metadata',{})
    label=' '.join(str(meta.get(k) or '') for k in ('document_type','discipline'))+' '+file['filename']
    for role,pattern in [('boq',r'boq|b\.?o\.?q|bill of quantit|\u0645\u0642\u0627\u064a\u0633\u0629|\u0643\u0645\u064a\u0627\u062a'),('specification',r'spec|\u0645\u0648\u0627\u0635\u0641\u0627\u062a'),
                         ('bms',r'bms|control|\u062a\u062d\u0643\u0645'),('electrical',r'electric|mcc|load list|\u0643\u0647\u0631\u0628'),
                         ('schedule',r'schedule|\u062c\u062f\u0648\u0644'),('drawing',r'drawing|plan|\u0631\u0633\u0645|\u0645\u062e\u0637\u0637')]:
        if re.search(pattern,label,re.I):return role
    if Path(file['filename']).suffix.lower() in ('.dwg','.dxf'):return 'drawing'
    if re.search(r'datasheet|data sheet|\u0643\u062a\u0627\u0644\u0648\u062c',label,re.I):return 'datasheet'
    return 'unclassified'

def header_fields(headers,explicit=None):
    columns={};units={};ambiguity=[]
    explicit=explicit or {}
    for index,header in enumerate(headers):
        raw=str(header or '').strip()
        if not raw:continue
        base=re.sub(r'\s*[([]([^])]+)[)\]]\s*$','',raw).strip()
        unit=re.search(r'[([]([^])]+)[)\]]\s*$',raw)
        mapped=explicit.get('columns',{}).get(raw)
        matches=[name for name,aliases in ALIASES.items() if norm(base) in {norm(a) for a in aliases}]
        name=mapped or (matches[0] if len(matches)==1 else norm(base))
        if name in columns:ambiguity.append('Ambiguous duplicate mapped header: '+raw)
        columns[name]=index
        units[name]=explicit.get('units',{}).get(name) or (unit.group(1).strip() if unit else None)
    return columns,units,ambiguity

def tabular_records(rows,sheet,explicit=None,page=None):
    explicit=explicit or {};records=[];issues=[]
    if len(rows)>100000:raise ValueError('Table exceeds explicit 100000 row limit')
    start=explicit.get('header_row')
    if start is None:
        for index,row in enumerate(rows[:30]):
            cols,_,_=header_fields(row,explicit)
            if len(set(cols)&set(ALIASES))>=2 and set(cols)&{'description','tag','item_type'}:
                start=index+1;break
    def preview(message):
        raw=[{'kind':'table_row','raw_text':json.dumps(list(row),ensure_ascii=False,default=str),
              'source':{'method':'master-procurement-mapping-preview/1','sheet':sheet,'row':index,'pdf_page':page},
              'data':{'raw_cells':[v if isinstance(v,(str,int,float,bool,type(None))) else str(v) for v in row],
                      'coverage':'First 30 rows for mapping only; item extraction pending'},
              'review':{'status':'unreviewed','issues':['MAPPING_NEEDED']}}
             for index,row in enumerate(rows[:30],1)]
        return raw,[{'code':'MAPPING_NEEDED','sheet':sheet,'message':message+' First 30 rows only are stored for Main mapping; no completed item extraction claimed.'}]
    if start is None:return preview('No unambiguous item/header layout recognized.')
    headers=rows[start-1];cols,units,amb=header_fields(headers,explicit)
    if amb:return preview('; '.join(amb))
    for number,row in enumerate(rows[start:],start+1):
        if not any(v not in (None,'') for v in row):continue
        cells={str(h):v if isinstance(v,(str,int,float,bool,type(None))) else str(v)
               for h,v in zip(headers,row) if h not in (None,'')}
        fields={};warnings=[]
        for field,index in cols.items():
            value=row[index] if index<len(row) else None
            if value in (None,''):continue
            if isinstance(value,str) and value.startswith('='):
                warnings.append('FORMULA_NOT_EVALUATED:'+field);continue
            if not isinstance(value,(str,int,float,bool)):value=str(value)
            fields[field]={'value':value,'unit':units.get(field),'context':explicit.get('context')}
        fields.update({k:{'value':v,'unit':None,'context':'explicit_mapping_constant'}
                       for k,v in explicit.get('constants',{}).items() if k not in fields})
        if 'quantity' in fields:
            fields['quantity']['unit']=fields.get('quantity_unit',{}).get('value') or fields['quantity'].get('unit')
            fields['quantity']['quantity_kind']='written'
            fields['quantity']['count_basis']=explicit.get('quantity_basis') or fields.get('scope',{}).get('value')
        if not any(k in fields for k in ('tag','description','item_type')):continue
        source={'method':'master-procurement-explicit-table/2' if explicit else 'master-procurement-recognized-header/2',
                'sheet':sheet,'row':number,'pdf_page':page,
                'field_columns':{f:str(headers[i]) for f,i in cols.items()},
                'mapping_basis':'explicit Main mapping' if explicit else 'recognized literal headers; classification unreviewed'}
        records.append({'kind':'procurement_row','raw_text':json.dumps(cells,ensure_ascii=False),
                        'source':source,'data':{'fields':fields,'raw_cells':cells},
                        'review':{'status':'unreviewed','issues':warnings}})
    return records,issues

def package_for(file,path,skills,mappings=None,existing=None):
    """Reuse native extractors, then core ETL; never claim unsupported conversion."""
    core=helper(skills,'etl-pipeline','mep_store.py')
    metadata={k:file.get('metadata',{}).get(k) for k in ('discipline','revision','drawing_number')}
    metadata['file_id']=file['file_id']
    doc=core.document_info(path,metadata)
    ext=path.suffix.lower();role=role_for(file);records=[];issues=[]
    mappings=mappings or {}
    if existing and ext in ('.docx','.txt','.md'):
        return core.validate_package(existing),None
    if existing and ext in ('.xlsx','.csv') and any(r.get('data',{}).get('fields') for r in existing['records']):
        return core.validate_package(existing),None
    if ext in ('.xlsx','.csv'):
        if ext=='.csv':
            with path.open(encoding='utf-8-sig',newline='') as stream:tabs=[('CSV',list(csv.reader(stream)))]
        else:
            from openpyxl import load_workbook
            import zipfile
            with zipfile.ZipFile(path) as z:
                if sum(i.file_size for i in z.infolist())>500000000:raise ValueError('Office ZIP size limit')
            wb=load_workbook(path,read_only=True,data_only=False,keep_links=False)
            try:tabs=[(s.title,list(s.iter_rows(values_only=True))) for s in wb]
            finally:wb.close()
        for sheet,rows in tabs:
            found,warnings=tabular_records(rows,sheet,mappings.get(sheet))
            records+=found;issues+=warnings
    elif ext=='.dxf':
        from .procurement_geometry import dxf_records
        records=dxf_records(path)
    elif ext=='.pdf':
        pdf=existing or helper(skills,'pdf-to-structured','extract_pdf.py').extract_pdf(path,metadata)
        records+=pdf['records'];issues+=pdf['issues'];doc=pdf['document']
        if role=='drawing' or any('tag' in str(r.get('raw_text','')).casefold() for r in pdf['records'][:40]):
            drawing=helper(skills,'drawing-analyzer','analyze_drawing.py').analyze_drawing(pdf)
            records+=drawing['records'];issues+=drawing['issues']
        for record in pdf['records']:
            if record['kind']=='table':
                rows=record.get('data',{}).get('rows') or record.get('data',{}).get('cells')
                if isinstance(rows,list):
                    found,warnings=tabular_records(rows,'PDF table '+str(record['source'].get('table_id')),page=record['source']['pdf_page'])
                    records+=found;issues+=warnings
        if role in ('specification','unclassified') and not any(r['kind']=='specification' for r in records):
            spec=helper(skills,'specification-extractor','extract_specifications.py').extract_specifications(pdf)
            records+=spec['records'];issues+=spec['issues']
        for r in records:
            if r['kind'] in ('equipment_candidate','equipment') and r.get('data',{}).get('tag'):
                r['data']['fields']={'tag':{'value':r['data']['tag'],'unit':None}}
    elif ext in ('.docx','.txt','.md'):
        if ext=='.docx':
            from docx import Document
            d=Document(path);paragraphs=[p.text for p in d.paragraphs]
            for index,t in enumerate(d.tables):
                found,warnings=tabular_records([[c.text for c in row.cells] for row in t.rows],'Word table '+str(index+1))
                records+=found;issues+=warnings
        else:paragraphs=path.read_text(encoding='utf-8-sig').splitlines()
        section=heading=clause=None
        for number,text in enumerate(paragraphs,1):
            if not text.strip():continue
            sec=re.search(r'\bSECTION\s+(\d{2}\s+\d{2}\s+\d{2}|\d{5,6})(?:\s+(.*))?',text,re.I)
            if sec:section,heading=sec.group(1),sec.group(2);clause=None
            hit=re.match(r'\s*((?:\d+\.)*\d+\.?|[A-Z]\.)\s+',text)
            if hit:clause=hit.group(1).rstrip('.')
            records.append({'kind':'specification' if role=='specification' or section else 'paragraph','raw_text':text,
                'source':{'method':'master-procurement-native-paragraph/1','paragraph':number,'pdf_page':None,
                          'page_basis':'Page unavailable; native '+ext[1:]+' paragraph','spec_section':section,'clause':clause},
                'data':{'section_title':heading},'review':{'status':'unreviewed','issues':[]}})
    else:
        return None,{'status':'File present but unreadable or unsupported','file':str(path),
                     'affects':'Content, quantities and downstream associations from this file',
                     'reason':'No verified native route for '+ext+'; provide a traceable supported export/conversion. Independent sources continue.'}
    # Preserve available PDF section headings on each fragment without changing wording.
    heading_by_section={}
    for record in records:
        if record['kind']=='specification' and record['data'].get('type')=='section':
            section=record['source'].get('spec_section')
            heading_by_section[section]=record['raw_text']
    for record in records:
        if record['kind']=='specification' and not record['data'].get('section_title'):
            record['data']['section_title']=heading_by_section.get(record['source'].get('spec_section'))
    if sha(path)!=doc['sha256']:raise ValueError('Source changed during extraction')
    package=core.validate_package({'schema_version':core.SCHEMA,'document':doc,'records':records,'issues':issues})
    return package,None
