"""Explicit direct-child scope policy; native qualification runs separately."""
import unittest
from pymacauto import AmbiguousMatch,ElementNotFound,WaitTimeout
from pymacauto.pages import PageSession
import test_pages

class ScopedPagesTests(unittest.TestCase):
    def setUp(self):
        fixture=test_pages.PageTests();fixture.setUp()
        self.b,self.app,self.pages=fixture.b,fixture.app,fixture.pages
        self.b.nodes['window']['AXChildren']=['a','b','container','noise']
        self.b.nodes['container']={'AXRole':'AXScrollArea','AXIdentifier':'container','AXChildren':['table']}
        self.b.nodes['noise']={'AXRole':'AXGroup','AXChildren':['bad']}
        self.b.nodes['bad']={'AXRole':'AXTable','AXIdentifier':'grid.A','AXColumns':['col']}
    def session(self):
        return PageSession(self.app,window={'identifier':'window'},pages=self.pages,
                           content_path=[{'role':'AXScrollArea','identifier':'container'}],
                           trigger_children_only=True)
    def test_only_explicit_content_container_is_read(self):
        original=self.b.get;calls=[]
        def get(ref,attr):calls.append((ref,attr));return original(ref,attr)
        self.b.get=get
        s=self.session()
        self.assertEqual(s.switch('B')['page'],'B')
        self.assertEqual(s.switch('A')['page'],'A')
        # Global modal safety scans structural nodes, but page detection must
        # not read an out-of-scope table's headers or data.
        self.assertFalse(any(ref in ('noise','bad') and attr in ('AXColumns','AXRows','AXValue') for ref,attr in calls))
        self.assertTrue(s.last_receipt['verified'])
    def test_duplicate_container_refuses_before_click(self):
        self.b.nodes['duplicate']=dict(self.b.nodes['container'])
        self.b.nodes['window']['AXChildren'].append('duplicate')
        with self.assertRaises(AmbiguousMatch):self.session().switch('B')
        self.assertEqual(self.b.calls,[])
    def test_direct_trigger_ambiguity_refuses(self):
        self.b.nodes['other']=dict(self.b.nodes['b'])
        self.b.nodes['window']['AXChildren'].append('other')
        with self.assertRaises(AmbiguousMatch):self.session().switch('B')
        self.assertEqual(self.b.calls,[])
    def test_nested_trigger_not_silently_accepted(self):
        self.b.nodes['window']['AXChildren'].remove('b')
        self.b.nodes['noise']['AXChildren'].append('b')
        with self.assertRaises(WaitTimeout):self.session().switch('B',timeout=0)
        self.assertEqual(self.b.calls,[])
    def test_rebuilt_container_reacquired(self):
        s=self.session();s.detect()
        self.b.nodes['window']['AXChildren'].remove('container')
        self.b.nodes['window']['AXChildren'].append('new-container')
        self.b.nodes['new-container']=dict(self.b.nodes['container'])
        self.assertEqual(s.switch('B')['page'],'B')
    def test_default_scope_still_detects_full_window_ambiguity(self):
        with self.assertRaises(AmbiguousMatch):
            PageSession(self.app,window={'identifier':'window'},pages=self.pages).detect()
    def test_invalid_scope_policy_rejected(self):
        with self.assertRaises(ValueError):
            PageSession(self.app,window={'identifier':'window'},pages=self.pages,content_path='not-a-path')
        with self.assertRaises(ValueError):
            PageSession(self.app,window={'identifier':'window'},pages=self.pages,trigger_children_only='yes')

    def test_direct_child_budget_refuses(self):
        from pymacauto import SearchLimitExceeded
        self.app.max_nodes=2
        with self.assertRaises(SearchLimitExceeded):self.session().detect()

    def test_regex_content_path_across_rebuilds(self):
        s=PageSession(self.app,window={'identifier':'window'},pages=self.pages,
                      content_path=[{'role':'AXScrollArea','identifier_re':r'^container(?:2)?$'}],
                      trigger_children_only=True)
        self.assertEqual(s.detect()['page'],'A')
        self.b.nodes['container']['AXIdentifier']='container2'
        self.assertEqual(s.switch('B')['page'],'B')

    def test_empty_content_path_works(self):
        self.b.nodes['window']['AXChildren'].remove('noise')
        self.assertEqual(PageSession(self.app,window={'identifier':'window'},pages=self.pages,
                                    content_path=[],trigger_children_only=True).switch('B')['page'],'B')
