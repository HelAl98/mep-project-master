"""Source-bound candidate retrieval reusing the existing technical reviewer rules.

The Main Agent supplies project selectors, never the source document itself.
Matches remain candidates. Selection omissions are explicit persisted coverage.
"""
import importlib
import json
from pathlib import Path
import re
import sys

from . import procurement_items as items
from .procurement_evidence import classify


def validate_options(options):
    allowed={'scope','mappings','specification_rules','specification_limit','quantity_checks','quantity_tolerances'}
    if not isinstance(options,dict) or set(options)-allowed:
        raise ValueError('Unsupported procurement options')
    limit=options.get('specification_limit',300)
    if type(limit) is not int or not 1<=limit<=10000:raise ValueError('Specification limit must be 1..10000')
    for rule in options.get('specification_rules',[]):
        if not rule.get('id') or not rule.get('basis') or not rule.get('items') or not rule.get('requirements'):
            raise ValueError('Specification rules require id, source-based rationale and explicit selectors')
        if set(rule['items'])-{'categories','systems','tags'}:
            raise ValueError('Unsupported item selector')
        if set(rule['requirements'])-{'sections','topics','technical_categories','text_terms','file_ids','systems','scopes','disciplines'}:
            raise ValueError('Unsupported native reviewer requirement selector')
        for pattern in rule['requirements'].get('sections',[]):re.compile(pattern)
    plans=options.get('quantity_checks',[])
    if not isinstance(plans,list) or any(not p.get('id') for p in plans) or len({p['id'] for p in plans})!=len(plans):
        raise ValueError('Quantity checks require unique stable IDs')
    for tolerance in options.get('quantity_tolerances',{}).values():
        from .procurement_geometry import number
        if any(number(tolerance.get(k,0))<0 for k in ('relative','absolute')):
            raise ValueError('Review tolerances must be finite and nonnegative')


def candidate_links(conn,cfg,states,options):
    scripts=str(Path(cfg['skills_root'])/'mep-cross-document-reviewer/scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    engine=importlib.import_module('technical_review.engine')
    common=importlib.import_module('technical_review.common')
    native_config=common.configuration(cfg.get('review_config'))
    records={rid:state for state in states for rid in state['record_ids']}
    clauses=[]
    for rid,state in records.items():
        raw=items.core_fact(conn,rid);record=raw['record']
        if record['kind']!='specification' or record['raw_text'].strip().upper().startswith('SECTION '):continue
        clauses.append((rid,raw,{'context':{'section':record['source'].get('spec_section'),
                         'system':record['data'].get('system'),'scope':record['data'].get('scope'),
                         'discipline':json.loads(raw['metadata_json']).get('discipline')},
                         'classification':common.classify(record['raw_text'],native_config),
                         'source':{'file_id':state['file_id']},'original_text':record['raw_text']}))
    clauses.sort(key=lambda r:(r[1]['filename'],r[1]['citation'].get('pdf_page') or 0,r[0]))
    result={'link_ids':[],'omitted':{},'evaluated':{},'unlinked_clause_ids':[],
            'method':'Existing technical_review classification and requirement_selected; no applicability approval',
            'limit_per_item':options.get('specification_limit',300)}
    linked=set()
    for item in conn.execute('SELECT id,category,identity_json FROM master_procurement_items WHERE project_id=? ORDER BY id',(cfg['project_id'],)):
        if not any(r[0] in records for r in conn.execute('SELECT record_id FROM master_procurement_links WHERE item_id=?',(item['id'],))):continue
        identity=json.loads(item['identity_json']);hits=[]
        for rid,raw,requirement in clauses:
            text=raw['record']['raw_text'];bases=[]
            if item['category']!='other' and classify(text)==item['category']:bases.append('literal category')
            tag=identity.get('tag')
            if tag and re.search(r'(?<!\w)'+re.escape(tag)+r'(?!\w)',text,re.I):bases.append('literal tag')
            for rule in options.get('specification_rules',[]):
                selector=rule['items'];values={'categories':item['category'],'systems':identity.get('service'),'tags':tag}
                if any(str(values[k]).casefold() not in {str(v).casefold() for v in vals} for k,vals in selector.items()):continue
                if engine.requirement_selected(requirement,rule['requirements']):bases.append('rule '+rule['id']+': '+rule['basis'])
            if bases:hits.append((rid,text,'; '.join(bases)))
        result['evaluated'][item['id']]={'clauses_examined':len(clauses),'matching_clauses':len(hits),'selected':min(len(hits),result['limit_per_item'])}
        omitted=hits[result['limit_per_item']:]
        if omitted:result['omitted'][item['id']]=[rid for rid,_,_ in omitted]
        for rid,text,basis in hits[:result['limit_per_item']]:
            relation='conditional' if re.search(r'\b(where|if|unless|when)\b|\u0639\u0646\u062f|\u0625\u0630\u0627',text,re.I) else 'candidate'
            result['link_ids'].append(items.add_link(conn,cfg,item['id'],rid,relation=relation,basis='Auto specification: '+basis))
            linked.add(rid)
    result['link_ids']=sorted(result['link_ids'])
    result['unlinked_clause_ids']=sorted({rid for rid,_,_ in clauses}-linked)
    result['unlinked_meaning']='Not selected by current rules; not a claim that these clauses are irrelevant or reviewed'
    return result
