"""Additive document-control schema on the existing engineering SQLite database."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .common import FIELDS, LEVELS, dump, key, load_core, metadata_fingerprint, normalized_number, now, path_key, relative_key, select_fields, skills_root

SQL = '''
CREATE TABLE IF NOT EXISTS registry_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_projects(
 id TEXT PRIMARY KEY, root_key TEXT NOT NULL UNIQUE, root_path TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_entities(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), kind TEXT NOT NULL,
 ref_key TEXT NOT NULL, label TEXT, created_at TEXT NOT NULL, UNIQUE(project_id,kind,ref_key), UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_files(
 id TEXT PRIMARY KEY REFERENCES registry_entities(id), project_id TEXT NOT NULL REFERENCES registry_projects(id),
 path_key TEXT NOT NULL, relative_path TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,path_key), UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_scans(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), config_json TEXT NOT NULL,
 config_hash TEXT NOT NULL, started_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_scan_results(
 run_id TEXT PRIMARY KEY REFERENCES registry_scans(id), status TEXT NOT NULL,
 counters_json TEXT NOT NULL, finished_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_analyses(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), version_id TEXT NOT NULL REFERENCES versions(id),
 config_hash TEXT NOT NULL, signature TEXT NOT NULL, status TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registry_scan_files(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES registry_scans(id), file_id TEXT NOT NULL REFERENCES registry_files(id),
 version_id TEXT REFERENCES versions(id), analysis_id TEXT REFERENCES registry_analyses(id),
 observed_path TEXT NOT NULL, stat_json TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(run_id,file_id));
CREATE TABLE IF NOT EXISTS registry_document_sheets(
 id TEXT PRIMARY KEY REFERENCES registry_entities(id), analysis_id TEXT NOT NULL REFERENCES registry_analyses(id),
 version_id TEXT NOT NULL REFERENCES versions(id), file_id TEXT NOT NULL REFERENCES registry_files(id),
 pdf_page INTEGER NOT NULL CHECK(pdf_page>0), source_json TEXT NOT NULL, UNIQUE(analysis_id,pdf_page));
CREATE TABLE IF NOT EXISTS registry_observations(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), analysis_id TEXT NOT NULL REFERENCES registry_analyses(id),
 file_id TEXT NOT NULL REFERENCES registry_files(id), sheet_id TEXT REFERENCES registry_document_sheets(id),
 field TEXT NOT NULL, value_json TEXT NOT NULL, evidence_class TEXT NOT NULL,
 confidence TEXT NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_issues(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), file_id TEXT REFERENCES registry_files(id),
 analysis_id TEXT REFERENCES registry_analyses(id), pdf_page INTEGER, code TEXT NOT NULL,
 message TEXT NOT NULL, severity TEXT NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_revisions(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), entity_id TEXT NOT NULL REFERENCES registry_entities(id),
 file_id TEXT NOT NULL REFERENCES registry_files(id), analysis_id TEXT NOT NULL REFERENCES registry_analyses(id),
 document_number TEXT, normalized_number TEXT, revision TEXT, issue_date TEXT, issue_status TEXT,
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_relationships(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES registry_projects(id), left_entity TEXT NOT NULL,
 right_entity TEXT NOT NULL, type TEXT NOT NULL, evidence_json TEXT NOT NULL, confidence TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(project_id,left_entity) REFERENCES registry_entities(project_id,id),
 FOREIGN KEY(project_id,right_entity) REFERENCES registry_entities(project_id,id),
 CHECK(left_entity<>right_entity), UNIQUE(project_id,id));
CREATE TABLE IF NOT EXISTS registry_reviews(
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES registry_projects(id), actor TEXT NOT NULL,
 decision TEXT NOT NULL, reason TEXT NOT NULL, target_file TEXT, target_revision TEXT, target_relationship TEXT,
 target_observation TEXT, target_issue TEXT, value_json TEXT, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
 CHECK((target_file IS NOT NULL)+(target_revision IS NOT NULL)+(target_relationship IS NOT NULL)+(target_observation IS NOT NULL)+(target_issue IS NOT NULL)=1),
 FOREIGN KEY(project_id,target_file) REFERENCES registry_files(project_id,id),
 FOREIGN KEY(project_id,target_revision) REFERENCES registry_revisions(project_id,id),
 FOREIGN KEY(project_id,target_relationship) REFERENCES registry_relationships(project_id,id),
 FOREIGN KEY(project_id,target_observation) REFERENCES registry_observations(project_id,id),
 FOREIGN KEY(project_id,target_issue) REFERENCES registry_issues(project_id,id));
CREATE VIRTUAL TABLE IF NOT EXISTS registry_fts USING fts5(project_id UNINDEXED, observation_id UNINDEXED, text);
CREATE INDEX IF NOT EXISTS registry_scan_files_current ON registry_scan_files(file_id,seq);
CREATE INDEX IF NOT EXISTS registry_analysis_version ON registry_analyses(version_id,config_hash);
CREATE INDEX IF NOT EXISTS registry_observation_analysis ON registry_observations(analysis_id,sheet_id,field);
CREATE INDEX IF NOT EXISTS registry_revision_number ON registry_revisions(project_id,normalized_number);
CREATE INDEX IF NOT EXISTS registry_issues_project ON registry_issues(project_id,analysis_id);
CREATE INDEX IF NOT EXISTS registry_reviews_project ON registry_reviews(project_id,id);
'''

TABLES = ('registry_migrations', 'registry_projects', 'registry_entities', 'registry_files', 'registry_scans',
          'registry_scan_results', 'registry_analyses', 'registry_scan_files', 'registry_document_sheets',
          'registry_observations', 'registry_issues', 'registry_revisions', 'registry_relationships', 'registry_reviews')


class Registry:
    def __init__(self, db_path, skills_root=None):
        self.skills_root = globals()['skills_root'](skills_root)
        self.core = load_core(str(self.skills_root))
        self.store = self.core.Store(db_path)
        self.path, self.conn = self.store.path, self.store.conn
        self.conn.execute('PRAGMA busy_timeout=30000')
        try:
            if self.conn.execute("select 1 from sqlite_master where name='registry_migrations'").fetchone():
                versions = [r[0] for r in self.conn.execute('select version from registry_migrations')]
                if versions != [1]:
                    raise ValueError('Unsupported registry migration version; no automatic destructive migration')
            self.conn.executescript(SQL)
            if not self.conn.execute('select 1 from registry_migrations').fetchone():
                self.conn.execute('insert into registry_migrations values(1,?,?)',
                                  (now(), 'Add project registry using existing engineering versions and archive'))
            for table in TABLES:
                pk = 'version' if table == 'registry_migrations' else 'run_id' if table == 'registry_scan_results' else 'seq' if table == 'registry_scan_files' else 'id'
                for operation in ('UPDATE', 'DELETE'):
                    self.conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_immutable_{operation}
                      BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable registry history'); END''')
                self.conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_immutable_INSERT BEFORE INSERT ON {table}
                  WHEN EXISTS(SELECT 1 FROM {table} WHERE {pk}=NEW.{pk})
                  BEGIN SELECT RAISE(ABORT,'Registry history cannot be replaced'); END''')
            self.conn.commit()
        except Exception:
            self.close()
            raise

    def close(self):
        self.store.close()

    @contextmanager
    def transaction(self):
        outer = self.conn.in_transaction
        if not outer:
            self.conn.execute('BEGIN IMMEDIATE')
        try:
            yield
            if not outer:
                self.conn.commit()
        except BaseException:
            if not outer:
                self.conn.rollback()
            raise

    def _insert(self, table, values, primary='id'):
        # All table/column names here are internal constants, never SQL from project files.
        if self.conn.execute(f'select 1 from {table} where {primary}=?', (values[primary],)).fetchone():
            return False
        columns = ','.join(values)
        self.conn.execute(f'insert into {table}({columns}) values({",".join("?" for _ in values)})', tuple(values.values()))
        return True

    def ensure_project(self, root, project_id=None):
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Project root must be a directory')
        root_identity = path_key(root)
        existing = self.conn.execute('select * from registry_projects where root_key=?', (root_identity,)).fetchone()
        if existing:
            if project_id is not None and project_id != existing['id']:
                raise ValueError('This root already belongs to a different project ID')
            return {'id': existing['id'], 'root': existing['root_path'], 'name': existing['name']}
        project_id = project_id or 'project-' + key(root_identity)[:20]
        if not isinstance(project_id, str) or not project_id.strip() or len(project_id) > 200:
            raise ValueError('Project ID must be a nonempty short string')
        if self.conn.execute('select 1 from registry_projects where id=?', (project_id,)).fetchone():
            raise ValueError('Project ID already belongs to another root')
        with self.transaction():
            self._insert('registry_projects', dict(id=project_id, root_key=root_identity, root_path=str(root), name=root.name, created_at=now()))
        return {'id': project_id, 'root': str(root), 'name': root.name}

    def entity(self, project_id, kind, reference, label=None):
        identity = key(project_id, kind, reference)
        self._insert('registry_entities', dict(id=identity, project_id=project_id, kind=kind,
                                              ref_key=reference, label=label, created_at=now()))
        return identity

    def file(self, project_id, relative):
        identity = self.entity(project_id, 'file', relative_key(relative), relative)
        self._insert('registry_files', dict(id=identity, project_id=project_id, path_key=relative_key(relative),
                                            relative_path=relative, created_at=now()))
        return identity

    def register_version(self, project_id, file_id, path, sha256, archive, stat):
        logical = 'registry:' + project_id + ':' + file_id
        version = key(logical, None, sha256)
        metadata = dict(path=str(Path(path).resolve()), filename=Path(path).name, sha256=sha256,
                        document_id=None, revision=None, media_type=Path(path).suffix.lower().lstrip('.'),
                        metadata=dict(project_id=project_id, file_id=file_id, stat=stat, file_version_not_contractual_revision=True))
        self._insert('versions', dict(id=version, logical_key=logical, document_id=None, revision=None,
                                     source_path=str(Path(path).resolve()), filename=Path(path).name, sha256=sha256,
                                     archive_path=str(archive), metadata_json=dump(metadata), created_at=now()))
        return version

    def issue(self, project_id, file_id, analysis_id, code, message, source=None, severity='review'):
        source = source or {}
        identity_source = {k:v for k,v in source.items() if k!='run_id'} if code in ('SOURCE_NOT_PRESENT','FILE_REGISTRATION_ERROR') else source
        identity = key(project_id, file_id, analysis_id, code, message, identity_source)
        self._insert('registry_issues', dict(id=identity, project_id=project_id, file_id=file_id, analysis_id=analysis_id,
                    pdf_page=source.get('pdf_page'), code=str(code), message=str(message), severity=severity,
                    source_json=dump(source), created_at=now()))
        return identity

    def record_analysis(self, project_id, file_id, version_id, analysis_id, result, config_hash, signature):
        if result.get('status') not in ('registered','registered_with_issues','registered_metadata_extraction_pending','error'):
            raise ValueError('Invalid metadata extraction status')
        self._insert('registry_analyses', dict(id=analysis_id, project_id=project_id, version_id=version_id,
                    config_hash=config_hash, signature=signature, status=result['status'],
                    metadata_json=dump(result.get('metadata', {})), created_at=now()))
        count = result.get('metadata', {}).get('page_count')
        groups = [(None, result.get('observations', []))]
        for sheet in result.get('sheets', []):
            page = sheet.get('pdf_page')
            if type(page) is not int or page < 1 or (type(count) is int and page > count):
                raise ValueError('Invalid actual PDF sheet page')
            sid = self.entity(project_id, 'sheet', key(analysis_id, page), 'PDF page ' + str(page))
            self._insert('registry_document_sheets', dict(id=sid, analysis_id=analysis_id, version_id=version_id,
                        file_id=file_id, pdf_page=page, source_json=dump(sheet.get('source', {}))))
            groups.append((sid, sheet.get('observations', [])))
        for sheet_id, observations in groups:
            for observation in observations:
                field, source = observation.get('field'), observation.get('source', {})
                level = observation.get('evidence_class')
                if not isinstance(field, str) or level not in LEVELS or not isinstance(source, dict) or not source.get('method'):
                    raise ValueError('Metadata observation lacks valid field/basis/source')
                page = source.get('pdf_page')
                if page is not None and (type(page) is not int or page < 1 or (type(count) is int and page > count)):
                    raise ValueError('Observation PDF page is not an actual source page')
                if sheet_id is not None:
                    actual_page = self.conn.execute('select pdf_page from registry_document_sheets where id=?', (sheet_id,)).fetchone()[0]
                    if level == 'content_extracted' and page != actual_page:
                        raise ValueError('Content sheet observation must reference its actual PDF page')
                value = observation.get('value')
                identity = key(analysis_id, sheet_id, field, value, level, source)
                confidence = observation.get('confidence', 'unknown')
                if confidence not in ('high','medium','low','unknown'):
                    raise ValueError('Confidence is categorical, not an invented accuracy score')
                inserted = self._insert('registry_observations', dict(id=identity, project_id=project_id,
                            analysis_id=analysis_id, file_id=file_id, sheet_id=sheet_id, field=field,
                            value_json=dump(value), evidence_class=level, confidence=confidence,
                            source_json=dump(source), created_at=now()))
                if inserted:
                    self.conn.execute('insert into registry_fts(project_id,observation_id,text) values(?,?,?)',
                                      (project_id, identity, field + ' ' + dump(value) + ' ' + dump(source)))
        for issue in result.get('issues', []):
            self.issue(project_id, file_id, analysis_id, issue.get('code','EXTRACTION_REVIEW'),
                       issue.get('message','Metadata needs review'), issue.get('source'), issue.get('severity','review'))

    def _reviews(self, project_id):
        result = []
        for row in self.conn.execute('select * from registry_reviews where project_id=? order by id', (project_id,)):
            item = dict(row)
            item['value'] = json.loads(item.pop('value_json')) if item['value_json'] is not None else None
            item['target_snapshot'] = json.loads(item.pop('snapshot_json'))
            item['review_id'] = item['id']
            item['target_type'] = next(t for t in ('file','revision','relationship','observation','issue') if item.get('target_'+t))
            item['target_id'] = item['target_'+item['target_type']]
            result.append(item)
        return result

    def _observations(self, project_id, analysis_ids):
        output = []
        for row in self.conn.execute('select * from registry_observations where project_id=? order by created_at,id', (project_id,)):
            if row['analysis_id'] not in analysis_ids:
                continue
            item = dict(row)
            item['observation_id'] = item.pop('id')
            item['value'] = json.loads(item.pop('value_json'))
            item['source'] = json.loads(item.pop('source_json'))
            item['review_status'] = 'unreviewed'
            output.append(item)
        return output

    def _current(self, project_id):
        return self.conn.execute('''select f.id as file_id,f.relative_path,s.*,v.filename,v.sha256,v.archive_path,
                a.status as extraction_status,a.metadata_json as analysis_metadata
             from registry_files f join registry_scan_files s on s.seq=(select max(s2.seq) from registry_scan_files s2 where s2.file_id=f.id)
             left join versions v on v.id=s.version_id left join registry_analyses a on a.id=s.analysis_id
             where f.project_id=? order by s.observed_path''', (project_id,)).fetchall()

    def _revision_rows(self, project_id, items, reviews):
        revisions = []
        for item in items:
            metadata = item['metadata']
            provenance = {f:item['provenance'].get(f) for f in ('document_number','revision','revision_date','issue_status')}
            identity = key(item.get('sheet_id') or item['file_id'], item['analysis_id'], metadata.get('document_number'),
                           metadata.get('revision'), metadata.get('revision_date'), metadata.get('issue_status'), provenance)
            if not metadata.get('document_number') and not metadata.get('revision'):
                continue
            with self.transaction():
                self._insert('registry_revisions', dict(id=identity, project_id=project_id,
                    entity_id=item.get('sheet_id') or item['file_id'], file_id=item['file_id'], analysis_id=item['analysis_id'],
                    document_number=metadata.get('document_number'), normalized_number=normalized_number(metadata.get('document_number')),
                    revision=metadata.get('revision'), issue_date=metadata.get('revision_date'), issue_status=metadata.get('issue_status'),
                    evidence_json=dump(provenance), created_at=now()))
            revisions.append(identity)
        return set(revisions)

    def _relation_status(self, relationship, reviews, current_analyses, fingerprints=None):
        evidence = json.loads(relationship['evidence_json'])
        if any(a not in current_analyses for a in evidence.get('analysis_ids', [])):
            return 'invalidated'
        if fingerprints is not None and any(fingerprints.get(entity)!=value for entity,value in evidence.get('field_fingerprints',{}).items()):
            return 'invalidated'
        decisions = [r for r in reviews if r['target_relationship'] == relationship['id']]
        if not decisions:
            return 'proposed'
        return 'confirmed' if decisions[-1]['decision'] == 'confirm_relationship' else 'rejected'

    def snapshot(self, project_id, history=False):
        row = self.conn.execute('select * from registry_projects where id=?', (project_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown project ID')
        project = {'id':row['id'], 'root':row['root_path'], 'name':row['name']}
        current = self._current(project_id)
        present = [r for r in current if r['status'] not in ('missing','excluded')]
        active_analyses = {r['analysis_id'] for r in present if r['analysis_id']}
        analyses = set(active_analyses)
        if history:
            analyses = {r[0] for r in self.conn.execute('select id from registry_analyses where project_id=?', (project_id,))}
        reviews = self._reviews(project_id)
        observations = self._observations(project_id, analyses)
        files, sheets = [], []
        for record in present:
            stat = json.loads(record['stat_json'])
            observed = [o for o in observations if o['analysis_id'] == record['analysis_id'] and o['sheet_id'] is None]
            metadata, provenance = select_fields(observed, reviews)
            item = dict(file_id=record['file_id'], version_id=record['version_id'], analysis_id=record['analysis_id'],
                        relative_path=record['observed_path'], filename=Path(record['observed_path']).name,
                        extension=Path(record['observed_path']).suffix.lower().lstrip('.'), size=stat.get('size'),
                        modified_at=stat.get('modified_at'), sha256=record['sha256'], archive_path=record['archive_path'],
                        registration_status=record['extraction_status'] or record['status'], metadata=metadata, provenance=provenance,
                        classification_category=metadata.get('document_type') or 'Unclassified Documents',
                        registry_status='unreviewed', sheet_count=0)
            identity_reviews = [r for r in reviews if r['target_file']==item['file_id'] and r['target_snapshot'].get('version_id')==item['version_id']]
            if identity_reviews:
                item['registry_status'] = 'identity_confirmed'
            for page in self.conn.execute('select * from registry_document_sheets where analysis_id=? order by pdf_page', (record['analysis_id'],)):
                obs = [o for o in observations if o['sheet_id']==page['id']]
                fields, sources = select_fields(obs, reviews)
                sheets.append(dict(sheet_id=page['id'], file_id=item['file_id'], version_id=item['version_id'], analysis_id=item['analysis_id'],
                                   relative_path=item['relative_path'], pdf_page=page['pdf_page'], metadata=fields, provenance=sources,
                                   registry_status='unreviewed'))
                item['sheet_count'] += 1
            files.append(item)
        # Derivations retain old candidates; only exact current observation/review fingerprints are current.
        current_revisions = self._revision_rows(project_id, sheets + [f for f in files if not f['sheet_count']], reviews)
        revisions = []
        for revision in self.conn.execute('select * from registry_revisions where project_id=? order by created_at,id', (project_id,)):
            is_current = revision['id'] in current_revisions
            if not history and not is_current:
                continue
            entity = self.conn.execute('select kind from registry_entities where id=?', (revision['entity_id'],)).fetchone()[0]
            relevant = [r for r in reviews if r['target_revision']==revision['id']]
            status = ('applicable' if relevant[-1]['decision']=='approve_applicability' else 'superseded') if relevant else 'unreviewed'
            item = dict(revision_id=revision['id'], entity_id=revision['entity_id'], entity_kind=entity,
                        file_id=revision['file_id'], analysis_id=revision['analysis_id'],
                        sheet_id=revision['entity_id'] if entity=='sheet' else None,
                        document_number=revision['document_number'], revision=revision['revision'],
                        issue_date=revision['issue_date'], issue_status=revision['issue_status'],
                        verification_status=status, is_current=is_current,
                        evidence=json.loads(revision['evidence_json']))
            versions = self.conn.execute('select version_id from registry_analyses where id=?', (revision['analysis_id'],)).fetchone()
            item['version_id'] = versions[0]
            revisions.append(item)
            for target in sheets if entity=='sheet' else files:
                if (target.get('sheet_id') or target['file_id'])==revision['entity_id'] and is_current:
                    target['registry_status'] = status if relevant else target['registry_status']
        endpoints = {f['file_id']:{'kind':'file','id':f['file_id'],'relative_path':f['relative_path'],'pdf_page':None,
                                  'document_number':f['metadata'].get('document_number'),'revision':f['metadata'].get('revision')} for f in files}
        endpoints.update({s['sheet_id']:{'kind':'sheet','id':s['sheet_id'],'relative_path':s['relative_path'],'pdf_page':s['pdf_page'],
                                       'document_number':s['metadata'].get('document_number'),'revision':s['metadata'].get('revision')} for s in sheets})
        fingerprints={(item.get('sheet_id') or item['file_id']):metadata_fingerprint(item) for item in files+sheets}
        relationships = []
        for relationship in self.conn.execute('select * from registry_relationships where project_id=? order by created_at,id', (project_id,)):
            def endpoint(identity):
                if identity in endpoints:
                    return endpoints[identity]
                target = self.conn.execute('select kind,label from registry_entities where id=?', (identity,)).fetchone()
                return {'kind':target['kind'],'id':identity,'label':target['label'],'relative_path':None,'pdf_page':None}
            relationships.append(dict(relationship_id=relationship['id'],type=relationship['type'],
                        left=endpoint(relationship['left_entity']),right=endpoint(relationship['right_entity']),
                        evidence=json.loads(relationship['evidence_json']), confidence=relationship['confidence'],
                        verification_status=self._relation_status(relationship,reviews,active_analyses,fingerprints)))
        issues = []
        by_file = {f['file_id']:f for f in files}
        for issue in self.conn.execute('select * from registry_issues where project_id=? order by created_at,id', (project_id,)):
            if not history and issue['analysis_id'] is not None and issue['analysis_id'] not in analyses:
                continue
            decisions = [r for r in reviews if r['target_issue']==issue['id']]
            status = 'resolved' if decisions and decisions[-1]['decision']=='resolve_issue' else 'open'
            source = json.loads(issue['source_json'])
            if any(a not in active_analyses for a in source.get('analysis_ids',[])):
                status = 'invalidated'
            if issue['code']=='SOURCE_NOT_PRESENT' and issue['file_id'] in by_file:
                status = 'invalidated'
            if issue['code']=='FILE_REGISTRATION_ERROR' and by_file.get(issue['file_id'],{}).get('registration_status')!='error':
                status = 'invalidated'
            if source.get('project_state_fingerprint') and source['project_state_fingerprint']!=key(sorted(active_analyses)):
                status='invalidated'
            issues.append(dict(issue_id=issue['id'], code=issue['code'],message=issue['message'],severity=issue['severity'],status=status,
                        file_id=issue['file_id'],analysis_id=issue['analysis_id'],relative_path=by_file.get(issue['file_id'],{}).get('relative_path'),
                        pdf_page=issue['pdf_page'],source=source))
        scan = self.conn.execute('''select s.*,r.status,r.counters_json,r.finished_at from registry_scans s
                   left join registry_scan_results r on r.run_id=s.id where s.project_id=? order by s.started_at desc,s.id desc limit 1''', (project_id,)).fetchone()
        scan_data = {'run_id':scan['id'],'status':scan['status'] or 'interrupted_or_running',
                     'counters':json.loads(scan['counters_json']) if scan['counters_json'] else {},
                     'started_at':scan['started_at'],'finished_at':scan['finished_at']} if scan else {}
        counters = scan_data.get('counters', {})
        summary = dict(file_count=len(files),sheet_count=len(sheets), processed_files=counters.get('processed_files',0),
                       unchanged_files=counters.get('unchanged_files',0), errors=counters.get('errors',0),
                       classified_documents=sum(bool(f['metadata'].get('document_type')) and str(f['metadata']['document_type']).lower() not in ('unclassified','unclassified documents') for f in files),
                       review_requirements=sum(i['status']=='open' for i in issues), relationship_count=len(relationships))
        return dict(project=project,generated_at=now(),files=files,sheets=sheets,relationships=relationships,
                    issues=issues,observations=observations,reviews=reviews,revisions=revisions,summary=summary,scan=scan_data)

    def relationship(self, project_id, left, right, kind, evidence, confidence):
        if left==right:
            raise ValueError('A document cannot be related to itself')
        for identity in (left,right):
            if not self.conn.execute('select 1 from registry_entities where id=? and project_id=?', (identity,project_id)).fetchone():
                raise ValueError('Relationship endpoint is outside the project')
        identity = key(project_id,left,right,kind,evidence)
        self._insert('registry_relationships',dict(id=identity,project_id=project_id,left_entity=left,right_entity=right,
                                                type=kind,evidence_json=dump(evidence),confidence=confidence,created_at=now()))
        return identity

    def review(self, project_id, target_type, target_id, decision, actor, reason, value=None):
        if not isinstance(actor,str) or not actor.strip() or not isinstance(reason,str) or not reason.strip():
            raise ValueError('Actual actor and reason are required')
        allowed = {'file':('confirm_identity',),'revision':('approve_applicability','supersede'),
                   'relationship':('confirm_relationship','reject_relationship'),
                   'observation':('correct_metadata',),'issue':('resolve_issue','reopen_issue')}
        tables = {'file':'registry_files','revision':'registry_revisions','relationship':'registry_relationships',
                  'observation':'registry_observations','issue':'registry_issues'}
        if target_type not in allowed or decision not in allowed[target_type]:
            raise ValueError('Decision is incompatible with its target type')
        target = self.conn.execute('select * from '+tables[target_type]+' where id=? and project_id=?', (target_id,project_id)).fetchone()
        if target is None:
            raise ValueError('Review target does not exist in this project')
        snapshot = {'target':dict(target)}
        if target_type=='file':
            current = next((r for r in self._current(project_id) if r['file_id']==target_id),None)
            snapshot['version_id'] = current['version_id'] if current else None
        if target_type=='revision' and (not target['document_number'] or not target['revision']):
            raise ValueError('Confirm/correct the document identity and revision before applicability review')
        if target_type=='relationship':
            projected=next((r for r in self.snapshot(project_id)['relationships'] if r['relationship_id']==target_id),None)
            if projected is None or projected['verification_status']=='invalidated':
                raise ValueError('Relationship refers to superseded file evidence; review a current proposal')
            if any(v is None for v in json.loads(target['evidence_json']).get('file_versions',[])):
                raise ValueError('Relationship has no complete registered source-byte versions')
        if target_type=='observation':
            if target['field'] not in FIELDS or isinstance(value,(list,dict)):
                raise ValueError('Metadata correction must be a scalar value for a supported field')
        elif value is not None:
            raise ValueError('Only metadata correction accepts a replacement value')
        columns = {f'target_{name}':None for name in allowed}
        columns['target_'+target_type] = target_id
        values = dict(project_id=project_id,actor=actor,decision=decision,reason=reason,**columns,
                      value_json=dump(value),snapshot_json=dump(snapshot),created_at=now())
        with self.transaction():
            cursor=self.conn.execute('insert into registry_reviews('+','.join(values)+') values('+','.join('?' for _ in values)+')',tuple(values.values()))
            if target_type=='observation':
                self.conn.execute('insert into registry_fts(project_id,observation_id,text) values(?,?,?)',
                                  (project_id,target_id,'engineering review '+target['field']+' '+dump(value)))
        return {'review_id':cursor.lastrowid,'project_id':project_id,'target_type':target_type,'target_id':target_id,'decision':decision}

    def search(self, project_id, query, limit=100, history=False):
        if not self.conn.execute('select 1 from registry_projects where id=?',(project_id,)).fetchone():
            raise ValueError('Unknown project ID')
        if not isinstance(query,str) or len(query)>1000 or type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Query/limit invalid')
        if not query.strip():
            return []
        literal='"'+query.replace('"','""')+'"'
        sql='''select distinct o.* from registry_fts f join registry_observations o on o.id=f.observation_id
               where registry_fts match ? and f.project_id=?'''
        if not history:
            sql+=''' and o.analysis_id in (select s.analysis_id from registry_scan_files s
                   where s.seq=(select max(c.seq) from registry_scan_files c where c.file_id=s.file_id) and s.status='present')'''
        rows=self.conn.execute(sql+' limit ?',(literal,project_id,limit)).fetchall()
        corrections={r['target_observation']:r for r in self._reviews(project_id) if r['decision']=='correct_metadata'}
        return [dict(observation_id=r['id'],file_id=r['file_id'],analysis_id=r['analysis_id'],sheet_id=r['sheet_id'],
                     field=r['field'],value=json.loads(r['value_json']),source=json.loads(r['source_json']),
                     current_value=corrections[r['id']]['value'] if r['id'] in corrections else json.loads(r['value_json']),
                     review_id=corrections[r['id']]['id'] if r['id'] in corrections else None,
                     evidence_class=r['evidence_class'],confidence=r['confidence'],
                     review_status='reviewed' if r['id'] in corrections else 'unreviewed') for r in rows]
