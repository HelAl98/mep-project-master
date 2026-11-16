from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
from mep_registry.scan import scan_project
from mep_registry.db import Registry


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=SKILL/'tests'); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.root=self.base/'sources'; self.root.mkdir()
        self.db=self.base/'engineering.sqlite'

    def pdf(self):
        from reportlab.pdfgen.canvas import Canvas
        path=self.root/'SYN-101.pdf'; canvas=Canvas(str(path))
        for i,line in enumerate(['DRAWING NUMBER: SYN-101','TITLE: Original marker','REVISION: A']):
            canvas.drawString(60,750-i*20,line)
        canvas.save(); return path

    def test_identity_correction_invalidates_prior_relationship_confirmation(self):
        self.pdf(); (self.root/'SYN-101.dwg').write_bytes(b'SYNTHETIC DWG')
        snapshot=scan_project(self.root,self.db,'synthetic-lifecycle')
        registry=Registry(self.db)
        try:
            relation=next(r for r in snapshot['relationships'] if r['type']=='representation_match')
            registry.review('synthetic-lifecycle','relationship',relation['relationship_id'],'confirm_relationship','Synthetic Engineer','Fixture pair')
            observation=next(o for o in snapshot['observations'] if o['field']=='document_number' and o['value']=='SYN-101' and o['sheet_id'] is None)
            registry.review('synthetic-lifecycle','observation',observation['observation_id'],'correct_metadata','Synthetic Engineer','Correct identity',value='SYN-999')
            changed=registry.snapshot('synthetic-lifecycle')
            old=next(r for r in changed['relationships'] if r['relationship_id']==relation['relationship_id'])
            self.assertEqual(old['verification_status'],'invalidated')
            with self.assertRaises(ValueError):
                registry.review('synthetic-lifecycle','relationship',relation['relationship_id'],'confirm_relationship','Synthetic Engineer','Old identity')
        finally: registry.close()

    def test_corrected_metadata_is_searchable_without_claiming_raw_evidence_changed(self):
        path=self.root/'facts.txt'; path.write_text('TITLE: OriginalMarker\n',encoding='utf-8')
        snapshot=scan_project(self.root,self.db,'synthetic-lifecycle')
        registry=Registry(self.db)
        try:
            observation=next(o for o in snapshot['observations'] if o['field']=='title' and o['value']=='OriginalMarker')
            registry.review('synthetic-lifecycle','observation',observation['observation_id'],'correct_metadata','Synthetic Engineer','Reviewed correction',value='ReviewedMarker')
            hits=registry.search('synthetic-lifecycle','ReviewedMarker')
            self.assertTrue(hits)
            self.assertEqual(hits[0]['value'],'OriginalMarker')
            self.assertEqual(hits[0]['current_value'],'ReviewedMarker')
            path.write_text('TITLE: NewSourceMarker\n',encoding='utf-8')
            scan_project(self.root,self.db,'synthetic-lifecycle')
            self.assertFalse(registry.search('synthetic-lifecycle','ReviewedMarker'))
            self.assertTrue(registry.search('synthetic-lifecycle','ReviewedMarker',history=True))
        finally: registry.close()

    def test_relationship_budget_limits_proposals_without_losing_files(self):
        for i in range(6):
            sub=self.root/str(i); sub.mkdir(); (sub/'same.txt').write_text('TITLE: Synthetic same\n',encoding='utf-8')
        snapshot=scan_project(self.root,self.db,'synthetic-lifecycle',{'max_relationship_pairs':2})
        self.assertEqual(snapshot['summary']['file_count'],6)
        self.assertLessEqual(sum(r['type']=='duplicate_content' for r in snapshot['relationships']),2)
        self.assertIn('RELATIONSHIP_LIMIT',{i['code'] for i in snapshot['issues']})

    def test_unclassified_category_does_not_invent_a_document_type(self):
        (self.root/'unknown.bin').write_bytes(b'SYNTHETIC unknown format')
        snapshot=scan_project(self.root,self.db,'synthetic-lifecycle')
        item=snapshot['files'][0]
        self.assertIsNone(item['metadata']['document_type'])
        self.assertEqual(item['classification_category'],'Unclassified Documents')


if __name__=='__main__': unittest.main()
