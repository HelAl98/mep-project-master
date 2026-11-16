"""P1-02: deterministic projections of existing evidence, with no storage constructors."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .common import HOME, now
from .memory import connect


CONTRACT = 'mep-evidence-reader/1'


def decoded(value, default=None):
    if value is None:
        return {} if default is None else default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return {'unparsed_saved_value': value, 'status': 'UNKNOWN'}


class EvidenceReader:
    """One read transaction per context. Original documents are never opened.

    Pass the existing master config (or source_currency.load_config(path)).
    Pagination is independent per profile section. History is opt-in.
    """

    def __init__(self, cfg, currency_snapshot=None):
        self.cfg = cfg
        self.conn = connect(cfg, writable=False)
        self.closed = False
        try:
            self.conn.execute('BEGIN')
            self.schema = {r['name']: {c['name'] for c in self.conn.execute(
                'PRAGMA table_info("' + r['name'].replace('"', '""') + '")')}
                for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION,
                       sqlite3.SQLITE_RECURSIVE}
            self.conn.set_authorizer(lambda action, a, b, db, trigger:
                                     sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
            self.snapshot = None
            self.currency_sources = {}
            self.currency_nodes = {}
            self.snapshot_info = {'status': 'NOT_REQUESTED', 'source_currency': 'UNKNOWN', 'dependency_impact': 'UNKNOWN'}
            if currency_snapshot:
                path = Path(currency_snapshot).resolve(strict=True)
                if path.stat().st_size > 64 * 1024 * 1024:
                    raise ValueError('Currency snapshot exceeds 64 MiB reader limit')
                raw = path.read_bytes()
                snap = json.loads(raw)
                if snap.get('schema_version') != 'mep-source-currency/1' or snap.get('project_id') != cfg['project_id']:
                    raise ValueError('Incompatible currency snapshot schema/project')
                if not isinstance(snap.get('sources'), list) or not isinstance(snap.get('dependencies'), list):
                    raise ValueError('Malformed currency snapshot collections')
                self.snapshot = snap
                self.currency_sources = {s['file_id']: s for s in snap['sources']}
                self.currency_nodes = {n['node_id']: n for n in snap['dependencies']}
                self.snapshot_info = {'status': 'EXPLICIT_SAVED_SNAPSHOT_NOT_LIVE_VERIFICATION', 'path': str(path),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'assessed_at': snap.get('assessed_at'),
                    'database_at_assessment': snap.get('database'), 'limits': snap.get('artifact_scan_limits'),
                    'limitations': snap.get('limitations'), 'live_source_rehash_performed': False}
        except BaseException:
            self.conn.close()
            raise

    def close(self):
        if not self.closed:
            self.conn.rollback()
            self.conn.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def has(self, table, *columns):
        return table in self.schema and set(columns) <= self.schema[table]

    def envelope(self, operation, **data):
        return {'schema_version': CONTRACT, 'project_id': self.cfg['project_id'], 'operation': operation,
                'read_at': now(), 'database': str(self.cfg['database']), 'database_access': 'mode=ro; query_only; authorizer; read transaction',
                'currency_assessment': self.snapshot_info, 'engineering_approval_created': False, **data}

    @staticmethod
    def bounds(limit, offset):
        if isinstance(limit, bool) or isinstance(offset, bool) or not isinstance(limit, int) or not isinstance(offset, int) or not 1 <= limit <= 200 or offset < 0:
            raise ValueError('limit must be 1..200; offset must be a nonnegative integer')

    def page(self, sql=None, args=(), transform=lambda r: r, limit=25, offset=0, reason=None):
        self.bounds(limit, offset)
        if sql is None:
            return {'status': 'UNSUPPORTED', 'reason': reason, 'items': [], 'total': None,
                    'limit': limit, 'offset': offset, 'next_offset': None}
        total = self.conn.execute('SELECT count(*) FROM (' + sql + ')', args).fetchone()[0]
        rows = self.conn.execute(sql + ' LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
        return {'status': 'AVAILABLE' if total else 'NO_RECORDED_EVIDENCE', 'items': [transform(dict(r)) for r in rows],
                'total': total, 'limit': limit, 'offset': offset,
                'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def heads(self):
        if not self.has('registry_scan_files', 'file_id', 'seq', 'version_id', 'analysis_id', 'status'):
            return None
        return '''SELECT f.id file_id,f.relative_path,s.version_id,s.analysis_id,s.status FROM registry_files f
          JOIN registry_scan_files s ON s.file_id=f.id WHERE f.project_id=:project AND
          s.seq=(SELECT max(s2.seq) FROM registry_scan_files s2 WHERE s2.file_id=f.id)'''

    def occurrence_basis(self, history=False):
        required = {'eq_occurrences': ('id','project_id','import_id','original_tag','normalized_tag','category_id','source_json','data_json','raw_json','identity_kind'),
                    'eq_imports': ('id','project_id','file_id','analysis_id','version_id','slot','role')}
        if any(not self.has(t, *cols) for t, cols in required.items()) or not self.heads():
            return None
        # Same file/slot and current registry analysis as the existing matcher projection.
        return '''WITH heads AS (''' + self.heads() + '''), candidate_imports AS (
          SELECT i.rowid import_sequence,i.* FROM eq_imports i JOIN heads h ON h.file_id=i.file_id
          AND h.analysis_id=i.analysis_id AND h.version_id=i.version_id
          WHERE i.project_id=:project AND h.status NOT IN ('missing','excluded','error')),
          active_imports AS (SELECT i.id FROM candidate_imports i WHERE NOT EXISTS
          (SELECT 1 FROM candidate_imports n WHERE n.file_id=i.file_id AND n.slot=i.slot AND n.import_sequence>i.import_sequence))
          SELECT o.*,i.file_id,i.version_id,i.analysis_id,i.role,i.slot,
          CASE WHEN o.import_id IN (SELECT id FROM active_imports) THEN 1 ELSE 0 END is_active
          FROM eq_occurrences o JOIN eq_imports i ON i.id=o.import_id AND i.project_id=o.project_id
          WHERE o.project_id=:project''' + ('' if history else ' AND o.import_id IN (SELECT id FROM active_imports)')

    def profiles_sql(self, history=False):
        table = 'uc_profiles' if history else 'uc_equipment'
        if not self.has(table, 'id','run_id','normalized_tag','family','identity_kind') or not self.has('uc_runs','id','project_id'):
            return None
        return 'SELECT p.* FROM ' + table + ' p JOIN uc_runs r ON r.id=p.run_id WHERE r.project_id=:project'

    def selection(self, reference, history=False):
        base = self.occurrence_basis(history)
        if base is None:
            return None
        profiles = self.profiles_sql(history)
        relation = ''
        if profiles and self.has('uc_observations','profile_id','occurrence_id'):
            relation += ''' OR o.id IN (SELECT l.occurrence_id FROM uc_observations l JOIN (''' + profiles + ''') p ON p.id=l.profile_id
                       WHERE p.id=:reference OR p.normalized_tag COLLATE NOCASE=:reference)'''
        if self.has('eq_entity_sources','entity_id','occurrence_id','project_id'):
            relation += ' OR o.id IN (SELECT occurrence_id FROM eq_entity_sources WHERE entity_id=:reference AND project_id=:project)'
        return '''SELECT o.* FROM (''' + base + ''') o WHERE (o.id=:reference OR o.original_tag COLLATE NOCASE=:reference
                  OR o.normalized_tag COLLATE NOCASE=:reference''' + relation + ')'

    def params(self, reference=None):
        return {'project': self.cfg['project_id'], 'reference': reference}

    def paged(self, sql, args, transform, limit, offset, reason):
        # Named SQL binds plus positional LIMIT cannot be mixed. Bind pagination by name.
        self.bounds(limit, offset)
        if sql is None:
            return self.page(limit=limit, offset=offset, reason=reason)
        total = self.conn.execute('SELECT count(*) FROM (' + sql + ')', args).fetchone()[0]
        rows = self.conn.execute(sql + ' LIMIT :page_limit OFFSET :page_offset',
                                 {**args, 'page_limit': limit, 'page_offset': offset}).fetchall()
        return {'status': 'AVAILABLE' if total else 'NO_RECORDED_EVIDENCE', 'items': [transform(dict(r)) for r in rows],
                'total': total, 'limit': limit, 'offset': offset,
                'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def row(self, table, identity):
        if not identity or not self.has(table, 'id'):
            return None
        sql = 'SELECT * FROM "' + table + '" WHERE id=?'
        args = [identity]
        if self.has(table, 'project_id'):
            sql += ' AND project_id=?'; args.append(self.cfg['project_id'])
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def version_identity(self, version_id):
        v = self.row('versions', version_id)
        if not v:
            return None
        return {k: v.get(k) for k in ('id','filename','source_path','sha256','archive_path','document_id','revision')}

    def provenance(self, table, record, source=None, file_id=None, version_id=None, relationship=None, artifacts=None):
        source = source if isinstance(source, dict) else {}
        file_id = file_id or source.get('file_id') or source.get('original_file_id')
        version_id = version_id or source.get('version_id') or record.get('version_id')
        version = self.row('versions', version_id)
        metadata = decoded(version.get('metadata_json')) if version else {}
        supplied = metadata.get('metadata', {}).get('supplied_metadata', {}) if isinstance(metadata.get('metadata'), dict) else {}
        supplied_original = supplied.get('original_source', {})
        file_id = file_id or supplied_original.get('file_id') or metadata.get('metadata', {}).get('file_id')
        original = None
        if file_id and self.has('registry_files','id','project_id'):
            registered = self.row('registry_files', file_id)
            if registered:
                # Use the explicitly cited version, not today's registry head, for historical evidence.
                cited_hash = source.get('original_sha256') or source.get('sha256') or supplied_original.get('sha256')
                if version and not supplied_original:
                    cited_hash = cited_hash or version.get('sha256')
                if cited_hash and self.has('versions','logical_key','sha256'):
                    found = self.conn.execute('SELECT id FROM versions WHERE logical_key=? AND sha256=? ORDER BY rowid DESC LIMIT 1',
                        ('registry:' + self.cfg['project_id'] + ':' + file_id, cited_hash)).fetchone()
                    original = self.version_identity(found[0]) if found else None
                if original is None:
                    original = {'id': None, 'sha256': cited_hash, 'source_path': source.get('original_path') or supplied_original.get('path'),
                                'revision': None, 'status': 'UNKNOWN_ORIGINAL_VERSION'}
                original.update(file_id=file_id, relative_path=registered.get('relative_path'))
        derived = self.version_identity(version_id) if supplied_original else None
        if supplied_original and original is None:
            original = {'file_id': supplied_original.get('file_id'), 'sha256': supplied_original.get('sha256'),
                        'source_path': supplied_original.get('path'), 'id': None, 'status': 'UNKNOWN_REGISTRY_LINK'}
        currency, impact = 'UNKNOWN', 'UNKNOWN'
        assessed = self.currency_sources.get(file_id)
        currency_reason = 'no_explicit_snapshot_or_original_identity'
        if assessed and original and original.get('id') and original.get('sha256') == assessed.get('recorded_sha256'):
            # Snapshot source identity must still match the current registry head; no source rehash here.
            head = self.conn.execute('SELECT version_id FROM (' + self.heads() + ') WHERE file_id=:file_id',
                                     {'project': self.cfg['project_id'], 'file_id': file_id}).fetchone() if self.heads() else None
            current = self.version_identity(head[0]) if head else None
            if current and current.get('sha256') == assessed.get('recorded_sha256'):
                currency = assessed.get('currency', 'UNKNOWN'); currency_reason = 'saved_assessment_only_not_live_bytes'
            else:
                currency_reason = 'snapshot_registry_basis_mismatch'
        kinds = {'eq_occurrences':'equipment_observation','eq_parameters':'equipment_parameter','records':'extracted_record',
                 'uc_profiles':'consolidated_profile','uc_context':'consolidated_context','uc_fields':'consolidated_parameter',
                 'uc_findings':'consolidated_finding','versions':'version'}
        node = self.currency_nodes.get(kinds.get(table, table) + ':' + str(record.get('id')))
        if node and original and original.get('id') and currency_reason != 'snapshot_registry_basis_mismatch':
            impact = node.get('impact', 'UNKNOWN')
        loc = {k: source.get(k) for k in ('pdf_page','printed_page','pdf_page_label','spec_section','clause','paragraph',
               'sheet','row','cell','handle','layer','coordinates','bbox','drawing_number','document_revision')}
        return {'database_record': {'table': table, 'id': record.get('id'), 'version_id': version_id},
                'original_source': original, 'derived_document': derived,
                'extracted_evidence_id': record.get('core_record_id') or (record.get('id') if table == 'records' else None),
                'source_locator': loc, 'recorded_source': source, 'derived_artifacts': artifacts,
                'equipment_relationship': relationship, 'lineage_status': 'RECORDED' if original and original.get('id') else 'UNKNOWN',
                'currency': {'source_currency': currency, 'dependency_impact': impact, 'basis': currency_reason}}

    def reviews(self, kind, identity):
        if not self.has('eq_reviews','project_id','target_kind','target_id','decision'):
            return {'status': 'UNKNOWN', 'latest_event': None}
        row = self.conn.execute('SELECT * FROM eq_reviews WHERE project_id=? AND target_kind=? AND target_id=? ORDER BY rowid DESC LIMIT 1',
                                (self.cfg['project_id'],kind,identity)).fetchone()
        return {'status': 'RECORDED_DECISION_REQUIRES_BASIS_REVALIDATION' if row else 'UNREVIEWED',
                'latest_event': dict(row) if row else None, 'approval_inferred': False}

    def observation(self, row):
        data, raw, src = decoded(row.get('data_json')), decoded(row.get('raw_json')), decoded(row.get('source_json'))
        confirmed = row.get('identity_kind') == 'instance' and data.get('physical_instance_confirmed') is True
        # A source's assertion is not a human identity approval.
        return {'evidence_id': row['id'], 'original_tag': row.get('original_tag'), 'normalized_tag': row.get('normalized_tag'),
                'equipment_family': data.get('category'),
                'recorded_identity_kind': row.get('identity_kind'), 'identity_kind': 'Type' if row.get('identity_kind')=='type' else
                    'Group' if row.get('identity_kind')=='group' else 'Reference',
                'source_claims_instance': confirmed, 'is_active': bool(row.get('is_active')), 'role': row.get('role'),
                'original_data': data, 'raw_text': raw.get('raw_text'), 'physical_quantity': None,
                'review': self.reviews('occurrence', row['id']),
                'provenance': self.provenance('eq_occurrences',row,src,row.get('file_id'),row.get('version_id'))}

    def get_observations(self, reference, *, include_history=False, limit=25, offset=0):
        sql = self.selection(reference, include_history)
        return self.paged(sql + ' ORDER BY o.id' if sql else None, self.params(reference), self.observation,limit,offset,
                          'Active equipment import/registry relation unavailable')

    def get_parameters(self, reference, *, include_history=False, limit=25, offset=0):
        selected = self.selection(reference, include_history)
        sql = None
        if selected and self.has('eq_parameters','id','occurrence_id','project_id','name','payload_json'):
            sql = '''SELECT p.id,p.occurrence_id,p.name,p.payload_json,o.source_json,o.file_id,o.version_id,o.role,o.is_active,
                'eq_parameters' evidence_table,NULL raw_values_json,NULL printed_unit,NULL artifact_json,NULL profile_id,NULL review_status
                FROM eq_parameters p JOIN (''' + selected + ''') o ON o.id=p.occurrence_id WHERE p.project_id=:project'''
        fields = self.fields_sql(reference, include_history)
        if fields:
            extra = '''SELECT f.id,NULL occurrence_id,f.name,NULL payload_json,f.source_json,NULL file_id,NULL version_id,
                'schedule' role,NULL is_active,'uc_fields' evidence_table,f.raw_values_json,f.printed_unit,f.artifact_json,
                f.profile_id,f.review_status FROM (''' + fields + ') f'
            sql = sql + ' UNION ALL ' + extra if sql else extra
        if sql:
            sql = 'SELECT * FROM (' + sql + ') ORDER BY evidence_table,id'
        def fact(r):
            payload = decoded(r.get('payload_json')); original = payload.get('original', {})
            if r['evidence_table'] == 'uc_fields':
                original = {'name': r['name'], 'value': None, 'raw_values': decoded(r.get('raw_values_json'), []),
                            'unit': r.get('printed_unit'), 'source_cells': decoded(r.get('source_json')).get('source_cells')}
            return {'evidence_id': r['id'], 'occurrence_id': r['occurrence_id'], 'original_name': original.get('name',r.get('name')),
                'original_printed_value': original.get('value',payload.get('value')), 'unit': original.get('unit',payload.get('unit')),
                'component_or_operating_context': original.get('component') or original.get('context'),
                'original_parameter': original, 'stored_parameter': payload, 'source_cells': original.get('source_cells'),
                'schedule_role': r.get('role'), 'is_active': bool(r['is_active']) if r.get('is_active') is not None else None,
                'review': self.reviews('parameter',r['id']) if r['evidence_table']=='eq_parameters' else {'status': r.get('review_status')},
                'provenance': self.provenance(r['evidence_table'],r,decoded(r.get('source_json')),r.get('file_id'),r.get('version_id'),
                    {'profile_id':r.get('profile_id')},decoded(r.get('artifact_json')))}
        return self.paged(sql,self.params(reference),fact,limit,offset,'Equipment parameter relation unavailable')

    def fields_sql(self, reference, history=False):
        profiles = self.selected_profiles(reference, history)
        if profiles and self.has('uc_fields','id','profile_id','name','raw_values_json','printed_unit','source_json','artifact_json','review_status'):
            return 'SELECT f.* FROM uc_fields f JOIN (' + profiles + ') p ON p.id=f.profile_id'
        return None

    def get_schedule_fields(self, reference, *, include_history=False, limit=25, offset=0):
        sql=self.fields_sql(reference,include_history)
        def field(r):
            return {'evidence_id':r['id'],'original_name':r['name'],'raw_values':decoded(r['raw_values_json'],[]),
                    'printed_unit':r['printed_unit'],'review_status':r.get('review_status'),
                    'provenance':self.provenance('uc_fields',r,decoded(r['source_json']),relationship={'profile_id':r['profile_id']},
                        artifacts=decoded(r.get('artifact_json')))}
        return self.paged(sql+' ORDER BY f.id' if sql else None,self.params(reference),field,limit,offset,
                          'Additional consolidated schedule fields unavailable')

    def selected_profiles(self, reference, history=False):
        sql = self.profiles_sql(history)
        if sql is None:
            return None
        related = ''
        if self.has('uc_observations','profile_id','occurrence_id'):
            related = ' OR p.id IN (SELECT profile_id FROM uc_observations WHERE occurrence_id=:reference)'
            if self.has('eq_entity_sources','entity_id','occurrence_id','project_id'):
                related += ''' OR p.id IN (SELECT u.profile_id FROM uc_observations u JOIN eq_entity_sources s
                              ON s.occurrence_id=u.occurrence_id WHERE s.entity_id=:reference AND s.project_id=:project)'''
        return 'SELECT p.* FROM (' + sql + ') p WHERE p.id=:reference OR p.normalized_tag COLLATE NOCASE=:reference' + related

    def get_context(self, reference, *, role=None, include_history=False, limit=25, offset=0):
        if role not in (None,'boq','electrical','bms','drawing','schedule'):
            raise ValueError('Unsupported context role')
        if self.profiles_sql(include_history) is None:
            from .native_equipment import context
            return context(self,reference,role,include_history,limit,offset)
        profiles = self.selected_profiles(reference,include_history)
        sql = None
        if profiles and self.has('uc_context','id','run_id','source_json','fields_json','file_id','role') and self.has('uc_links','profile_id','context_id','relationship','review_status'):
            sql = '''SELECT c.*,l.profile_id,l.relationship,l.basis,l.review_status FROM uc_context c JOIN uc_links l
              ON l.context_id=c.id JOIN (''' + profiles + ''') p ON p.id=l.profile_id AND p.run_id=c.run_id''' + (
              ' WHERE c.role=:role' if role else '') + ' ORDER BY c.id,l.profile_id,l.relationship'
        def context(r):
            fields, src = decoded(r.get('fields_json')),decoded(r.get('source_json'))
            val = lambda key: fields.get(key,{}).get('value') if isinstance(fields.get(key),dict) else fields.get(key)
            return {'evidence_id':r['id'], 'profile_id':r['profile_id'], 'role':r['role'], 'raw_text':r.get('raw_text'),
                'recorded_fields':fields, 'relationship':r.get('relationship'), 'relationship_basis':r.get('basis'),
                'relationship_status':r.get('review_status'), 'item_code':val('item_number'),
                'description':val('description'), 'quantity_as_printed':val('quantity_raw'), 'unit_as_printed':val('quantity_unit'),
                'installation_location':val('installation_location'), 'area_served':val('area_served'),
                'provenance':self.provenance('uc_context',r,{**src,'sha256':r.get('sha256')},r.get('file_id'),
                   relationship={'profile_id':r['profile_id'],'status':r.get('review_status'),'kind':r.get('relationship')},
                   artifacts=decoded(r.get('artifact_json')))}
        return self.paged(sql,{**self.params(reference),'role':role},context,limit,offset,
                          'No supported current unified context relationship; native role observations remain separately available')

    def get_drawing_references(self, reference, *, include_history=False, limit=25, offset=0):
        selected = self.selection(reference,include_history)
        sql = 'SELECT o.* FROM (' + selected + ") o WHERE o.role IN ('drawing','schedule','electrical','bms') ORDER BY o.id" if selected else None
        def drawing(r):
            item=self.observation(r);src=decoded(r.get('source_json'));data=decoded(r.get('data_json'))
            original=item['provenance']['original_source'] or {}
            item.update(drawing_filename=Path(original.get('relative_path') or '').name or None,
                        drawing_number=src.get('drawing_number'),revision=src.get('document_revision'),
                        cad_handle=src.get('handle'),coordinates=src.get('coordinates'),
                        installation_location=data.get('installation_location'),area_served=data.get('area_served'),
                        location_warning='CAD coordinates and drawing scope are not installation locations')
            return item
        return self.paged(sql,self.params(reference),drawing,limit,offset,'Drawing occurrence relationship unavailable')

    def get_specifications(self, reference, *, section=None, applicability=None, include_history=False, limit=25, offset=0, evidence_ids=None):
        if self.profiles_sql(include_history) is None:
            from .native_equipment import specifications
            return specifications(self,reference,section,applicability,include_history,limit,offset,evidence_ids or [])
        if evidence_ids is not None:
            raise ValueError('Explicit Reader clause IDs are a native projection option; UC uses its existing saved links and supplier selection rules')
        profiles=self.selected_profiles(reference,include_history)
        requirements={'uc_spec_rules':('run_id','family','section','relationship','condition','review_status'),
                      'uc_spec_evidence':('run_id','file_id','record_id','classification'),
                      'uc_spec_documents':('run_id','file_id','section','metadata_json'),
                      'records':('id','version_id','raw_text','payload_json')}
        sql=None
        if profiles and all(self.has(t,*cols) for t,cols in requirements.items()):
            sql='''SELECT e.record_id id,e.file_id,e.classification,d.section,d.metadata_json,r.version_id,r.raw_text,r.payload_json,
              p.id profile_id,ru.relationship,ru.condition,ru.review_status applicability_status
              FROM (''' + profiles + ''') p JOIN uc_spec_rules ru ON ru.run_id=p.run_id AND ru.family=p.family
              JOIN uc_spec_documents d ON d.run_id=ru.run_id AND d.section=ru.section
              JOIN uc_spec_evidence e ON e.run_id=d.run_id AND e.file_id=d.file_id
              JOIN records r ON r.id=e.record_id WHERE (:section IS NULL OR d.section=:section)
              AND (:applicability IS NULL OR ru.review_status COLLATE NOCASE=:applicability)
              ORDER BY e.record_id,p.id,d.section'''
        def spec(r):
            payload=decoded(r.get('payload_json'));src=payload.get('source',{});data=payload.get('data',{});meta=decoded(r.get('metadata_json'))
            # Preserve the conversion record's distinct PDF identity and the linked original DOC.
            source={**src,'original_sha256':meta.get('original_sha256')}
            return {'evidence_id':r['id'],'profile_id':r['profile_id'],'exact_original_paragraph_text':r.get('raw_text'),
                'section':r.get('section'),'section_title':data.get('section_title'),'clause':src.get('clause'),
                'paragraph_number':src.get('paragraph'),'physical_pdf_page':src.get('pdf_page'),
                'verified_printed_page':src.get('printed_page') if src.get('printed_page_verified') is True else None,
                'printed_page_as_recorded':src.get('printed_page'),'recorded_fragments':data.get('fragments'),
                'classification':r.get('classification'),'applicability_status':r.get('applicability_status'),
                'relationship':r.get('relationship'),'condition':r.get('condition'),
                'applicability_scope':'Existing family/system link; not automatic tag-specific approval',
                'provenance':self.provenance('records',r,source,r.get('file_id'),r.get('version_id'),
                    {'profile_id':r['profile_id'],'kind':r.get('relationship'),'status':r.get('applicability_status')},meta)}
        return self.paged(sql,{**self.params(reference),'section':section,'applicability':applicability},spec,limit,offset,
                          'Supported UC specification link contract unavailable; other requirement schemas are not guessed')

    def get_findings(self, reference, *, include_history=False, limit=25, offset=0):
        profiles=self.selected_profiles(reference,include_history);sql=None
        if profiles and self.has('uc_findings','id','profile_id','classification','source_a_json','source_b_json'):
            sql='SELECT f.* FROM uc_findings f JOIN ('+profiles+') p ON p.id=f.profile_id ORDER BY f.id'
        def finding(r):
            a,b=decoded(r.get('source_a_json')),decoded(r.get('source_b_json'))
            return {'evidence_id':r['id'],'profile_id':r['profile_id'],'classification':r.get('classification'),
                'parameter':r.get('parameter'),'note':r.get('note'),'review_status':r.get('review_status'),
                'source_a':a,'source_b':b,'provenance':self.provenance('uc_findings',r,relationship={'profile_id':r['profile_id']}),
                'source_provenance': [self.provenance('uc_findings',r,x.get('source',{})) for x in (a,b) if isinstance(x,dict) and x.get('source')]}
        return self.paged(sql,self.params(reference),finding,limit,offset,'Supported consolidated finding relation unavailable')

    def get_relationships(self, reference, *, include_history=False, limit=25, offset=0):
        selected=self.selection(reference,include_history);base=self.occurrence_basis(include_history);sql=None
        if selected and self.has('eq_matches','id','project_id','run_id','left_id','right_id','evidence_json'):
            sql='''SELECT m.* FROM eq_matches m WHERE m.project_id=:project AND
              (m.left_id IN (SELECT id FROM ('''+selected+''')) OR m.right_id IN (SELECT id FROM ('''+selected+''')))
              AND m.left_id IN (SELECT id FROM ('''+base+''')) AND m.right_id IN (SELECT id FROM ('''+base+'''))'''
            if not include_history and self.has('eq_runs','id','project_id'):
                sql+=' AND m.run_id=(SELECT id FROM eq_runs WHERE project_id=:project ORDER BY rowid DESC LIMIT 1)'
            sql+=' ORDER BY m.id'
        def relationship(r):
            return {'database_record':{'table':'eq_matches','id':r['id']},'left_id':r['left_id'],'right_id':r['right_id'],
                    'run_id':r['run_id'],'kind':r.get('kind'),'candidate_status':r.get('proposed_status'),
                    'evidence':decoded(r.get('evidence_json')),'review':self.reviews('match',r['id']),
                    'run_currency':'UNKNOWN_NOT_REVALIDATED','physical_quantity':None}
        return self.paged(sql,self.params(reference),relationship,limit,offset,'Matching relationship contract unavailable')

    def list_equipment(self, family=None, *, include_history=False, limit=25, offset=0):
        profiles=self.profiles_sql(include_history)
        if profiles is None:
            from .native_equipment import profiles as native_profiles,page
            rows=native_profiles(self,family,include_history)
            if rows is None:
                result=self.page(limit=limit,offset=offset,reason='Native equipment/import/registry contract unavailable')
            else:result=page(self,rows,limit,offset,gaps=['One profile per native source observation; no physical-instance grouping.'])
            return self.envelope('list_equipment',family=family,include_history=include_history,
                entity_semantics='Native source-reference profiles; repeated tags remain separate candidates, never counts',result=result)
        if profiles:
            sql='SELECT p.* FROM ('+profiles+') p WHERE (:family IS NULL OR p.family COLLATE NOCASE=:family) ORDER BY p.normalized_tag,p.id'
            transform=lambda r:{**{k:v for k,v in r.items() if not k.endswith('_json')},'original_tags':decoded(r.get('original_tags_json'),[]),
                'provenance':self.provenance('uc_profiles',r,relationship={'profile_id':r['id'],'status':r.get('review_status')})}
        else:
            base=self.occurrence_basis(include_history)
            sql=None
            if base and self.has('eq_categories','id','project_id','name'):
                sql='''SELECT o.* FROM ('''+base+''') o LEFT JOIN eq_categories c ON c.id=o.category_id AND c.project_id=o.project_id
                  WHERE (:family IS NULL OR c.name COLLATE NOCASE=:family) ORDER BY o.normalized_tag,o.id'''
            transform=self.observation
        return self.envelope('list_equipment', family=family, include_history=include_history,
            entity_semantics='Unified profiles where current view is available, otherwise source references; never a physical count',
            result=self.paged(sql,{'project':self.cfg['project_id'],'family':family},transform,limit,offset,'No supported equipment family relation'))

    def list_source_limitations(self, *, limit=25, offset=0):
        sql=None
        if self.has('master_operator_events','id','project_id','action','payload_json'):
            sql="SELECT id,payload_json,'master_operator_events' evidence_table FROM master_operator_events WHERE project_id=:project AND action='accepted_source_limitation'"
        if self.has('uc_limitations','id','run_id','payload_json') and self.has('uc_runs','id','project_id'):
            extra="SELECT l.id,l.payload_json,'uc_limitations' evidence_table FROM uc_limitations l JOIN uc_runs r ON r.id=l.run_id WHERE r.project_id=:project"
            sql=sql+' UNION ALL '+extra if sql else extra
        if sql:
            sql='SELECT * FROM ('+sql+') ORDER BY evidence_table,id'
        return self.envelope('source_limitations', result=self.paged(sql,self.params(),lambda r:{'database_record':{'table':r['evidence_table'],'id':r['id']},
            'saved_limitation':decoded(r['payload_json']),'approval_scope':'Existing source limitation, not equipment approval'},limit,offset,
            'Accepted source limitation audit table unavailable'))

    def get_provenance(self, evidence_id, *, table=None):
        supported={'eq_occurrences','eq_parameters','records','uc_context','uc_fields','uc_findings','uc_profiles'}
        if table is not None and table not in supported:
            raise ValueError('Unsupported evidence table')
        matches=[]
        for name in sorted({table} if table else supported):
            r=self.row(name,evidence_id)
            if not r:
                continue
            # Optional UC rows lack project_id: verify their run/profile membership explicitly.
            if name.startswith('uc_'):
                run=r.get('run_id')
                if not run and r.get('profile_id'):
                    p=self.row('uc_profiles',r['profile_id']);run=p.get('run_id') if p else None
                if not self.row('uc_runs',run):
                    continue
            if name=='eq_parameters':
                occurrence=self.row('eq_occurrences',r.get('occurrence_id')) or {};imp=self.row('eq_imports',occurrence.get('import_id')) or {}
                matches.append(self.provenance(name,r,decoded(occurrence.get('source_json')),imp.get('file_id'),imp.get('version_id')))
            elif name=='records':
                v=self.row('versions',r.get('version_id')) or {};meta=decoded(v.get('metadata_json'))
                fid=meta.get('metadata',{}).get('file_id') or meta.get('metadata',{}).get('supplied_metadata',{}).get('original_source',{}).get('file_id')
                if not fid:
                    fid=meta.get('metadata',{}).get('supplied_metadata',{}).get('file_id')
                if not fid and self.heads():
                    candidates=[]
                    for head in self.conn.execute(self.heads(),self.params()):
                        version=self.version_identity(head['version_id']) or {}
                        if version.get('sha256')==v.get('sha256') and Path(version.get('source_path') or '').resolve()==Path(v.get('source_path') or '').resolve():
                            candidates.append(head['file_id'])
                    if len(candidates)==1:fid=candidates[0]
                if not self.row('registry_files',fid):
                    continue
                matches.append(self.provenance(name,r,decoded(r.get('payload_json')).get('source',{}),fid,r.get('version_id')))
            else:
                imp=self.row('eq_imports',r.get('import_id')) or {}
                source=decoded(r.get('source_json'))
                if r.get('sha256'):
                    source={**source,'sha256':r['sha256']}
                citation=self.provenance(name,r,source,r.get('file_id') or imp.get('file_id'),imp.get('version_id'),
                    {'profile_id':r.get('profile_id')},decoded(r.get('artifact_json')))
                if name=='uc_findings':
                    citation['source_citations']=[self.provenance(name,r,x.get('source',{})) for x in
                        (decoded(r.get('source_a_json')),decoded(r.get('source_b_json'))) if isinstance(x,dict) and x.get('source')]
                matches.append(citation)
        return self.envelope('provenance',evidence_id=evidence_id,status='AVAILABLE' if matches else 'NOT_FOUND_OR_UNSUPPORTED',items=matches)

    def inspect_evidence(self, evidence_id, *, table):
        """Exact immutable row and cited values for bounded human inspection; never a review constructor."""
        ordinary={'eq_occurrences','eq_parameters','records','uc_context','uc_fields','uc_findings','uc_profiles'}
        extra={'eq_entities','eq_matches','registry_revisions','versions'}
        if table not in ordinary|extra:
            raise ValueError('Unsupported review evidence table')
        row=self.row(table,evidence_id)
        if not row:
            return self.envelope('inspect_evidence',status='NOT_FOUND',items=[])
        provenance=None;role=None;related=[]
        if table in ordinary:
            projection=self.get_provenance(evidence_id,table=table)
            if not projection['items']:
                return self.envelope('inspect_evidence',status='NOT_FOUND_OR_FOREIGN',items=[])
            provenance=projection['items'][0]
            occurrence=row if table=='eq_occurrences' else self.row('eq_occurrences',row.get('occurrence_id'))
            imp=self.row('eq_imports',occurrence.get('import_id')) if occurrence else None
            role=imp.get('role') if imp else 'schedule' if table=='uc_fields' else None
            if table=='uc_profiles' and self.has('uc_observations','profile_id','occurrence_id'):
                related=[{'table':'eq_occurrences','id':r[0]} for r in self.conn.execute(
                    'SELECT occurrence_id FROM uc_observations WHERE profile_id=? ORDER BY occurrence_id',(row['id'],))]
        elif table=='versions':
            meta=decoded(row.get('metadata_json'));nested=meta.get('metadata',{})
            original=nested.get('supplied_metadata',{}).get('original_source',{})
            fid=nested.get('file_id') or original.get('file_id')
            if not fid:
                prefix='registry:'+self.cfg['project_id']+':'
                logical=row.get('logical_key') or ''
                fid=logical[len(prefix):] if logical.startswith(prefix) else None
            if not self.row('registry_files',fid):
                return self.envelope('inspect_evidence',status='NOT_FOUND_OR_FOREIGN',items=[])
            provenance=self.provenance(table,row,{'file_id':fid,'sha256':original.get('sha256') or row.get('sha256')},fid,row['id'])
        elif table=='registry_revisions':
            analysis=self.row('registry_analyses',row.get('analysis_id')) or {}
            version=analysis.get('version_id');v=self.row('versions',version) or {}
            provenance=self.provenance(table,row,{'file_id':row.get('file_id'),'sha256':v.get('sha256')},row.get('file_id'),version)
        elif table=='eq_entities' and self.has('eq_entity_sources','project_id','entity_id','occurrence_id'):
            related=[{'table':'eq_occurrences','id':r[0]} for r in self.conn.execute(
                'SELECT occurrence_id FROM eq_entity_sources WHERE project_id=? AND entity_id=? ORDER BY occurrence_id',
                (self.cfg['project_id'],row['id']))]
        elif table=='eq_matches':
            related=[{'table':'eq_occurrences','id':row[k]} for k in ('left_id','right_id')]
        parsed={k[:-5]:decoded(v) for k,v in row.items() if k.endswith('_json')}
        legacy=[]
        kinds={'eq_occurrences':'occurrence','eq_parameters':'parameter','eq_entities':'entity','eq_matches':'match'}
        if table in kinds and self.has('eq_reviews','project_id','target_kind','target_id'):
            legacy=[{'table':'eq_reviews',**dict(r)} for r in self.conn.execute(
                'SELECT * FROM eq_reviews WHERE project_id=? AND target_kind=? AND target_id=? ORDER BY rowid',
                (self.cfg['project_id'],kinds[table],row['id']))]
        if table=='records' and self.has('reviews','record_id'):
            legacy=[{'table':'reviews',**dict(r)} for r in self.conn.execute('SELECT * FROM reviews WHERE record_id=? ORDER BY id',(row['id'],))]
        if table=='registry_revisions' and self.has('registry_reviews','project_id','target_revision'):
            legacy=[{'table':'registry_reviews',**dict(r)} for r in self.conn.execute(
                'SELECT * FROM registry_reviews WHERE project_id=? AND target_revision=? ORDER BY id',(self.cfg['project_id'],row['id']))]
        return self.envelope('inspect_evidence',status='AVAILABLE',items=[{'table':table,'id':row['id'],
            'original_record':row,'parsed_original':parsed,'provenance':provenance,'source_role':role,'related_references':related,
            'legacy_reviews':legacy,'legacy_review_validity':'NOT_REVALIDATED_NO_APPROVAL_INFERRED'}])

    def source_version_basis(self, file_ids):
        """Registered heads only. No source hash execution or revision approval."""
        sql=self.heads();result={}
        if sql:
            for fid in sorted(set(file_ids)):
                row=self.conn.execute('SELECT * FROM ('+sql+') WHERE file_id=:file_id',
                    {'project':self.cfg['project_id'],'file_id':fid}).fetchone()
                if row:
                    value=dict(row);value['version']=self.version_identity(value['version_id']);result[fid]=value
        return result

    def get_decision_history(self, reference=None, *, decision_type=None, limit=25, offset=0):
        from .human_decisions import decision_history
        return decision_history(self,reference,decision_type=decision_type,limit=limit,offset=offset)

    def check_decision_validity(self, decision_id):
        from .human_decisions import decision_validity
        return decision_validity(self,decision_id)

    def list_pending_reviews(self, *, family=None, limit=25, offset=0):
        from .human_decisions import pending_targets
        return pending_targets(self,family=family,limit=limit,offset=offset)

    def get_equipment_profile(self, reference, *, include_history=False, include_decisions=False, limit=25, offset=0, specification_evidence_ids=None):
        if not isinstance(reference,str) or not reference.strip():
            raise ValueError('A nonempty equipment reference is required')
        reference=reference.strip()
        psql=self.selected_profiles(reference,include_history)
        identities=self.paged(psql+' ORDER BY p.id' if psql else None,self.params(reference),lambda r:{
            'id':r['id'],'original_tags':decoded(r.get('original_tags_json'),[]),'normalized_tag':r.get('normalized_tag'),
            'family':r.get('family'),'identity_kind':r.get('identity_kind'),'review_status':r.get('review_status'),
            'description':r.get('description'),'provenance':self.provenance('uc_profiles',r,relationship={'profile_id':r['id']})},
            limit,offset,'Current consolidated profile contract unavailable; see source observations')
        if self.profiles_sql(include_history) is None:
            from .native_equipment import profiles as native_profiles,page
            rows=native_profiles(self,history=include_history,reference=reference)
            if rows is not None:identities=page(self,rows,limit,offset,gaps=['Native evidence profile; identity and quantity remain unapproved.'])
        specification_selection={'evidence_ids':specification_evidence_ids} if specification_evidence_ids is not None else {}
        sections={'identities':identities,'observations':self.get_observations(reference,include_history=include_history,limit=limit,offset=offset),
            'parameters':self.get_parameters(reference,include_history=include_history,limit=limit,offset=offset),
            'drawings':self.get_drawing_references(reference,include_history=include_history,limit=limit,offset=offset),
            'specifications':self.get_specifications(reference,include_history=include_history,limit=limit,offset=offset,**specification_selection),
            'context':self.get_context(reference,include_history=include_history,limit=limit,offset=offset),
            'findings':self.get_findings(reference,include_history=include_history,limit=limit,offset=offset),
            'candidate_relationships':self.get_relationships(reference,include_history=include_history,limit=limit,offset=offset),
            'project_source_limitations':self.list_source_limitations(limit=limit,offset=offset)['result']}
        missing=[{'domain':name,'status':s['status'],'meaning':'No saved evidence in this supported scope, not proof of absence'}
                 for name,s in sections.items() if s['status']!='AVAILABLE']
        result=self.envelope('equipment_profile',reference=reference,include_history=include_history,sections=sections,
            status='AVAILABLE' if (sections['observations']['total'] or identities['total']) else 'NOT_FOUND_OR_UNSUPPORTED',
            physical_equipment_quantity=None,missing_information=missing,
            source_coverage={'status':'UNKNOWN_NOT_CERTIFIED','scope':'Recorded evidence only; project limitations are not automatically equipment-specific'},
            limitations=['No physical counts inferred from labels, match pairs or controller quantities.',
                        'Saved decisions are returned with their basis; no new approval or correction is applied.',
                        'Current imports mean current registry analysis/slot, not engineering approval or live source verification.',
                        'UC context/specifications require a current project-scoped view; unknown alternative schemas remain unsupported.',
                        'Each section has independent total/offset/next_offset; no linked collection is silently truncated.'])
        if self.profiles_sql(include_history) is None:
            result['equipment_profile_contract']='mep-equipment-profile/1'
            result['limitations'][-2]='Native clauses require explicit core IDs or recorded native requirement links; unlinked clauses stay unselected.'
        if include_decisions:
            result['human_decisions']=self.get_decision_history(reference,limit=limit,offset=offset)
        return result

    def write_json(self, output, response):
        """Explicit exclusive-create export. Nothing else in the reader writes files."""
        target=Path(output).resolve()
        blocked=[Path(self.cfg['source_directory']).resolve(),Path(self.cfg['database']).resolve().parent,HOME.resolve()]
        if self.has('versions','archive_path'):
            for r in self.conn.execute('SELECT DISTINCT archive_path FROM versions WHERE archive_path IS NOT NULL'):
                archive=Path(r[0]);archive=archive if archive.is_absolute() else Path(self.cfg['database']).parent/archive
                blocked.append(archive.resolve().parent)
        if any(target.is_relative_to(p) for p in blocked):
            raise ValueError('Export must be outside source documents, database/state, evidence archives and installed master')
        encoded=json.dumps(response,ensure_ascii=False,indent=2,allow_nan=False)
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as stream:
            stream.write(encoded)
        return str(target)
