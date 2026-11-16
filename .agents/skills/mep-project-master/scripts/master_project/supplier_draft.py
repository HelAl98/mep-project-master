"""P1-03: compact draft compilation through EvidenceReader v1 only. No SQL."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from xml.sax.saxutils import escape

from .common import HOME
from .evidence_reader import CONTRACT, EvidenceReader

DRAFT = 'DRAFT \u2014 FOR TECHNICAL REVIEW'
INCOMPLETE = 'INCOMPLETE SOURCE DATA \u2014 ENGINEERING CONFIRMATION REQUIRED'
CATEGORIES = ('Directly Supported by Available Evidence', 'General Requirement',
              'Candidate \u2014 Requires Review', 'Conditional \u2014 Requires Confirmation')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def plain(value):
    if value is None:
        return 'UNKNOWN'
    if isinstance(value, (list, dict)):
        return canonical(value) if isinstance(value, dict) else '; '.join(plain(x) for x in value)
    return str(value)


def original_value(parameter):
    value = parameter['original_printed_value']
    return parameter['original_parameter'].get('raw_values', []) if value is None else value


def known(value):
    if isinstance(value, list):
        return bool(value) and all(known(x) for x in value)
    return value is not None and str(value).strip().upper() not in ('', '_', '-', '--', 'N/A', 'UNKNOWN', 'NULL')


class ReaderContractError(ValueError):
    pass


def require(record, fields, where):
    if not isinstance(record, dict) or any(k not in record for k in fields):
        raise ReaderContractError('EvidenceReader contract gap at ' + where + ': required ' + ','.join(fields))


def pages(call, *args, max_items=10000, **kwargs):
    """Consume every requested page or fail visibly; no silent caps."""
    offset, total, items = 0, None, []
    while True:
        page = call(*args, limit=200, offset=offset, **kwargs)
        require(page, ('status','items','total','limit','offset','next_offset'), call.__name__)
        if page['status'] == 'UNSUPPORTED':
            return [], {'status':'UNSUPPORTED', 'reason':page.get('reason')}
        if not isinstance(page['total'], int) or page['total'] < 0 or not isinstance(page['items'], list):
            raise ReaderContractError('Invalid page totals/items')
        if total is None:
            total = page['total']
        if total != page['total'] or total > max_items:
            raise ReaderContractError('Changed or over-limit collection: ' + call.__name__)
        items.extend(page['items'])
        if page['next_offset'] is None:
            if len(items) != total:
                raise ReaderContractError('Incomplete page traversal: ' + call.__name__)
            return items, {'status':page['status'], 'total':total, 'all_pages_read':True}
        if page['next_offset'] <= offset or page['next_offset'] != len(items):
            raise ReaderContractError('Nonadvancing/discontinuous reader pagination')
        offset = page['next_offset']


def checked_provenance(prov, where):
    require(prov, ('database_record','original_source','derived_document','source_locator','currency','lineage_status'), where)
    require(prov['database_record'], ('table','id'), where + '.database_record')
    require(prov['currency'], ('source_currency','dependency_impact'), where + '.currency')
    return prov


def citation(prov, cells=None):
    original = prov.get('original_source') or {}
    derived = prov.get('derived_document') or {}
    loc = prov.get('source_locator') or {}
    filename = original.get('filename') or Path(original.get('relative_path') or original.get('source_path') or '').name
    parts = []
    for key, label in [('drawing_number','drawing'),('sheet','sheet'),('row','row'),('cell','cell'),('handle','handle')]:
        if loc.get(key) is not None:
            parts.append(label + ' ' + plain(loc[key]))
    if loc.get('pdf_page') is not None:
        parts.append(('derived PDF' if derived else 'physical PDF') + ' p.' + str(loc['pdf_page']))
    if loc.get('clause') is not None:
        parts.append('clause ' + str(loc['clause']))
    for cell in cells or []:
        if not isinstance(cell, dict):
            continue
        for key in ('cell','handle','worksheet_row'):
            if cell.get(key) is not None:
                item = key + ' ' + str(cell[key])
                if item not in parts:
                    parts.append(item)
    return {'filename':filename or 'UNKNOWN', 'locator':'; '.join(parts) or 'UNKNOWN',
            'drawing_number':loc.get('drawing_number'), 'original_file_id':original.get('file_id'),
            'revision_as_recorded':original.get('revision'), 'revision_verification':'NOT_REVALIDATED',
            'source_currency':prov['currency']['source_currency'], 'dependency_impact':prov['currency']['dependency_impact']}


def structural_fragment(item):
    """Negative structural filters only; never keyword-based applicability."""
    text = item['exact_original_paragraph_text'].strip()
    relation = str(item.get('relationship') or '').lower()
    if 'manufacturer_context' in relation or str(item.get('section') or '').upper() == 'MANUFACTURERS':
        return 'manufacturer_list_not_requirement'
    if item.get('classification') not in ('unreviewed_requirement_paragraph_candidate','requirement','technical_requirement'):
        return 'non_requirement_classification'
    if not text:
        return 'empty_fragment'
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if re.fullmatch(r'(?:SECTION\s+\S+|PART\s+\d+\s*[-\u2013\u2014].*|Page\s+\d+\s+of\s+\d+)', text, re.I):
        return 'heading_or_page_footer'
    if re.match(r'^Rev\.?\s*\d+.*Section\s+\S+', text, re.I):
        return 'revision_footer'
    if len(lines) <= 2 and (re.search(r'\bCairo\s+Suez\s+Road\b', text, re.I) or text == text.upper() and len(text) < 150):
        return 'cover_or_heading'
    if re.match(r'^\d+\s*\.\s*\d+\s+[A-Z][A-Z\s-]+$', text):
        return 'numbered_heading'
    return None


def validate_options(options):
    if options.get('schema_version') != 'mep-supplier-draft-config/1':
        raise ValueError('Requires mep-supplier-draft-config/1')
    if not options.get('family') and not options.get('references'):
        raise ValueError('Select a family or explicit references')
    if options.get('language','en') != 'en':
        raise ValueError('Only English supplier output is supported; source text is never translated')
    if options.get('schedule_format','xlsx') != 'xlsx' or options.get('specification_format','pdf') != 'pdf':
        raise ValueError('Required draft outputs are xlsx and pdf; optional docx is additional and explicit')
    if options.get('status','draft').lower() != 'draft':
        raise ValueError('This phase supports DRAFT ONLY')
    if options.get('source_reference_visibility','compact') not in ('compact','detailed'):
        raise ValueError('Source visibility is compact or detailed; source references cannot be disabled')
    if options.get('include_missing_information',True) is not True:
        raise ValueError('Missing information cannot be hidden in draft packages')
    if not isinstance(options.get('max_equipment',500),int) or not 1 <= options.get('max_equipment',500) <= 10000:
        raise ValueError('max_equipment must be 1..10000')
    if not isinstance(options.get('max_supplier_clauses',60),int) or not 1 <= options.get('max_supplier_clauses',60) <= 300:
        raise ValueError('max_supplier_clauses must be 1..300')
    for rule in options.get('specification_rules',[]):
        if not rule.get('section') or rule.get('category',CATEGORIES[2]) not in CATEGORIES:
            raise ValueError('Every specification rule needs an explicit section and supported category')
        if not rule.get('basis'):
            raise ValueError('Specification selection needs an explicit recorded/configuration basis')
        if not rule.get('discipline'):
            raise ValueError('Specification rule discipline must be explicit')


class SupplierDraftGenerator:
    def __init__(self, reader, options):
        validate_options(options)
        self.reader, self.options = reader, dict(options)
        self.gaps = []
        probe = reader.envelope('supplier_contract_probe')
        if probe.get('schema_version') != CONTRACT:
            raise ReaderContractError('Unsupported EvidenceReader envelope version')
        self.snapshot = probe['currency_assessment']
        self.provenance = {}

    def audit(self, record, kind):
        prov = checked_provenance(record['provenance'], kind)
        identity = fingerprint({'kind':kind,'id':record.get('evidence_id'), 'provenance':prov})[:20]
        self.provenance[identity] = {'kind':kind, 'evidence_id':record.get('evidence_id'), 'provenance':prov,
                                    'saved_fact':record}
        return identity

    def selected_equipment(self):
        def listing(**kwargs):
            envelope = self.reader.list_equipment(self.options.get('family'),**kwargs)
            require(envelope,('schema_version','result'),'list_equipment')
            if envelope['schema_version'] != CONTRACT:
                raise ReaderContractError('Equipment list version mismatch')
            return envelope['result']
        rows, coverage = pages(listing,max_items=self.options.get('max_equipment',500))
        if coverage['status'] == 'UNSUPPORTED':
            raise ReaderContractError('Equipment list not supported: ' + str(coverage))
        wanted = set(self.options.get('references',[]))
        selected = []
        found = set()
        for row in rows:
            require(row,('id','normalized_tag','family','identity_kind','provenance'),'equipment identity')
            if wanted:
                keys = {row['id'],row['normalized_tag'],*(row.get('original_tags') or [])}
                matches = {w for w in wanted if any(str(w).casefold()==str(k).casefold() for k in keys)}
                if not matches:
                    continue
                found.update(matches)
            if not row.get('family') or not row.get('normalized_tag'):
                raise ReaderContractError('Missing stored family/tag; do not invent a grouping')
            selected.append(row)
        if wanted-found:
            raise ReaderContractError('Selected equipment not exposed by reader list: '+', '.join(sorted(wanted-found)))
        if not selected:
            raise ValueError('No current equipment references in requested scope')
        return sorted(selected,key=lambda r:(r['family'],r['normalized_tag'],r['id']))

    def compile_family(self, family, identities):
        equipment, parameters, issues, context = [], [], [], []
        allowed_disciplines = set(self.options.get('disciplines',['Mechanical','Electrical','BMS']))
        role_disciplines = self.options.get('role_disciplines',{'schedule':'Mechanical','drawing':'Mechanical','electrical':'Electrical','bms':'BMS','boq':'Mechanical'})
        for identity in identities:
            tag, reference = identity['normalized_tag'], identity['id']
            identity_ref = self.audit({'evidence_id':identity['id'],'provenance':identity['provenance'],**identity},'equipment_identity')
            native, native_coverage = pages(self.reader.get_observations,reference,max_items=10000)
            facts, param_coverage = pages(self.reader.get_parameters,reference,max_items=10000)
            findings, finding_coverage = pages(self.reader.get_findings,reference,max_items=10000)
            row = {'tag':tag,'family':family,'identity_kind':identity['identity_kind'], 'description':identity.get('description'),
                'identity_ref':identity_ref,'physical_quantity':None,'physical_quantity_status':'UNKNOWN \u2014 NOT VERIFIED',
                'scheduled_quantities':[],'installation_location':[],'area_served':[],'source_refs':[],
                'review_status':identity.get('review_status','UNKNOWN'),'coverage':{'observations':native_coverage,'parameters':param_coverage,'findings':finding_coverage}}
            seen = {}
            for fact in facts:
                require(fact,('evidence_id','original_name','original_printed_value','unit','original_parameter','provenance','schedule_role','review'),'equipment parameter')
                if role_disciplines.get(fact['schedule_role']) not in allowed_disciplines:
                    continue
                ref = self.audit(fact,'parameter')
                value = original_value(fact)
                prov = fact['provenance']
                source = citation(prov,fact.get('source_cells'))
                signature = fingerprint([tag,fact['original_name'],value,fact['unit'],prov.get('original_source'),
                    fact.get('source_cells'),prov.get('source_locator')])
                if signature in seen:
                    seen[signature]['provenance_refs'].append(ref)
                    continue
                entry = {'tag':tag,'family':family,'name':fact['original_name'],'value':value,'unit':fact['unit'],
                    'component_context':fact.get('component_or_operating_context'),'value_status':'AS PRINTED \u2014 UNREVIEWED' if known(value) else 'MISSING / PRINTED PLACEHOLDER',
                    'review':fact['review'],'source':source,'provenance_refs':[ref]}
                parameters.append(entry);seen[signature]=entry
                row['source_refs'].append(ref)
                name = str(fact['original_name']).casefold()
                if name in self.options.get('location_parameter_names',['location','installation_location']) and known(value):
                    row['installation_location'].append({'value':value,'provenance_ref':ref})
                if name in self.options.get('area_parameter_names',['area_served']) and known(value):
                    row['area_served'].append({'value':value,'provenance_ref':ref})
                if name in self.options.get('quantity_parameter_names',['quantity','scheduled_quantity']) and fact['schedule_role']=='schedule' and known(value):
                    row['scheduled_quantities'].append({'value':value,'unit':fact['unit'],'status':'EXPLICIT SCHEDULE DECLARATION \u2014 PHYSICAL COUNT NOT APPROVED','provenance_ref':ref})
            for obs in native:
                require(obs,('evidence_id','role','original_data','provenance'),'equipment observation')
                if obs['role']=='schedule' and role_disciplines.get('schedule') in allowed_disciplines and known(obs['original_data'].get('quantity')):
                    ref=self.audit(obs,'scheduled_quantity')
                    row['scheduled_quantities'].append({'value':obs['original_data']['quantity'],'unit':None,
                        'status':'EXPLICIT SCHEDULE DECLARATION \u2014 PHYSICAL COUNT NOT APPROVED','provenance_ref':ref})
            issues.append({'tag':tag,'item':'Physical equipment quantity','detail':'UNKNOWN. Reference labels and repeated occurrences do not establish a physical count.',
                'status':'ENGINEERING CONFIRMATION REQUIRED','provenance_refs':[identity_ref]})
            if not any(p['tag']==tag and known(p['value']) for p in parameters):
                issues.append({'tag':tag,'item':'Equipment schedule','detail':'No usable technical schedule values exposed in the selected discipline scope.',
                    'status':'MISSING SOURCE DATA','provenance_refs':[identity_ref]})
            for name in self.options.get('essential_parameters',[]):
                if not any(p['tag']==tag and p['name']==name and known(p['value']) for p in parameters):
                    issues.append({'tag':tag,'item':name,'detail':'Essential value not available in selected saved schedule evidence.',
                        'status':'MISSING SOURCE DATA','provenance_refs':[identity_ref]})
            for finding in findings:
                if finding.get('classification') not in ('MISSING_INFORMATION','POTENTIAL_CONFLICT','UNVERIFIED_LINK','SOURCE_VALUE_DIFFERENCE'):
                    continue
                ref=self.audit(finding,'saved_finding')
                issues.append({'tag':tag,'item':finding.get('parameter'),'detail':finding.get('note'),
                    'status':finding.get('classification'),'provenance_refs':[ref]})
            for role in self.options.get('optional_context',[]):
                if role not in ('boq','electrical','bms','drawing'):
                    raise ValueError('Unsupported optional context role')
                if role_disciplines.get(role) not in allowed_disciplines:
                    continue
                records, cov=pages(self.reader.get_context,reference,role=role,max_items=10000)
                for item in records:
                    ref=self.audit(item,'optional_context')
                    context.append({'tag':tag,'role':role,'text':item.get('raw_text'),'status':item.get('relationship_status'),
                                    'provenance_refs':[ref],'source':citation(item['provenance'])})
                if cov['status']=='UNSUPPORTED':self.gaps.append({'reference':reference,'domain':role,'coverage':cov})
            for domain,cov in row['coverage'].items():
                if cov['status']=='UNSUPPORTED':self.gaps.append({'reference':reference,'domain':domain,'coverage':cov})
            equipment.append(row)
        specs, review, selection = self.select_specifications(family,identities)
        if not specs:
            issues.append({'tag':'FAMILY','item':'Equipment specification selection','detail':'No traceable technical clauses selected. Review explicit section/clause configuration and saved applicability.',
                           'status':'MISSING SOURCE DATA','provenance_refs':[]})
        return {'family':family,'equipment':equipment,'parameters':sorted(parameters,key=lambda p:(p['tag'],p['name'],canonical(p['value']),p['provenance_refs'][0])),
                'issues':sorted(issues,key=lambda p:(p['tag'],p['item'] or '',p['status'])),
                'specifications':specs,'optional_context':context,'internal_specification_review':review,'selection':selection,
                'incomplete':bool(issues),'status':DRAFT,'incomplete_status':INCOMPLETE if issues else None}

    def select_specifications(self,family,identities):
        included, uncertain, counts, seen, visited = [], [], Counter(), {}, set()
        # UC list exposes the run: same run+family shares existing rule scope. Missing run => per-reference, safely.
        scopes={}
        for identity in identities:
            scopes.setdefault((identity.get('run_id') or identity['id'],family),identity)
        summaries=[]
        for identity in scopes.values():
            reference=identity['id']
            probe=self.reader.get_specifications(reference,limit=1)
            require(probe,('status','total','items','next_offset'),'specification probe')
            summary={'representative_reference':reference,'family_candidate_total':probe['total'],
                     'scope_basis':'Existing reader UC family and run relationship','sections_queried':[]}
            if identity.get('schema_version')=='mep-equipment-profile/1':
                summary['scope_basis']='Exact native source reference; explicit clause IDs or recorded native requirement links, Pending'
            for rule in self.options.get('specification_rules',[]):
                if rule.get('families') and family not in rule['families']:
                    continue
                if rule['discipline'] not in self.options.get('disciplines',['Mechanical','Electrical','BMS']):
                    continue
                section=str(rule['section'])
                selection={}
                if identity.get('schema_version')=='mep-equipment-profile/1':
                    selection['evidence_ids']=list(dict.fromkeys([*rule.get('evidence_ids',[]),*([rule['title_evidence_id']] if rule.get('title_evidence_id') else [])]))
                records, coverage=pages(self.reader.get_specifications,reference,section=section,max_items=10000,**selection)
                summary['sections_queried'].append({'section':section,**coverage})
                if coverage['status']=='UNSUPPORTED':
                    self.gaps.append({'domain':'specifications','section':section,'coverage':coverage});continue
                title=next((r for r in records if r['evidence_id']==rule.get('title_evidence_id')),None)
                if rule.get('title_evidence_id') and title is None:
                    raise ReaderContractError('Selected section-title evidence is not available in this scope')
                configured_ids=set(rule.get('evidence_ids',[]));found=set()
                for item in records:
                    require(item,('evidence_id','exact_original_paragraph_text','classification','section','physical_pdf_page',
                        'clause','applicability_status','provenance'),'specification fact')
                    checked_provenance(item['provenance'],'specification provenance')
                    key=(reference,section,item['evidence_id'])
                    if key in visited:continue
                    visited.add(key)
                    reason=structural_fragment(item)
                    if configured_ids and item['evidence_id'] not in configured_ids:
                        reason=reason or 'outside_explicit_clause_selection'
                    elif item['evidence_id'] in configured_ids:found.add(item['evidence_id'])
                    prov=item['provenance'];original=prov.get('original_source') or {};src=citation(prov)
                    if not reason and (not original.get('file_id') or not original.get('sha256') or not original.get('id') or not item.get('physical_pdf_page')):
                        reason='incomplete_source_citation'
                    if not reason and str(original.get('filename') or original.get('source_path') or '').lower().endswith(('.doc','.docx')) and not prov.get('derived_document'):
                        reason='missing_derived_pdf_identity'
                    if reason:
                        counts[reason]+=1
                        if reason in ('incomplete_source_citation','missing_derived_pdf_identity','outside_explicit_clause_selection'):
                            uncertain.append({'reason':reason,'section':section,'evidence_id':item['evidence_id'],
                                'text':item['exact_original_paragraph_text'],'provenance':prov})
                        continue
                    category=rule.get('category',CATEGORIES[2])
                    if category==CATEGORIES[0] and str(item['applicability_status']).casefold() not in ('approved','confirmed'):
                        category=CATEGORIES[2]
                    # Explicit mapped general requirements stay general; conditional scope is not approval.
                    if category==CATEGORIES[2] and 'conditional' in str(item.get('relationship') or '').casefold():category=CATEGORIES[3]
                    dedup=fingerprint([original.get('file_id'),original.get('sha256'),item['section'],item['physical_pdf_page'],
                                      re.sub(r'\s+',' ',item['exact_original_paragraph_text']).strip()])
                    ref=self.audit(item,'specification')
                    if dedup in seen:
                        seen[dedup]['provenance_refs'].append(ref);counts['duplicate_clause']+=1;continue
                    entry={'section':section,'section_title':title['exact_original_paragraph_text'] if title else item.get('section_title'),
                        'section_title_provenance':title['provenance'] if title else None,
                        'clause':item['clause'],'paragraph':item.get('paragraph_number'),'text':item['exact_original_paragraph_text'],
                        'physical_pdf_page':item['physical_pdf_page'],'page_basis':'derived PDF physical page' if prov.get('derived_document') else 'original PDF physical page',
                        'verified_printed_page':item.get('verified_printed_page'),
                        'source':src,'category':category,'applicability_status':item['applicability_status'],
                        'condition':item.get('condition'),'selection_basis':rule['basis'],'provenance_refs':[ref],
                        'source_order':(prov['source_locator'].get('bbox') or [0,0])[1]}
                    seen[dedup]=entry;included.append(entry)
                if configured_ids-found:
                    self.gaps.append({'domain':'explicit_specification_clauses','section':section,'unavailable_ids':sorted(configured_ids-found)})
            summaries.append(summary)
        included.sort(key=lambda r:(r['section'],r['source']['filename'],r['physical_pdf_page'],r['source_order'],r['clause'] or '',r['provenance_refs'][0]))
        cap=self.options.get('max_supplier_clauses',60)
        if len(included)>cap:
            raise ValueError('Selected clauses exceed compact limit; narrow explicit sections/clauses. Nothing silently truncated.')
        return included,uncertain,{'scopes':summaries,'exclusions':dict(sorted(counts.items())), 'included_unique_clauses':len(included),
            'automatic_keyword_applicability':False,'unqueried_candidates':'Not selected; no claim of complete applicability review'}

    def compile(self):
        rows=self.selected_equipment();groups={}
        for row in rows:groups.setdefault(row['family'],[]).append(row)
        families=[self.compile_family(name,group) for name,group in sorted(groups.items())]
        def limitations_page(**kwargs):
            response=self.reader.list_source_limitations(**kwargs)
            require(response,('schema_version','result'),'source limitations')
            if response['schema_version']!=CONTRACT:raise ReaderContractError('Source limitation version mismatch')
            return response['result']
        source_limitations,limitation_coverage=pages(limitations_page,max_items=10000)
        if limitation_coverage['status']=='UNSUPPORTED':self.gaps.append({'domain':'source_limitations','coverage':limitation_coverage})
        content={'schema_version':'mep-supplier-draft/1','reader_contract':CONTRACT,
            'project_id':self.reader.cfg['project_id'],'project_name':self.options.get('project_name') or self.reader.cfg.get('project_name') or self.reader.cfg['project_id'],
            'title':self.options.get('title','Equipment technical package'),'options':self.options,
            'currency_assessment':self.snapshot,'families':families,'provenance':self.provenance,'interface_gaps':self.gaps,
            'project_source_limitations':{'records':source_limitations,'coverage':limitation_coverage,
                'scope':'Project-level saved limitations; not automatically equipment-specific applicability'},
            'engineering_approval_created':False,'source_data_writes':False,'status':DRAFT}
        content['content_fingerprint']=fingerprint(content)
        return content


def safe_output(reader,output):
    root=Path(output).resolve()
    cfg=reader.cfg
    blocked=[Path(cfg['source_directory']).resolve(),Path(cfg['database']).resolve().parent,HOME.resolve()]
    # Use the reader's supported safety interface; no independent archive SQL.
    for parent in root.parents:
        if parent in blocked:raise ValueError('Package output must be outside source/state/master')
    if root in blocked:raise ValueError('Unsafe output directory')
    if root.exists():raise FileExistsError('Use a new output directory; previous packages are never replaced')
    return root


def generate_supplier_drafts(reader,options,output_directory,*,node_executable=None,artifact_module_root=None):
    """Compile and render one folder per stored family; explicit draft output only."""
    root=safe_output(reader,output_directory)
    generator=SupplierDraftGenerator(reader,options)
    content=generator.compile()
    # Reader owns the archive/source/state safety contract. Probe export only after all compilation succeeds.
    probe=root/'internal'/'compilation.json'
    reader.write_json(probe,content)
    internal=root/'internal'
    receipt={'schema_version':'mep-supplier-render-receipt/1','status':'RUNNING','content_fingerprint':content['content_fingerprint'],
        'generated_at':datetime.now(timezone.utc).isoformat(),'packages':[]}
    receipt_path=internal/'render-receipt.json'
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        for family in content['families']:
            slug=re.sub(r'[^A-Za-z0-9_-]+','-',family['family']).strip('-') or 'Equipment'
            slug += '-' + fingerprint(family['family'])[:6]
            package=root/slug
            package.mkdir()
            family_internal=package/'internal';family_internal.mkdir()
            used=set()
            def visit(value):
                if isinstance(value,str) and value in content['provenance']:used.add(value)
                elif isinstance(value,dict):
                    for v in value.values():visit(v)
                elif isinstance(value,list):
                    for v in value:visit(v)
            visit(family)
            manifest={'schema_version':'mep-supplier-provenance/1','content_fingerprint':content['content_fingerprint'],
                'project_id':content['project_id'],'family':family['family'],'scope_tags':[r['tag'] for r in family['equipment']],
                'currency_assessment':content['currency_assessment'],'selection':family['selection'],
                'project_source_limitations':content['project_source_limitations'],
                'source_provenance':{k:content['provenance'][k] for k in sorted(used)},'interface_gaps':content['interface_gaps'],
                'draft_only':True,'supplier_files':['Equipment Technical Schedule.xlsx','Equipment Technical Specifications.pdf']}
            if options.get('docx',False):manifest['supplier_files'].append('Equipment Technical Specifications.docx')
            (family_internal/'provenance-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            (family_internal/'specification-review.json').write_text(json.dumps(family['internal_specification_review'],ensure_ascii=False,indent=2),encoding='utf-8')
            render_pdf(content,family,package/'Equipment Technical Specifications.pdf')
            if options.get('docx',False):render_docx(content,family,package/'Equipment Technical Specifications.docx')
            renderer=HOME/'scripts/master_project/supplier_schedule.mjs'
            node=node_executable or shutil.which('node')
            if not node:raise ValueError('Node runtime unavailable; resolve bundled runtime using workspace dependency loader')
            command=[str(node),str(renderer),'--input',str(probe),'--family',family['family'],'--output',str(package)]
            if artifact_module_root:command+=['--module-root',str(artifact_module_root)]
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            (family_internal/'spreadsheet-render.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError('Spreadsheet renderer failed; see '+str(family_internal/'spreadsheet-render.log'))
            files=[]
            for name in manifest['supplier_files']:
                path=package/name
                if not path.is_file() or path.stat().st_size==0:raise RuntimeError('Missing rendered output: '+name)
                files.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            receipt['packages'].append({'family':family['family'],'path':str(package),'files':files,
                'reference_count':len(family['equipment']),'parameter_rows':len(family['parameters']),
                'specification_clauses':len(family['specifications']),'incomplete':family['incomplete']})
        receipt['status']='COMPLETED_DRAFT'
    except BaseException as error:
        receipt.update(status='FAILED_PARTIAL_DRAFT',error=type(error).__name__+': '+str(error))
        raise
    finally:receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


def render_pdf(content,family,path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,KeepTogether,Table,TableStyle
    import reportlab
    fonts=Path(reportlab.__file__).parent/'fonts'
    if 'SupplierVera' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('SupplierVera',str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('SupplierVeraBold',str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('SupplierVera',normal='SupplierVera',bold='SupplierVeraBold')
    body=ParagraphStyle('body',fontName='SupplierVera',fontSize=9,leading=13,spaceAfter=7,textColor=colors.HexColor('#243447'))
    title=ParagraphStyle('title',parent=body,fontName='SupplierVeraBold',fontSize=19,leading=24,spaceAfter=10)
    heading=ParagraphStyle('heading',parent=body,fontName='SupplierVeraBold',fontSize=12,leading=16,spaceBefore=12,spaceAfter=7)
    small=ParagraphStyle('small',parent=body,fontSize=7.5,leading=11,spaceAfter=3,textColor=colors.HexColor('#4D6073'))
    warning=ParagraphStyle('warning',parent=body,fontName='SupplierVeraBold',fontSize=9,leading=13,textColor=colors.HexColor('#9C4125'))
    p=lambda text,style=body:Paragraph(escape(plain(text)).replace('\n','<br/>'),style)
    story=[p(content['project_name'],small),p(family['family']+' \u2014 Technical specifications',title),p(DRAFT,warning)]
    if family['incomplete']:story.append(p(INCOMPLETE,warning))
    story+=[p(content['title'],body),p('Scope: '+', '.join(r['tag'] for r in family['equipment']),small),
        p('Physical equipment quantity: UNKNOWN. Schedule declarations, where present, are separate from approved physical counts.',small)]
    snapshot=content['currency_assessment']
    story.append(p('Source assessment: '+str(snapshot.get('assessed_at') or 'UNKNOWN')+'; saved snapshot only. Source currency is not engineering approval.',small))
    story.append(p('Citations use physical pages of the derived PDF when identified. Printed pages and parent clause hierarchy are not inferred.',small))
    if family['issues']:
        story.append(p('Outstanding technical information',heading))
        grouped={}
        for issue in family['issues']:
            key=(issue['item'],issue['detail'],issue['status']);grouped.setdefault(key,[]).append(issue['tag'])
        for (item,detail,status),tags in grouped.items():
            # Keep detailed per-tag source findings in the schedule; concise shared gaps here.
            if status not in ('MISSING SOURCE DATA','ENGINEERING CONFIRMATION REQUIRED','MISSING_INFORMATION'):continue
            scope='All listed references' if len(tags)==len(family['equipment']) else ', '.join(sorted(set(tags)))
            story.append(p(scope+': '+str(item)+'. '+str(detail),small))
    current=None
    for clause in family['specifications']:
        group=(clause['section'],clause['source']['filename'])
        if group!=current:
            story.append(p('Section '+clause['section']+(' \u2014 '+clause['section_title'] if clause.get('section_title') else ''),heading));current=group
        label='Clause '+str(clause['clause']) if clause['clause'] else 'Clause number UNKNOWN'
        if clause.get('paragraph'):label+=' / paragraph '+str(clause['paragraph'])
        source=clause['source']['filename']+'; '+clause['page_basis']+' '+str(clause['physical_pdf_page'])
        if clause['verified_printed_page'] is not None:source+='; verified printed page '+str(clause['verified_printed_page'])
        ref=', '.join(clause['provenance_refs'])
        story.append(KeepTogether([p(label+' \u2014 '+clause['category'],small),
            p('Applicability: '+str(clause['applicability_status'])+'; '+source,small),
            p(clause['text'],body),p('Source ref: '+ref,small)]))
    if not family['specifications']:story.append(p('No specification clauses could be selected reliably from the configured evidence.',warning))
    def decorate(canvas,doc):
        width,height=A4;canvas.saveState();canvas.setStrokeColor(colors.HexColor('#CBD5E1'));canvas.line(42,height-35,width-42,height-35)
        canvas.setFont('SupplierVera',7);canvas.setFillColor(colors.HexColor('#52677A'))
        canvas.drawString(42,23,DRAFT);canvas.drawRightString(width-42,23,'Page '+str(doc.page));canvas.restoreState()
    class DeterministicCanvas(Canvas):
        def __init__(self,*args,**kwargs):kwargs['invariant']=1;super().__init__(*args,**kwargs)
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=47,bottomMargin=43,
        title=family['family']+' Technical Specifications',author='MEP Project Master',pageCompression=1)
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate,canvasmaker=DeterministicCanvas)


def render_docx(content,family,path):
    """Only invoked for explicit docx:true. No Word automation or external service."""
    from docx import Document
    document=Document();document.add_heading(content['project_name'],0);document.add_heading(family['family'],1)
    document.add_paragraph(DRAFT)
    if family['incomplete']:document.add_paragraph(INCOMPLETE)
    for clause in family['specifications']:
        document.add_heading('Section '+clause['section']+' / clause '+str(clause['clause'] or 'UNKNOWN'),2)
        document.add_paragraph(clause['category']+'; applicability '+str(clause['applicability_status']))
        document.add_paragraph(clause['text'])
        document.add_paragraph(clause['source']['filename']+'; physical derived PDF page '+str(clause['physical_pdf_page'])+'; refs '+', '.join(clause['provenance_refs']))
    document.save(path)


def render_procurement_items(cfg, view, *, mode='review', issue_confirmation=None):
    """General item extension; legacy equipment compilation/rendering is unchanged.

    The caller owns exact user issue confirmation. The item renderer is used once
    per output and never calls the original equipment-only package generator.
    """
    if mode=='issue':
        if not issue_confirmation or issue_confirmation.get('fingerprint')!=view['fingerprint'] or set(issue_confirmation.get('item_ids',[]))!={i['id'] for i in view['items']} or not issue_confirmation.get('statement'):
            raise PermissionError('Exact scoped human issue confirmation required')
    from .procurement_documents import render
    return render(cfg, view, mode=mode)
