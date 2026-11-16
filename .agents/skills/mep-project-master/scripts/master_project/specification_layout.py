"""Narrow Operation B acceptance of native, unreviewed specification fragments."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
from .common import read,sha
from .interfaces import reference

POLICY='operation-B-native-specification-layout/1'
LAYOUT_WARNING={'code':'specification_layout_review','message':'Line grouping, section/clause context and page continuations are candidates for review. Headers, footers and columns are not semantically resolved.'}


def _require(value,message):
    if not value:raise ValueError('Specification layout acceptance: '+message)


def _validate_package(memory,package):
    # Reuse the installed native contract, without constructing Store or writing SQLite.
    path=Path(memory.cfg['skills_root'])/'etl-pipeline/scripts/mep_store.py'
    spec=importlib.util.spec_from_file_location('_mep_specification_contract',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.validate_package(package)


def validate_input(memory,job):
    _require(job.get('skill')=='specification-extractor' and job.get('command')=='extract','unsupported native command')
    _require(len(job.get('inputs',[]))==1 and len(job.get('source_file_ids',[]))==1,'one exact input/source required')
    path=reference(memory,job['inputs'][0]);package=read(path);_validate_package(memory,package)
    _require(package['issues']==[],'upstream package issues are not covered by this policy')
    document=package['document'];_require(document['media_type']=='pdf','actual original PDF required')
    from .limited_scope import _source
    source,original=_source(memory,{'file_id':job['source_file_ids'][0],'sha256':document['sha256']})
    _require(Path(document['path']).resolve()==original.resolve() and document['filename']==original.name,'original PDF path/name mismatch')
    import pdfplumber
    with pdfplumber.open(original) as pdf:bounds=[(page.width,page.height) for page in pdf.pages]
    _require(bool(bounds),'PDF has no pages')
    lines=0
    for record in package['records']:
        _require(record['review']['status']=='unreviewed' and record['review']['issues']==[],'upstream record review/issues unsupported')
        locator=record['source'];page=locator['pdf_page']
        _require(1<=page<=len(bounds),'upstream page outside actual PDF')
        if record['kind']=='line':
            lines+=1;box=locator.get('bbox');width,height=bounds[page-1]
            _require(isinstance(box,list) and len(box)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in box),'line requires finite source bbox')
            _require(0<=box[0]<=box[2]<=width and 0<=box[1]<=box[3]<=height,'line bbox outside actual PDF')
    _require(lines>0,'no native line evidence')
    return path,package,bounds


def validate_result(memory,job,response,primary,policy):
    _require(policy==POLICY and getattr(memory,'operation_result_scope',None)==('B','native_job'),'acceptance is restricted to Operation B native execution')
    path,upstream,bounds=validate_input(memory,job)
    _validate_package(memory,response)
    _require(read(primary)==response,'result differs from persisted evidence file')
    _require(response['document']==upstream['document'],'output document/provenance changed')
    _require(response['issues']==[LAYOUT_WARNING],'only the exact single native layout warning is permitted')
    _require(bool(response['records']),'empty specification extraction')
    for record in response['records']:
        _require(record['kind']=='specification' and bool(record['raw_text'].strip()),'non-specification or empty fragment')
        _require(record['review']['status']=='unreviewed' and record['review']['issues']==[],'record-level warnings/approval are not covered')
        source=record['source'];indexes=source.get('input_record_indexes')
        _require(isinstance(indexes,list) and bool(indexes) and all(type(i) is int and 0<=i<len(upstream['records']) for i in indexes),'invalid upstream record indexes')
        _require(indexes==sorted(set(indexes)),'duplicate/out-of-order input indexes')
        lines=[upstream['records'][i] for i in indexes]
        _require(all(r['kind']=='line' for r in lines),'fragment does not cite native lines')
        _require(record['raw_text']=='\n'.join(r['raw_text'] for r in lines),'original text changed')
        _require(len({r['source']['pdf_page'] for r in lines})==1,'cross-page fragment unsupported')
        first=lines[0]['source'];boxes=[r['source']['bbox'] for r in lines]
        expected_box=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
        _require(source.get('bbox')==expected_box,'fragment bbox is not the original line union')
        _require(source.get('method')=='specification-extractor/1.0; local line grouping' and source.get('upstream_method')==first['method'],'unsupported extraction method')
        for key,value in first.items():
            if key not in ('bbox','method','spec_section','clause','input_record_indexes'):
                _require(source.get(key)==value,'source locator changed: '+key)
        fragments=[{'raw_text':r['raw_text'],'source':deepcopy(r['source']),'input_record_index':i} for i,r in zip(indexes,lines)]
        _require(record['data'].get('line_fragments')==fragments,'original line fragments/locators changed')
        _require(record['data'].get('continuation_candidate') is False,'page continuation requires separate review')
        _require(record['data'].get('fragments')==[{'raw_text':record['raw_text'],**deepcopy(source)}],'unsupported grouped fragment locators')
    return {'policy':POLICY,'status':'ACCEPTED_UNREVIEWED_WITH_LAYOUT_LIMITATION',
        'accepted_issues':deepcopy(response['issues']),'record_count':len(response['records']),
        'input_artifact':{'path':str(path),'sha256':sha(path)},'evidence_artifact':{'path':str(primary),'sha256':sha(primary)},
        'source_file_ids':list(job['source_file_ids']),'checks':['native_package_contract','live_original_and_archive','actual_pdf_page_and_line_bounds','exact_original_text_and_line_locators','unreviewed_records_only','exact_expected_layout_warning_only'],
        'full_source_coverage':False,'specification_applicability':'UNREVIEWED','engineering_approval_created':False,
        'etl_authorized':False,'supplier_release_authorized':False}
