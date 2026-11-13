import unittest
from pymacauto import Application,ElementNotFound,UnsafeOperation
from test_core import MemoryAX

class PathTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.a=Application.connect(pid=42,backend=self.b)
    def test_direct_type_filtered_zero_based_index(self):
        target=self.a.window(title='Demo').child(role='AXButton',index=1,expected_count=2)
        self.assertEqual(target.resolve().ref,'b')
    def test_each_level_and_depth_do_not_flatten(self):
        self.b.nodes['window']['AXChildren']=['group','b']
        self.b.nodes['group']={'AXRole':'AXGroup','AXChildren':['a']}
        loc=self.a.window(title='Demo').child(role='AXGroup',index=0,expected_count=1).child(role='AXButton',index=0,expected_count=1)
        self.assertEqual(loc.resolve().ref,'a')
        self.assertEqual(self.a.window(title='Demo').child(role='AXButton',index=0).resolve().ref,'b')
    def test_count_and_index_boundaries(self):
        with self.assertRaises(UnsafeOperation):self.a.window(title='Demo').child(role='AXButton',index=1,expected_count=3).resolve()
        with self.assertRaises(ElementNotFound):self.a.window(title='Demo').child(role='AXButton',index=2).resolve()
        for index in (-1,True,1.2):
            with self.assertRaises(ValueError):self.a.window(title='Demo').child(role='AXButton',index=index)
    def test_path_serializable_re_resolves(self):
        config=[{'relation':'descendant','selector':{'role':'AXWindow','title':'Demo'}},
                {'relation':'child','selector':{'role':'AXButton'},'index':1,'expected_count':2}]
        loc=self.a.locator_path(config)
        self.assertEqual(loc.resolve().ref,'b')
        self.b.nodes['new']=dict(self.b.nodes['b']);self.b.nodes['window']['AXChildren']=['a','new']
        self.assertEqual(loc.resolve().ref,'new')
    def test_index_fingerprint_rejects_same_count_reordering(self):
        loc=self.a.window(title='Demo').child(role='AXButton',index=0,expected_count=2,verify={'identifier':'apply'})
        self.b.nodes['window']['AXChildren']=['b','a']
        with self.assertRaises(UnsafeOperation):loc.resolve()
    def test_input_path_mutation_does_not_change_locator(self):
        config=[{'relation':'descendant','selector':{'identifier':'apply'}}]
        loc=self.a.locator_path(config)
        config[0]['selector']['identifier']='changed'
        self.assertEqual(loc.resolve().ref,'a')
    def test_malformed_path_refused(self):
        for path in ([],[{'relation':'child','selector':{},'index':0}],
                     [{'relation':'child','selector':{'role':'AXButton'},'index':0,'typo':1}]):
            with self.assertRaises(ValueError):self.a.locator_path(path)
