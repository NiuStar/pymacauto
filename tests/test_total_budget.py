import time
import unittest
from pymacauto import Application,Condition,AXError
from pymacauto.operations import OperationSession
from test_core import MemoryAX

class TotalBudgetTests(unittest.TestCase):
    def fixture(self):
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        a=Application.connect(pid=42,backend=b)
        return b,a,OperationSession(a,window={'identifier':'win'})
    def test_slow_preflight_does_not_dispatch_after_budget(self):
        b,a,s=self.fixture();original=s._guard
        def slow(target):time.sleep(.02);return original(target)
        s._guard=slow
        receipt=s.execute(a.child_window(identifier='apply'),postcondition=Condition(a.child_window(identifier='result'),value='after'),timeout=.005)
        self.assertEqual(b.calls,[])
        self.assertEqual(receipt['error_category'],'DEADLINE_EXCEEDED')
        self.assertEqual(receipt['error_stage'],'pre_dispatch')
    def test_multistep_final_guard_expiry_blocks_next_input(self):
        b,a,s=self.fixture();b.nodes['a'].update(AXRole='AXCheckBox',AXValue=0)
        original=s._guard_same;checks=[]
        def guard(target,element):
            original(target,element);checks.append(1)
            if len(checks)==2:time.sleep(.03)
        s._guard_same=guard
        r=s.apply(a.child_window(identifier='apply'),'check',value=True,timeout=.02)
        self.assertEqual(b.calls,[])
        self.assertEqual(r['error_category'],'DEADLINE_EXCEEDED')
    def test_stop_classified_without_dispatch(self):
        import threading
        b,a,s=self.fixture();s.stop=threading.Event();s.stop.set()
        r=s.execute(a.child_window(identifier='apply'),postcondition=Condition(a.child_window(identifier='result'),value='after'),timeout=1)
        self.assertEqual(r['error_category'],'STOPPED');self.assertEqual(b.calls,[])
    def test_native_code_preserved_separate_from_category(self):
        b,a,s=self.fixture()
        def fail(ref,action):raise AXError('AXPress',-25204)
        b.perform=fail
        r=s.execute(a.child_window(identifier='apply'),postcondition=Condition(a.child_window(identifier='result'),value='after'),timeout=0)
        self.assertEqual(r['error_category'],'NATIVE_ERROR')
        self.assertEqual(r['native_error']['code'],-25204)
        self.assertTrue(r['dispatch_attempted'])
