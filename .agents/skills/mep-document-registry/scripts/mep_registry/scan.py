"""Incremental, bounded document discovery and immutable source registration."""
from datetime import datetime, timezone
import fnmatch
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid

from .common import dump, key, metadata_fingerprint, normalized_number, now, path_key, select_fields, skills_root as find_skills
from .db import Registry
from .extract import extract_document

MARKER = '.mep-registry-output.json'
EXCLUDED_DIRS = {'.git','.agents','.codex','__pycache__','.mep-registry'}


def validate_config(config):
    config = dict(config or {})
    dump(config)
    if not isinstance(config.get('exclude_globs', []),list) or any(not isinstance(v,str) for v in config.get('exclude_globs', [])):
        raise ValueError('exclude_globs must be an array of relative path patterns')
    order = config.get('revision_order', [])
    if not isinstance(order,list) or any(not isinstance(v,str) for v in order) or len(order)!=len(set(order)):
        raise ValueError('revision_order must be an explicit unique array of labels')
    if type(config.get('max_relationship_pairs',50000)) is not int or config.get('max_relationship_pairs',50000)<1:
        raise ValueError('max_relationship_pairs must be a positive integer')
    rules = config.get('classification_rules', [])
    if not isinstance(rules,list):
        raise ValueError('classification_rules must be an array')
    for rule in rules:
        if not isinstance(rule,dict) or rule.get('target') not in ('filename','relative_path','content'):
            raise ValueError('Invalid classification rule target')
        re.compile(rule.get('pattern',''))
    return config


def _excluded(relative, config):
    relative = str(relative).replace('\\','/')
    for pattern in config.get('exclude_globs', []):
        pattern = pattern.replace('\\','/')
        if fnmatch.fnmatch(relative, pattern) or (pattern.endswith('/**') and relative==pattern[:-3]):
            return True
    return False


def discover(root, config, db=None):
    """Never follow symlinks/junctions or descend into marked generated output."""
    root = Path(root).resolve(strict=True)
    db = Path(db).resolve() if db else None
    archive = db.parent/(db.stem+'.evidence') if db else None
    def walk(folder):
        if (folder/MARKER).is_file():
            return
        with os.scandir(folder) as entries:
            for entry in sorted(entries,key=lambda e:e.name.casefold()):
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if entry.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
                    continue
                if _excluded(relative,config):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in EXCLUDED_DIRS or (archive and path.resolve()==archive):
                        continue
                    yield from walk(path)
                elif entry.is_file(follow_symlinks=False):
                    absolute = path.resolve()
                    if db and (absolute==db or str(absolute) in {str(db)+'-wal',str(db)+'-shm',str(db)+'-journal'}):
                        continue
                    if path.suffix.lower() in ('.sqlite','.sqlite3','.db'):
                        continue
                    yield path,relative
    yield from walk(root)


def choose_database(root, explicit=None):
    if explicit is not None:
        return Path(explicit).resolve()
    root = Path(root).resolve()
    candidates = []
    for folder, dirs, filenames in os.walk(root, followlinks=False):
        parent = Path(folder)
        dirs[:] = [d for d in dirs if d not in {'.git','.agents','.codex','__pycache__'}
                   and not (parent/d/MARKER).exists() and not d.endswith('.evidence')
                   and not (parent/d).is_symlink() and not (hasattr(parent/d,'is_junction') and (parent/d).is_junction())]
        for name in filenames:
            path = parent/name
            if path.suffix.lower() not in ('.sqlite','.sqlite3','.db') or path.is_symlink():
                continue
            try:
                conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:
                    if conn.execute('pragma user_version').fetchone()[0]==2 and conn.execute("select 1 from sqlite_master where name='versions'").fetchone():
                        candidates.append(path.resolve())
                finally:
                    conn.close()
            except sqlite3.Error:
                continue
    if len(candidates)>1:
        raise ValueError('Multiple compatible engineering databases found; supply --db explicitly: '+', '.join(map(str,candidates)))
    return candidates[0] if candidates else root/'.mep-registry/engineering.sqlite'


def archive_source(path, db):
    """Stream stable source bytes into the same content-addressed archive as ETL."""
    path=Path(path)
    before=path.stat()
    base=Path(db).parent/(Path(db).stem+'.evidence')
    staging=base/'.staging'
    staging.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='registry-',dir=staging)
    temporary=Path(temporary)
    try:
        digest=hashlib.sha256()
        with path.open('rb') as source,os.fdopen(fd,'wb') as output:
            start=os.fstat(source.fileno())
            for chunk in iter(lambda:source.read(1024*1024),b''):
                digest.update(chunk); output.write(chunk)
            final=os.fstat(source.fileno())
        after=path.stat()
        if any((s.st_size,s.st_mtime_ns,s.st_ino)!=(before.st_size,before.st_mtime_ns,before.st_ino) for s in (start,final,after)):
            raise ValueError('Source changed during registration; retry a stable file')
        sha=digest.hexdigest()
        target=base/sha[:2]/sha
        target.parent.mkdir(parents=True,exist_ok=True)
        try:
            with target.open('xb') as destination,temporary.open('rb') as source:
                try:
                    shutil.copyfileobj(source,destination,1024*1024)
                    destination.flush()
                    os.fsync(destination.fileno())
                except BaseException:
                    destination.close()
                    if target.resolve().is_relative_to(base.resolve()):
                        target.unlink(missing_ok=True)
                    raise
        except FileExistsError:
            check=hashlib.sha256()
            with target.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):
                    check.update(chunk)
            if check.hexdigest()!=sha:
                raise ValueError('Retained evidence archive failed hash verification')
        stat={'size':after.st_size,'modified_at':datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat(),
              'modified_ns':after.st_mtime_ns}
        return sha,target,stat
    finally:
        # Only remove the known newly created temporary copy, never the input.
        if temporary.parent.resolve()==staging.resolve():
            temporary.unlink(missing_ok=True)


def signature(skills):
    versions={}
    for dist in ('pypdf','pdfplumber','openpyxl','python-docx','ezdxf'):
        try: versions[dist]=importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError: versions[dist]=None
    helpers=[Path(__file__).with_name('extract.py'),skills/'pdf-to-structured/scripts/extract_pdf.py',
             skills/'drawing-analyzer/scripts/analyze_drawing.py']
    return key('registry-extraction-v1',versions,{str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in helpers if p.is_file()})


def _stem(filename):
    stem=Path(filename).stem
    stem=re.sub(r'(?:^|[ _.-])REV(?:ISION)?[ _.-]*[A-Za-z0-9]+(?=$|[ _.-])','',stem,flags=re.I)
    return re.sub(r'[\s_.]+','-',stem).strip('-').casefold()


def _newer(left,right,order):
    a,b=left['metadata'].get('revision'),right['metadata'].get('revision')
    if a and b and a!=b:
        if a in order and b in order:
            return ('right' if order.index(b)>order.index(a) else 'left'),'project_revision_order'
        da,db=left['metadata'].get('revision_date'),right['metadata'].get('revision_date')
        try:
            d1,d2=datetime.fromisoformat(da),datetime.fromisoformat(db)
            if d1!=d2: return ('right' if d2>d1 else 'left'),'observed_iso_issue_date'
        except (TypeError,ValueError):
            pass
        if re.fullmatch(r'\d+',str(a)) and re.fullmatch(r'\d+',str(b)):
            return ('right' if int(b)>int(a) else 'left'),'numeric_label_heuristic_unverified'
        if re.fullmatch(r'[A-Z]',str(a)) and re.fullmatch(r'[A-Z]',str(b)):
            return ('right' if b>a else 'left'),'alphabetic_label_heuristic_unverified'
    return None,'ordering_unresolved'


def _candidate_pairs(registry,project_id,items,config,sheets=False):
    # Group indexed identities before forming pairs: unrelated documents never
    # produce a quadratic comparison pass on a large construction project.
    groups={}
    for item in items:
        identifiers=[('number',normalized_number(item['metadata'].get('document_number')))]
        if not sheets: identifiers += [('sha',item['sha256']),('name',_stem(item['filename']))]
        for identifier in identifiers:
            if identifier[1]: groups.setdefault(identifier,[]).append(item)
    seen=set(); maximum=config.get('max_relationship_pairs',50000)
    for group in groups.values():
        for left,right in itertools.combinations(group,2):
            pair=tuple(sorted([left.get('sheet_id') or left['file_id'],right.get('sheet_id') or right['file_id']]))
            if pair in seen: continue
            if len(seen)>=maximum:
                registry.issue(project_id,None,None,'RELATIONSHIP_LIMIT',
                    'Candidate relationship pair budget reached; all files remain registered, but relationship discovery is incomplete.',
                    {'method':'grouped-relationship-discovery','pair_limit':maximum,'entity_kind':'sheet' if sheets else 'file',
                     'project_state_fingerprint':key(sorted({r['analysis_id'] for r in registry._current(project_id)
                                                            if r['analysis_id'] and r['status']=='present'}))})
                return
            seen.add(pair)
            yield left,right


def refresh_relationships(registry, project_id, config):
    snapshot=registry.snapshot(project_id)
    files=snapshot['files']
    with registry.transaction():
        for left,right in _candidate_pairs(registry,project_id,files,config):
            base={'analysis_ids':sorted(a for a in (left['analysis_id'],right['analysis_id']) if a),
                  'file_versions':[left['version_id'],right['version_id']],
                  'relative_paths':[left['relative_path'],right['relative_path']],
                  'field_fingerprints':{left['file_id']:metadata_fingerprint(left),right['file_id']:metadata_fingerprint(right)}}
            if left['sha256'] and left['sha256']==right['sha256']:
                registry.relationship(project_id,left['file_id'],right['file_id'],'duplicate_content',
                                      {**base,'sha256':left['sha256'],'basis':'exact_source_bytes'},'high')
                registry.issue(project_id,left['file_id'],left['analysis_id'],'DUPLICATE_CONTENT',
                               'Identical bytes occur at another independently retained path.',{'other_path':right['relative_path'],'sha256':left['sha256'],'analysis_ids':base['analysis_ids']})
            same_name=_stem(left['filename'])==_stem(right['filename'])
            left_no=normalized_number(left['metadata'].get('document_number'))
            right_no=normalized_number(right['metadata'].get('document_number'))
            same_number=left_no is not None and left_no==right_no
            if {left['extension'],right['extension']} & {'dwg','dxf'} and 'pdf' in {left['extension'],right['extension']} and (same_name or same_number):
                evidence={**base,'basis':'normalized_content_identifier' if same_number else 'filename_similarity_only',
                          'document_numbers':[left_no,right_no], 'never_authorizes_export_use':True}
                registry.relationship(project_id,left['file_id'],right['file_id'],'representation_match',evidence,'medium' if same_number else 'low')
                registry.issue(project_id,left['file_id'],left['analysis_id'],'UNVERIFIED_REPRESENTATION',
                               'Possible CAD/PDF representation match requires an engineer to verify the exact files.',{'other_path':right['relative_path'],'analysis_ids':base['analysis_ids']})
            if (same_number or same_name) and left['metadata'].get('revision')!=right['metadata'].get('revision'):
                newer,basis=_newer(left,right,config.get('revision_order',[]))
                registry.relationship(project_id,left['file_id'],right['file_id'],'revision_candidate',
                    {**base,'basis':'document_number' if same_number else 'filename_similarity_only',
                     'revisions':[left['metadata'].get('revision'),right['metadata'].get('revision')],
                     'potential_newer':newer,'ordering_basis':basis,'contractual_approval':False},'medium' if same_number else 'low')
                registry.issue(project_id,left['file_id'],left['analysis_id'],'REVISION_SELECTION_REQUIRED',
                               'Multiple potential revisions retained; applicability is not automatically approved.',{'other_path':right['relative_path'],'analysis_ids':base['analysis_ids']})
        # Sheet identities are independent of container files.
        for left,right in _candidate_pairs(registry,project_id,snapshot['sheets'],config,sheets=True):
            number=normalized_number(left['metadata'].get('document_number'))
            if number and number==normalized_number(right['metadata'].get('document_number')) and left['metadata'].get('revision')!=right['metadata'].get('revision'):
                newer,basis=_newer(left,right,config.get('revision_order',[]))
                registry.relationship(project_id,left['sheet_id'],right['sheet_id'],'revision_candidate',
                    {'analysis_ids':sorted({left['analysis_id'],right['analysis_id']}),'document_number':number,
                     'pdf_pages':[left['pdf_page'],right['pdf_page']],'revisions':[left['metadata'].get('revision'),right['metadata'].get('revision')],
                     'potential_newer':newer,'ordering_basis':basis,'contractual_approval':False,
                     'field_fingerprints':{left['sheet_id']:metadata_fingerprint(left),right['sheet_id']:metadata_fingerprint(right)}},'medium')
        for file in files:
            discipline=file['metadata'].get('discipline')
            category=str(file['metadata'].get('document_type') or '').casefold()
            if discipline and any(word in category for word in ('schedule','specification')):
                target=registry.entity(project_id,'discipline',discipline,discipline)
                registry.relationship(project_id,file['file_id'],target,'discipline_association',
                      {'analysis_ids':[file['analysis_id']],'basis':file['provenance'].get('discipline',{})},'medium')
            if category in ('boq','bill of quantities'):
                target=registry.entity(project_id,'project_scope',project_id,snapshot['project']['name'])
                registry.relationship(project_id,file['file_id'],target,'scope_association',
                      {'analysis_ids':[file['analysis_id']],'basis':'file_registered_under_project_root; technical scope not verified'},'low')


def scan_project(root, db_path=None, project_id=None, config=None, skills_root=None):
    root=Path(root).resolve(strict=True)
    if not root.is_dir() or (root/MARKER).exists():
        raise ValueError('Supply an original project directory, not a marked generated output')
    config=validate_config(config)
    db=choose_database(root,db_path)
    registry=Registry(db,skills_root=skills_root)
    run_id=uuid.uuid4().hex
    counts={'processed_files':0,'unchanged_files':0,'errors':0,'discovered_files':0}
    project=None
    completed=False
    try:
        project=registry.ensure_project(root,project_id)
        pid=project['id']; config_hash=key(config); extractor_signature=signature(registry.skills_root)
        with registry.transaction():
            registry._insert('registry_scans',dict(id=run_id,project_id=pid,config_json=dump(config),config_hash=config_hash,started_at=now()))
        seen=set()
        for path,relative in discover(root,config,db):
            counts['discovered_files']+=1
            file_id=None
            try:
                with registry.transaction():
                    file_id=registry.file(pid,relative)
                seen.add(file_id)
                with registry.transaction():
                    sha,archive,stat=archive_source(path,db)
                    version=registry.register_version(pid,file_id,path,sha,archive,stat)
                analysis=key(version,config_hash,extractor_signature,relative)
                cached=registry.conn.execute('select 1 from registry_analyses where id=?',(analysis,)).fetchone()
                if cached:
                    counts['unchanged_files']+=1
                else:
                    result=extract_document(archive,config,skills_root=registry.skills_root,original_name=path.name,relative_path=relative)
                    with registry.transaction():
                        registry.record_analysis(pid,file_id,version,analysis,result,config_hash,extractor_signature)
                    counts['processed_files']+=1
                extraction_status=registry.conn.execute('select status from registry_analyses where id=?',(analysis,)).fetchone()[0]
                if extraction_status=='error': counts['errors']+=1
                with registry.transaction():
                    registry.conn.execute('''insert into registry_scan_files(run_id,file_id,version_id,analysis_id,observed_path,stat_json,status)
                                  values(?,?,?,?,?,?,?)''',(run_id,file_id,version,analysis,relative,dump(stat),'present'))
            except (OSError,ValueError,sqlite3.Error) as error:
                counts['errors']+=1
                with registry.transaction():
                    if file_id is None: file_id=registry.file(pid,relative)
                    seen.add(file_id)
                    registry.issue(pid,file_id,None,'FILE_REGISTRATION_ERROR',type(error).__name__+': '+str(error),
                                   {'method':'filesystem-registration','relative_path':relative,'run_id':run_id},'error')
                    registry.conn.execute('''insert into registry_scan_files(run_id,file_id,version_id,analysis_id,observed_path,stat_json,status)
                                  values(?,?,NULL,NULL,?,?,?)''',(run_id,file_id,relative,dump({}),'error'))
        # Only a completed traversal can establish missing/excluded paths.
        with registry.transaction():
            for previous in registry._current(pid):
                if previous['file_id'] in seen: continue
                relative=previous['observed_path']
                state='excluded' if _excluded(relative,config) else 'missing'
                registry.conn.execute('''insert into registry_scan_files(run_id,file_id,version_id,analysis_id,observed_path,stat_json,status)
                         values(?,?,?,?,?,?,?)''',(run_id,previous['file_id'],previous['version_id'],previous['analysis_id'],relative,previous['stat_json'],state))
                if state=='missing':
                    registry.issue(pid,previous['file_id'],None,'SOURCE_NOT_PRESENT',
                                   'Previously registered path is not present in the completed scan; retained evidence is not deleted.',
                                   {'method':'completed-filesystem-scan','relative_path':relative,'run_id':run_id})
        refresh_relationships(registry,pid,config)
        completed=True
    except BaseException:
        if project is not None:
            with registry.transaction():
                registry._insert('registry_scan_results',dict(run_id=run_id,status='interrupted',counters_json=dump(counts),finished_at=now()),primary='run_id')
        raise
    finally:
        if completed:
            with registry.transaction():
                registry._insert('registry_scan_results',dict(run_id=run_id,status='completed_with_errors' if counts['errors'] else 'completed',
                                 counters_json=dump(counts),finished_at=now()),primary='run_id')
        registry.close()
    reopened=Registry(db,skills_root=skills_root)
    try:
        snapshot=reopened.snapshot(project['id'])
        snapshot['database_path']=str(db)
        return snapshot
    finally:
        reopened.close()
