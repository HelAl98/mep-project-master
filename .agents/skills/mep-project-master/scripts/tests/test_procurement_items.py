"""New bounded checks only; isolated sources, no historical project or old suites."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import contextlib
import io

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from master_project.procurement import prepare, run_procurement, snapshot, decide, confirm_issue, link_evidence, interpret


class ProcurementChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mep-procurement-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.src=self.base/'sources';self.src.mkdir()
        self.schedule=self.src/'mechanical_schedule.csv'
        self.schedule.write_text('Tag,Item Type,Description,Service,Size,Material,Pressure Class,Connection,Quantity,Quantity Unit,Motor Power (kW)\nP-01,Pump,Pump for water,CHW,DN80,Iron,PN16,Flanged,2,ea,7.5\n,Valve,Butterfly valve,CHW,DN80,Iron,PN16,Flanged,8,ea,\n,Valve,Butterfly valve,CHW,DN80,Iron,,Flanged,3,ea,\n',encoding='utf-8')
        (self.src/'unreadable.dwg').write_bytes(b'UNPARSED FIXTURE')
        self.cfg=prepare(self.src,state=self.base/'state-root')
        self.cfg['project_name']='FIXTURE_ONLY_MECHANICAL_PROCUREMENT'

    def run_it(self):
        return run_procurement(self.cfg)

    def test_store_partial_reuse_and_safe_identity(self):
        first=self.run_it();view=snapshot(self.cfg)
        self.assertEqual(len(view['items']),3)
        self.assertTrue(any(g['status']=='File present but unreadable or unsupported' for g in view['gaps']))
        self.assertTrue(any(g['status']=='Not provided in the available files' for g in view['gaps']))
        with closing(sqlite3.connect(self.cfg['database'])) as db:
            self.assertGreater(db.execute('select count(*) from records').fetchone()[0],0)
            before=db.execute('select count(*) from runs').fetchone()[0]
        self.run_it()
        with closing(sqlite3.connect(self.cfg['database'])) as db:
            self.assertEqual(before,db.execute('select count(*) from runs').fetchone()[0])
        self.assertEqual(snapshot(self.cfg)['fingerprint'],view['fingerprint'])
        self.assertTrue(all(i['calculated_quantity'] is None for i in view['items']))
        self.assertTrue(first['deliveries'])

    def test_decisions_are_field_scoped_and_invalidated(self):
        self.run_it()
        boq=self.src/'boq.csv'
        boq.write_text('Tag,Item Type,Description,Service,Quantity,Quantity Unit,Motor Power (kW)\nP-01,Pump,Pump for water,CHW,4,ea,11\n',encoding='utf-8')
        self.run_it();view=snapshot(self.cfg)
        item=next(i for i in view['items'] if i['tag']=='P-01')
        qty=next(f for f in item['facts'] if f['field']=='quantity' and f['value']=='4')
        decision=decide(self.cfg,item['id'],'quantity',qty['link_id'],'Use the BOQ quantity for this pump','Fixture Engineer')
        chosen=next(i for i in snapshot(self.cfg)['items'] if i['id']==item['id'])
        self.assertEqual(chosen['selected']['quantity']['value'],'4')
        self.assertNotIn('motor_power',chosen['selected'])
        self.assertTrue(any(f['field']=='motor_power' and f['kind']=='comparable_disagreement' for f in chosen['findings']))
        boq.write_text(boq.read_text().replace(',4,ea,11',',5,ea,11'))
        self.run_it()
        changed=next(i for i in snapshot(self.cfg)['items'] if i['id']==item['id'])
        self.assertNotIn('quantity',changed['selected'])
        self.assertEqual(changed['decisions'][-1]['validity'],'Requires Revalidation')
        self.assertTrue(decision['statement'])

    def test_exact_clause_link_render_and_unresolved_issue_gate(self):
        from docx import Document
        spec=self.src/'valve_specs.docx'
        d=Document();d.add_paragraph('SECTION 23 05 23 Valves')
        d.add_paragraph('A. Valve bodies shall be iron.')
        d.add_paragraph('B. Unrelated decorative finishes are not procurement requirements.')
        d.save(spec)
        self.run_it();view=snapshot(self.cfg)
        valve=next(i for i in view['items'] if not i['tag'] and not i['identity_missing'])
        clauses=[c for c in valve['clauses'] if 'Valve bodies' in c['text']]
        self.assertTrue(clauses)
        link_evidence(self.cfg,valve['id'],clauses[0]['record_id'],relation='direct',basis='Exact valve body clause selected after reading')
        decide(self.cfg,valve['id'],'pressure_class',None,'SYNTHETIC: leave pressure class unresolved','Fixture Engineer')
        self.run_it();current=snapshot(self.cfg,item_ids=[valve['id']])
        with self.assertRaisesRegex(ValueError,'FOR ISSUE blocked'):
            confirm_issue(self.cfg,[valve['id']],current['fingerprint'],'Confirm this valve scope and information for issue','Fixture Engineer')
        review=self.run_it()
        delivery=next(d for d in review['deliveries'] if d['category']=='valve')
        word=Document(delivery['docx'])
        text='\n'.join(p.text for p in word.paragraphs)
        self.assertIn('Valve bodies shall be iron.',text)
        self.assertIn('Page unavailable',text)
        self.assertNotIn('Unrelated decorative finishes',text)
        from openpyxl import load_workbook
        wb=load_workbook(delivery['xlsx'],data_only=False)
        self.assertIn('Items',wb.sheetnames)
        self.assertTrue(any('UNKNOWN' in str(c.value) for row in wb['Items'] for c in row))
        wb.close()
        spec.write_bytes(spec.read_bytes()+b'changed')
        with self.assertRaises(ValueError):
            confirm_issue(self.cfg,[valve['id']],current['fingerprint'],'Issue again','Fixture Engineer')

    def test_scope_missing_attributes_and_no_implicit_approval(self):
        self.run_it();all_items=snapshot(self.cfg)
        valves=snapshot(self.cfg,scope={'categories':['valve']})
        self.assertEqual(len(valves['items']),2)
        self.assertNotEqual(valves['items'][0]['id'],valves['items'][1]['id'])
        self.assertTrue(all(not i['selected'] for i in all_items['items']))
        with self.assertRaises(ValueError):
            decide(self.cfg,valves['items'][0]['id'],'quantity','made-up-link','Use quantity','Fixture Engineer')
        with self.assertRaises(PermissionError):
            run_procurement(self.cfg,executor_role='subagent')

    def test_interpret_spec_material_then_choose_only_that_field(self):
        from docx import Document
        spec=self.src/'specifications.docx';d=Document()
        d.add_paragraph('SECTION 23 05 23 Valves')
        d.add_paragraph('A. Valve body material shall be bronze.')
        d.save(spec)
        self.run_it();view=snapshot(self.cfg)
        valve=next(i for i in view['items'] if i['category']=='valve' and not i['identity_missing'])
        clause=next(c for c in valve['clauses'] if 'bronze' in c['text'])
        interpret(self.cfg,valve['id'],clause['record_id'],{'body_material':{'value':'bronze','unit':None}},
                  clause['text'],'Literal body material statement; applicability candidate')
        updated=snapshot(self.cfg,item_ids=[valve['id']])['items'][0]
        bronze=next(f for f in updated['facts'] if f['field']=='body_material')
        decide(self.cfg,valve['id'],'body_material',bronze['link_id'],'Use the specification for this valve body material','Fixture Engineer')
        self.run_it()
        chosen=snapshot(self.cfg,item_ids=[valve['id']])['items'][0]
        self.assertEqual(chosen['selected']['body_material']['value'],'bronze')
        self.assertNotIn('quantity',chosen['selected'])
        with self.assertRaises(ValueError):
            interpret(self.cfg,valve['id'],clause['record_id'],{'body_material':{'value':'titanium'}},clause['text'],'Invented value')
        decide(self.cfg,valve['id'],'body_material',None,'Leave this difference unresolved','Fixture Engineer')
        self.assertNotIn('body_material',snapshot(self.cfg,item_ids=[valve['id']])['items'][0]['selected'])

    def test_material_punctuation_and_subtypes_never_collapse(self):
        self.schedule.write_text('Item Type,Description,Service,Size,Material,Pressure Class,Connection,Quantity,Quantity Unit\nValve,Butterfly valve,CHW,1.5,Iron,PN16,Flanged,1,ea\nValve,Butterfly valve,CHW,15,Iron,PN16,Flanged,1,ea\nValve,Gate valve,CHW,15,Iron,PN16,Flanged,1,ea\n',encoding='utf-8')
        self.run_it()
        self.assertEqual(len(snapshot(self.cfg)['items']),3)

    def test_native_pdf_storage_and_related_electrical_units(self):
        from reportlab.pdfgen.canvas import Canvas
        spec=self.src/'pump_specification.pdf';canvas=Canvas(str(spec))
        for i,line in enumerate(['SECTION 23 00 00','1.1 GENERAL','A. Pump casing shall resist corrosion.']):
            canvas.drawString(40,750-i*25,line)
        canvas.save()
        (self.src/'electrical_mcc.csv').write_text('Tag,Service,Motor Power (W)\nP-01,CHW,7500\n',encoding='utf-8')
        self.run_it();view=snapshot(self.cfg)
        self.assertEqual(len(view['items']),3)  # MCC references are not new purchase items.
        pump=next(i for i in view['items'] if i['tag']=='P-01')
        self.assertTrue(any(f['unit']=='W' and f['value']=='7500' for f in pump['facts']))
        self.assertFalse(any(f['field']=='motor_power' for f in pump['findings']))
        self.assertTrue(any(c['citation']['pdf_page']==1 for c in pump['clauses']))
        with closing(sqlite3.connect(self.cfg['database'])) as db:
            self.assertGreater(db.execute("SELECT count(*) FROM records WHERE kind='specification'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM master_events WHERE job_id IS NULL AND status!='PENDING'").fetchone()[0],0)

    def test_cli_scope_and_later_expansion_reuses_queryable_source(self):
        from master_project.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code=main(['--config',self.cfg['config_path'],'procurement','run','--category','valve'])
        self.assertEqual(code,0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['items'],2)
        self.assertEqual({d['category'] for d in result['deliveries']},{'valve'})
        with closing(sqlite3.connect(self.cfg['database'])) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM master_procurement_items WHERE category='pump'").fetchone()[0],0)
        from master_project.procurement import configure
        configure(self.cfg,{'scope':{}})
        expanded=self.run_it()
        self.assertEqual(expanded['items'],3)
        self.assertGreaterEqual(expanded['reused_sources'],1)

    def test_identity_kinds_and_audited_reasoning_guards(self):
        self.schedule.write_text('Tag,Item Type,Description,Service,Identity\nP-01,Pump,Pump reference,CHW,Reference\nP-01,Pump,Pump type,CHW,Type\n',encoding='utf-8')
        self.run_it();view=snapshot(self.cfg)
        self.assertEqual({i['identity_kind'] for i in view['items']},{'Reference','Type'})
        self.assertEqual(len(view['items']),2)
        from master_project.procurement import record_reasoning
        with self.assertRaises(ValueError):
            record_reasoning(self.cfg,{'role':'equipment_matcher','task_id':'fixture','basis':'test','actual_model':'gpt-6.1-sol'})
        with self.assertRaises(PermissionError):
            record_reasoning(self.cfg,{'role':'critical_reviewer','task_id':'fixture','basis':'test','fallback_reason':'No explicit user request'})
        record_reasoning(self.cfg,{'role':'equipment_matcher','task_id':'fixture','basis':'No model needed for literal equality',
                                  'fallback_reason':'Main deterministic comparison; no subagent invoked','actual_model':None,'evidence_ids':[]})
        from master_project.supplier_draft import render_procurement_items
        with self.assertRaises(PermissionError):render_procurement_items(self.cfg,view,mode='issue')
        with closing(sqlite3.connect(self.cfg['database'])) as db:
            self.assertGreater(db.execute("SELECT count(*) FROM master_operator_events WHERE action='procurement_findings_v1'").fetchone()[0],0)


if __name__=='__main__':
    unittest.main()

