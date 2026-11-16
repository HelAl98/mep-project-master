import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
from mep_registry.scan import scan_project, choose_database
from mep_registry.db import Registry


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=SKILL/'tests')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/'source'; self.root.mkdir()
        (self.root/'synthetic.txt').write_text('TITLE: Synthetic register\nDOCUMENT NUMBER: SYN-01\nREVISION: A\nDISCIPLINE: BMS\n',encoding='utf-8')
        self.db=self.base/'engineering.sqlite'

    def run_cli(self,*args):
        return subprocess.run([sys.executable,'-X','utf8','-B',str(SKILL/'scripts/registry.py'),*map(str,args)],
                              capture_output=True,encoding='utf-8',timeout=60)

    def test_scan_exports_and_rescan_excludes_generated_output(self):
        first=self.run_cli('scan','--root',self.root,'--db',self.db,'--project-id','synthetic-cli')
        self.assertEqual(first.returncode,0,first.stderr)
        output=json.loads(first.stdout)
        self.assertEqual(output['summary']['file_count'],1)
        self.assertTrue(Path(output['outputs']['document_register.xlsx']).is_file())
        second=self.run_cli('rescan','--root',self.root,'--db',self.db,'--project-id','synthetic-cli')
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads(second.stdout)['summary']['unchanged_files'],1)

    def test_read_commands_do_not_create_missing_database(self):
        missing=self.base/'missing.sqlite'
        result=self.run_cli('issues','--db',missing,'--project-id','not-present')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(missing.exists())

    def test_existing_database_discovered_and_ambiguous_choice_refused(self):
        existing=self.root/'existing.sqlite'
        reg=Registry(existing); reg.close()
        self.assertEqual(choose_database(self.root),existing.resolve())
        other=self.root/'another.sqlite'
        reg=Registry(other); reg.close()
        with self.assertRaises(ValueError): choose_database(self.root)

    def test_cli_review_and_search(self):
        snapshot=scan_project(self.root,self.db,'synthetic-cli')
        revision=snapshot['revisions'][0]
        response=self.run_cli('review','--db',self.db,'--project-id','synthetic-cli',
                              '--target-type','revision','--target-id',revision['revision_id'],
                              '--decision','approve_applicability','--actor','Synthetic CLI Engineer','--reason','Synthetic demonstration')
        self.assertEqual(response.returncode,0,response.stderr)
        shown=self.run_cli('show','--db',self.db,'--project-id','synthetic-cli')
        self.assertEqual(json.loads(shown.stdout)['revisions'][0]['verification_status'],'applicable')
        found=self.run_cli('search','--db',self.db,'--project-id','synthetic-cli','--query','register')
        self.assertTrue(json.loads(found.stdout)['results'])

    def test_interrupted_scan_is_visible_and_rerun_is_safe(self):
        from unittest.mock import patch
        with patch('mep_registry.scan.extract_document',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): scan_project(self.root,self.db,'synthetic-cli')
        registry=Registry(self.db)
        try: self.assertEqual(registry.snapshot('synthetic-cli')['scan']['status'],'interrupted')
        finally: registry.close()
        completed=scan_project(self.root,self.db,'synthetic-cli')
        self.assertEqual(completed['summary']['file_count'],1)
        self.assertIn(completed['scan']['status'],('completed','completed_with_errors'))

    def test_demo_is_explicitly_synthetic_and_reproducible(self):
        demo=self.run_cli('demo','--output',self.base/'synthetic-demo')
        self.assertEqual(demo.returncode,0,demo.stderr)
        data=json.loads(demo.stdout)
        self.assertTrue(data['synthetic'])
        self.assertEqual(data['rescan']['processed_files'],0)
        self.assertTrue(Path(data['outputs']['registry_summary.json']).is_file())


if __name__=='__main__': unittest.main()
