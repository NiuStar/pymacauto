import unittest
from collections import Counter
from pymacauto import Application,UnsafeOperation,AXError,AttributeUnsupported
from pymacauto.query_context import QueryContext
from test_core import MemoryAX

class QueryContextTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.calls=Counter();original=self.b.get
        def get(ref,attr):self.calls[(ref,attr)]+=1;return original(ref,attr)
        self.b.get=get;self.app=Application.connect(pid=42,backend=self.b)
    def test_phase_reuses_structural_not_values(self):
        with QueryContext(self.app) as q:
            self.assertEqual(q.get('a','AXRole'),'AXButton')
            self.assertEqual(q.get('a','AXRole'),'AXButton')
            self.b.nodes['a']['AXValue']='first'
            self.assertEqual(q.get('a','AXValue'),'first')
            self.b.nodes['a']['AXValue']='second'
            self.assertEqual(q.get('a','AXValue'),'second')
        self.assertEqual(self.calls[('a','AXRole')],1)
        self.assertEqual(self.calls[('a','AXValue')],2)
    def test_new_phase_sees_rebuild_and_closed_phase_refuses(self):
        with QueryContext(self.app) as q:self.assertEqual(q.get('a','AXRole'),'AXButton')
        self.b.nodes['a']['AXRole']='AXTextField'
        with QueryContext(self.app) as fresh:self.assertEqual(fresh.get('a','AXRole'),'AXTextField')
        with self.assertRaises(UnsafeOperation):q.get('a','AXRole')
    def test_secure_value_never_reaches_backend(self):
        self.b.nodes['a']['AXSubrole']='AXSecureTextField'
        with QueryContext(self.app) as q:
            with self.assertRaises(UnsafeOperation):q.get('a','AXValue')
        self.assertEqual(self.calls[('a','AXValue')],0)
    def test_readonly_interface_rejects_input(self):
        with QueryContext(self.app) as q:
            with self.assertRaises(UnsafeOperation):q.set('a','AXValue','x')
            with self.assertRaises(UnsafeOperation):q.perform('a','AXPress')
    def test_optional_does_not_hide_stale(self):
        def fail(*args):raise AXError('read',-25202)
        self.b.get=fail
        with QueryContext(self.app) as q:
            with self.assertRaises(AXError):q.get('a','AXRole')
    def test_public_input_cannot_cross_read_phase(self):
        target=self.app.child_window(identifier='apply')
        with QueryContext(self.app):
            with self.assertRaises(UnsafeOperation):target.click()
            with self.assertRaises(UnsafeOperation):target.set_value('x')
        self.assertEqual(self.b.calls,[])
    def test_bool_and_integer_selector_plans_are_distinct(self):
        self.b.nodes['a']['AXValue']=1
        from pymacauto.core import _matches
        with QueryContext(self.app):
            self.assertFalse(_matches(self.b,'a',{'value':True}))
            self.assertTrue(_matches(self.b,'a',{'value':1}))
    def test_copied_context_thread_cannot_reuse_evidence(self):
        import threading,contextvars
        errors=[]
        with QueryContext(self.app) as q:
            ctx=contextvars.copy_context()
            def read():
                try:q.get('a','AXRole')
                except Exception as exc:errors.append(exc)
            t=threading.Thread(target=lambda:ctx.run(read));t.start();t.join()
        self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],UnsafeOperation)
    def test_cached_arrays_return_copies(self):
        with QueryContext(self.app) as q:
            refs=q.get('window','AXChildren');refs.clear()
            self.assertEqual(q.get('window','AXChildren'),['a','b'])
