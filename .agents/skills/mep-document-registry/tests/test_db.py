import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from mep_registry.db import Registry

SKILLS = next(p / '.agents/skills' for p in Path(__file__).resolve().parents if (p / '.agents/skills/etl-pipeline').is_dir())


class DatabaseTests(unittest.TestCase):
    def test_additive_migration_preserves_existing_engineering_database(self):
        with tempfile.TemporaryDirectory(dir=SKILL / 'tests') as temporary:
            path = Path(temporary) / 'engineering.sqlite'
            script = SKILLS / 'etl-pipeline/scripts/mep_store.py'
            spec = importlib.util.spec_from_file_location('test_registry_core', script)
            core = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(core)
            original = core.Store(path)
            source = Path(temporary) / 'source.csv'
            source.write_text('Tag\nAHU-01\n', encoding='utf-8')
            original.ingest({'schema_version':'mep-evidence/1','document':core.document_info(source),
                             'records':[{'kind':'equipment','raw_text':'AHU-01','source':{'method':'synthetic'},
                                         'data':{'tag':'AHU-01'},'review':{'status':'unreviewed','issues':[]}}], 'issues':[]})
            before = [tuple(row) for row in original.conn.execute('select * from records')]
            original.close()
            registry = Registry(path, skills_root=SKILLS)
            project = registry.ensure_project(temporary, 'synthetic-project')
            self.assertEqual(project['id'], 'synthetic-project')
            self.assertEqual(registry.conn.execute('pragma user_version').fetchone()[0], 2)
            self.assertEqual([tuple(row) for row in registry.conn.execute('select * from records')], before)
            registry.close()
            reopened = core.Store(path)
            self.assertEqual(len(reopened.search('AHU')['results']), 1)
            reopened.close()

    def test_project_identity_does_not_silently_change_root(self):
        with tempfile.TemporaryDirectory(dir=SKILL / 'tests') as temporary:
            base = Path(temporary)
            a, b = base/'a', base/'b'
            a.mkdir(); b.mkdir()
            registry = Registry(base/'engineering.sqlite', skills_root=SKILLS)
            try:
                registry.ensure_project(a, 'fixed-project')
                with self.assertRaises(ValueError):
                    registry.ensure_project(b, 'fixed-project')
            finally:
                registry.close()


if __name__ == '__main__':
    unittest.main()
