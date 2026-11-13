import unittest
from pymacauto import Application,AttributeUnsupported,UnsafeOperation,Condition
from pymacauto.core import Element
from pymacauto.query_context import QueryContext
from test_core import MemoryAX

class QueryFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.app=Application.connect(pid=42,backend=self.b)
    def test_changed_secure_role_refuses_direct_content_without_reading_it(self):
        reads=[];original=self.b.get
        def get(ref,attr):reads.append((ref,attr));return original(ref,attr)
        self.b.get=get
        with QueryContext(self.app) as q:
            q.get('a','AXSubrole')
            self.b.nodes['a']['AXSubrole']='AXSecureTextField'
            for attr in ('AXValue','AXSelectedText','AXTitle'):
                with self.subTest(attr=attr):
                    with self.assertRaises(UnsafeOperation):Element(self.app,'a').get(attr)
                self.assertNotIn(('a',attr),reads)
    def test_required_window_relation_unsupported_is_not_gone(self):
        original=self.b.get
        def get(ref,attr):
            if attr=='AXWindows':raise AttributeUnsupported('unsupported relation')
            return original(ref,attr)
        self.b.get=get
        locator=self.app.locator_path([{'relation':'window','selector':{'title':'Demo'}}])
        with self.assertRaises(AttributeUnsupported):Condition(locator,state='gone').check()
    def test_required_read_not_satisfied_by_cached_optional_missing(self):
        original=self.b.get
        def get(ref,attr):
            if attr=='AXWindows':raise AttributeUnsupported('unsupported relation')
            return original(ref,attr)
        self.b.get=get
        locator=self.app.locator_path([{'relation':'window','selector':{'title':'Demo'}}])
        with QueryContext(self.app) as q:
            self.assertIsNone(q.get('app','AXWindows'))
            with self.assertRaises(AttributeUnsupported):locator.resolve()
