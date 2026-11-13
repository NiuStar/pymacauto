import unittest
from pymacauto import Application,AXError,AmbiguousMatch,WaitTimeout
from pymacauto.pages import PageSession
from pymacauto.query import window_scope
from test_core import MemoryAX

class PageTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window']
        self.b.nodes['window']['AXIdentifier']='window'
        self.b.nodes['window']['AXChildren']=['a','b','table']
        self.b.nodes['a']['AXIdentifier']='page.A'
        self.b.nodes['b']['AXIdentifier']='page.B'
        self.b.nodes['table']={'AXRole':'AXTable','AXIdentifier':'grid.A','AXColumns':['col'],'AXChildren':['cell']}
        self.b.nodes['col']={'AXHeader':'header'}
        self.b.nodes['header']={'AXTitle':'Column'}
        self.b.nodes['cell']={'AXRole':'AXStaticText','AXValue':'unchanged'}
        self.app=Application.connect(pid=42,backend=self.b)
        self.pages={name:{'trigger':{'identifier':'page.'+name,'role':'AXButton'},
                         'table':{'identifier':'grid.'+name,'role':'AXTable'},'headers':['Column']} for name in ('A','B')}
        def perform(ref,action):
            self.b.calls.append((ref,action))
            self.b.nodes['table']['AXIdentifier']='grid.'+('A' if ref=='a' else 'B')
        self.b.perform=perform
        self.session=PageSession(self.app,window={'identifier':'window'},pages=self.pages)
    def test_switch_verifies_caller_fingerprint_and_restore(self):
        self.assertEqual(self.session.switch('B')['page'],'B')
        self.assertEqual(self.session.switch('A')['page'],'A')
        self.assertEqual(self.b.calls,[('b','AXPress'),('a','AXPress')])
    def test_already_on_page_does_not_click(self):
        self.session.switch('A');self.assertEqual(self.b.calls,[])
    def test_ambiguous_trigger_never_clicks(self):
        self.b.nodes['duplicate']=dict(self.b.nodes['b'])
        self.b.nodes['window']['AXChildren'].append('duplicate')
        with self.assertRaises(AmbiguousMatch):self.session.switch('B')
        self.assertEqual(self.b.calls,[])
    def test_dispatch_error_not_retried(self):
        def broken(ref,action):
            self.b.calls.append((ref,action));raise AXError('press',-25204)
        self.b.perform=broken
        with self.assertRaises(AXError):self.session.switch('B')
        self.assertEqual(len(self.b.calls),1)
    def test_noop_action_times_out_not_confirmed(self):
        self.b.perform=lambda *a:self.b.calls.append(a)
        with self.assertRaises(WaitTimeout):self.session.switch('B',timeout=.001)
        self.assertEqual(len(self.b.calls),1)
    def test_duplicate_page_fingerprint_refuses(self):
        self.b.nodes['window']['AXChildren'].append('second')
        self.b.nodes['second']=dict(self.b.nodes['table'])
        with self.assertRaises(AmbiguousMatch):self.session.detect()
    def test_header_mismatch_not_page_success(self):
        self.b.nodes['header']['AXTitle']='Wrong'
        with self.assertRaises(WaitTimeout):self.session.wait(timeout=0)
    def test_full_table_selector_is_enforced(self):
        self.session.pages['A']['table']['title']='required'
        with self.assertRaises(WaitTimeout):self.session.wait(timeout=0)
    def test_full_table_selector_without_identifier(self):
        for page in self.session.pages.values():page['table']={'role':'AXTable'}
        self.session.pages['B']['headers']=['Other']
        self.assertEqual(self.session.detect()['page'],'A')

    def test_read_only_rebuild_error_requeries_then_recovers(self):
        original=self.b.get;count=0
        def get(ref,attr):
            nonlocal count
            if ref=='table' and attr=='AXIdentifier' and count==0:
                count+=1;raise AXError('read',-25202)
            return original(ref,attr)
        self.b.get=get
        self.assertEqual(self.session.wait(timeout=1)['page'],'A')
        self.assertEqual(self.session.read_errors,[{'operation':'read','code':-25202}])
    def test_unknown_trigger_rejected(self):
        with self.assertRaises(ValueError):self.session.wait(trigger='missing')

    def test_combined_detection_returns_unique_trigger_without_click(self):
        result=self.session.detect(trigger='B')
        self.assertEqual(result['page'],'A')
        self.assertEqual(result['trigger'],'b')
        self.assertEqual(self.b.calls,[])

    def test_config_constructor_and_malformed_inputs(self):
        config={'window':{'identifier':'window'},'pages':self.pages}
        self.assertEqual(PageSession.from_config(self.app,config).switch('B')['page'],'B')
        for invalid in (None,{}, {'window':{},'pages':{}}, {**config,'typo':True},
                        {**config,'pages':{'B':None}},
                        {**config,'pages':{'B':{**self.pages['B'],'headers':'Column'}}},
                        {**config,'pages':{'B':{**self.pages['B'],'typo':True}}},
                        {**config,'leaf_roles':'AXTable'}):
            with self.subTest(config=invalid):
                with self.assertRaises(ValueError):PageSession.from_config(self.app,invalid)

    def test_top_level_window_uses_windows_relation_only(self):
        self.b.nodes['app']['AXChildren']=[]
        self.assertEqual(window_scope(self.app,identifier='window').root,'window')
