import tempfile
from pathlib import Path
import threading
import unittest
from pymacauto import UnsafeOperation
from pymacauto.operations import OperationSession
from pymacauto.pages import PageSession
import test_pages

class ProtectedPageTests(unittest.TestCase):
    def setUp(self):
        f=test_pages.PageTests();f.setUp();self.b,self.app,self.pages=f.b,f.app,f.pages
    def test_sheet_blocks_switch(self):
        self.b.nodes['window']['AXSheets']=['sheet']
        session=PageSession(self.app,window={'identifier':'window'},pages=self.pages)
        with self.assertRaises(UnsafeOperation):session.switch('B')
        self.assertEqual(self.b.calls,[])
    def test_stopped_switch_never_clicks(self):
        stop=threading.Event();stop.set()
        with OperationSession(self.app,window={'identifier':'window'},stop=stop) as owner:
            session=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
            with self.assertRaises(UnsafeOperation):session.switch('B')
        self.assertEqual(self.b.calls,[])
    def test_noop_id_cannot_later_name_another_page(self):
        with OperationSession(self.app,window={'identifier':'window'}) as owner:
            s=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
            self.assertEqual(s.switch('A',operation_id='noop')['page'],'A')
            with self.assertRaises(UnsafeOperation):s.switch('B',operation_id='noop')
        self.assertEqual(self.b.calls,[])
    def test_noop_id_bound_across_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=Path(folder).resolve()/'noop.db'
            with OperationSession(self.app,window={'identifier':'window'},journal=journal) as owner:
                s=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
                r=s.switch('A',operation_id='noop')['receipt']
                self.assertFalse(r['verified']);self.assertTrue(r['observed'])
            with OperationSession(self.app,window={'identifier':'window'},journal=journal) as owner:
                s=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
                self.assertTrue(s.switch('A',operation_id='noop')['receipt']['observed'])
                with self.assertRaises(UnsafeOperation):s.switch('B',operation_id='noop')
        self.assertEqual(self.b.calls,[])
    def test_same_id_other_page_is_conflict_even_already_observed(self):
        with OperationSession(self.app,window={'identifier':'window'}) as owner:
            s=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
            s.switch('B',operation_id='one')
            self.b.nodes['table']['AXIdentifier']='grid.A'
            with self.assertRaises(UnsafeOperation):s.switch('A',operation_id='one')
        self.assertEqual(len(self.b.calls),1)
    def test_durable_switch_id_does_not_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=Path(folder).resolve()/'ops.db'
            for _ in range(2):
                with OperationSession(self.app,window={'identifier':'window'},journal=journal) as owner:
                    session=PageSession(self.app,window={'identifier':'window'},pages=self.pages,operations=owner)
                    result=session.switch('B',operation_id='page-1')
                    self.assertEqual(result['page'],'B')
        self.assertEqual(self.b.calls,[('b','AXPress')])
