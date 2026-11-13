import unittest
from pymacauto import Application
from pymacauto.operations import OperationSession,Condition
from test_core import MemoryAX

class OperationTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window']
        self.b.nodes['window']['AXIdentifier']='win'
        self.app=Application.connect(pid=42,backend=self.b)
        self.s=OperationSession(self.app,window={'identifier':'win'})
        self.target=self.app.child_window(identifier='apply')
        self.b.nodes['b']['AXValue']='before';self.b.nodes['b']['AXIdentifier']='other'
        self.after=Condition(self.app.child_window(identifier='other'),value='after')
    def test_press_single_dispatch_independent_confirmation(self):
        def perform(ref,action):
            self.b.calls.append((ref,action));self.b.nodes['b']['AXValue']='after'
        self.b.perform=perform
        r=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'CONFIRMED');self.assertEqual(len(self.b.calls),1)
    def test_unconfirmed_dispatch_never_repeats(self):
        r=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(len(self.b.calls),1)
    def test_unknown_sheet_prevents_input(self):
        self.b.nodes['window']['AXSheets']=['sheet']
        self.b.nodes['sheet']={'AXRole':'AXSheet'}
        r=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_false_precondition_stops(self):
        r=self.s.execute(self.target,precondition=self.after,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_duplicate_id_never_dispatches_twice(self):
        first=self.s.execute(self.target,postcondition=self.after,timeout=0,operation_id='request-1')
        second=self.s.execute(self.target,postcondition=self.after,timeout=0,operation_id='request-1')
        self.assertEqual(first,second);self.assertEqual(len(self.b.calls),1)
    def test_close_refuses_new_dispatch(self):
        self.s.close()
        r=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_same_app_second_session_cannot_enter_during_dispatch(self):
        other=OperationSession(self.app,window={'identifier':'win'})
        receipts=[]
        def perform(ref,action):
            self.b.calls.append((ref,action))
            receipts.append(other.execute(self.target,postcondition=self.after,timeout=0))
        self.b.perform=perform
        self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(len(self.b.calls),1)
        self.assertEqual(receipts[0]['status'],'NOT_DISPATCHED')
    def test_cross_window_target_is_rejected(self):
        self.b.nodes['app']['AXChildren'].append('foreign')
        self.b.nodes['foreign']=dict(self.b.nodes['a'],AXIdentifier='foreign')
        receipt=self.s.execute(self.app.child_window(identifier='foreign'),postcondition=self.after,timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_modal_window_is_rejected(self):
        self.b.nodes['app']['AXWindows'].append('modal')
        self.b.nodes['modal']={'AXRole':'AXWindow','AXModal':True}
        receipt=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_interrupt_retains_uncertain_receipt_before_reraise(self):
        def interrupted(ref,action):
            self.b.calls.append((ref,action));raise KeyboardInterrupt
        self.b.perform=interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.s.execute(self.target,postcondition=self.after,operation_id='interrupt',timeout=0)
        retry=self.s.execute(self.target,postcondition=self.after,operation_id='interrupt',timeout=0)
        self.assertEqual(retry['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(len(self.b.calls),1)
    def test_preexisting_postcondition_not_claimed_as_effect(self):
        self.b.nodes['b']['AXValue']='after'
        receipt=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_permission_failure_never_reaches_dispatch(self):
        from pymacauto import PermissionDenied
        original=self.b.get
        def get(ref,attribute):
            if attribute=='AXWindows':raise PermissionDenied('revoked')
            return original(ref,attribute)
        self.b.get=get
        receipt=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_dispatch_error_is_uncertain_not_safe_to_retry(self):
        def broken(*args):raise RuntimeError('sensitive payload')
        self.b.perform=broken
        r=self.s.execute(self.target,postcondition=self.after,timeout=0)
        self.assertEqual(r['status'],'DISPATCHED_UNCONFIRMED')
        self.assertNotIn('sensitive',str(r))
