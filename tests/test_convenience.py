import unittest
from pymacauto import Application,Element,AmbiguousMatch,ElementNotFound
from test_core import MemoryAX

class ConvenienceTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window']
        self.app=Application.connect(pid=42,backend=self.b)
    def test_window_children_and_scoped_locator(self):
        windows=self.app.windows()
        self.assertEqual([w.ref for w in windows],['window'])
        self.assertEqual(len(windows[0].children(role='AXButton')),2)
        self.assertEqual(windows[0].child_window(identifier='apply').resolve().ref,'a')
    def test_element_scope_does_not_match_outside_siblings(self):
        self.b.nodes['app']['AXChildren'].append('outside')
        self.b.nodes['outside']=dict(self.b.nodes['a'])
        self.assertEqual(self.app.windows()[0].child_window(identifier='apply').resolve().ref,'a')
        with self.assertRaises(AmbiguousMatch):self.app.child_window(identifier='apply').resolve()
    def test_nested_element_locator_preserves_root_scope(self):
        self.b.nodes['window']['AXChildren']=['group']
        self.b.nodes['group']={'AXRole':'AXGroup','AXIdentifier':'group','AXChildren':['a']}
        self.assertEqual(self.app.windows()[0].child_window(identifier='group').child_window(identifier='apply').resolve().ref,'a')
    def test_value_convenience(self):
        self.b.nodes['a']['AXValue']='原样值'
        self.assertEqual(self.app.child_window(identifier='apply').get_value(),'原样值')
        self.assertEqual(self.app.child_window(identifier='apply').resolve().get_value(),'原样值')
    def test_scoped_descendants(self):
        window=self.app.windows()[0]
        self.assertEqual([e.ref for e in window.descendants(identifier='apply')],['a'])
        self.assertEqual([e.ref for e in window.children(identifier='apply')],['a'])
