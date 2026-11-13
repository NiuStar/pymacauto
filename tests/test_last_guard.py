import tempfile
from pathlib import Path
import unittest
from pymacauto import Application,Condition
from pymacauto.operations import OperationSession
from test_core import MemoryAX

class LastGuardTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window'];self.b.nodes['window']['AXIdentifier']='win'
        self.b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        self.a=Application.connect(pid=42,backend=self.b)
        self.target=self.a.child_window(identifier='apply');self.post=Condition(self.a.child_window(identifier='result'),value='after')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def test_sheet_inserted_during_intent_blocks_native_input(self):
        with OperationSession(self.a,window={'identifier':'win'},journal=Path(self.temp.name).resolve()/'ops.db') as s:
            original=s.journal.intent
            def intent(op):original(op);self.b.nodes['window']['AXSheets']=['sheet']
            s.journal.intent=intent
            r=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(r['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(self.b.calls,[])
    def test_target_replaced_during_intent_blocks_input(self):
        with OperationSession(self.a,window={'identifier':'win'},journal=Path(self.temp.name).resolve()/'ops.db') as s:
            original=s.journal.intent
            def intent(op):
                original(op);self.b.nodes['new']=dict(self.b.nodes['a']);self.b.nodes['window']['AXChildren']=['new','b']
            s.journal.intent=intent
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(self.b.calls,[])
    def test_precondition_changed_during_intent_blocks_input(self):
        self.b.nodes['b']['AXValue']='before'
        pre=Condition(self.a.child_window(identifier='result'),value='before')
        with OperationSession(self.a,window={'identifier':'win'},journal=Path(self.temp.name).resolve()/'ops.db') as s:
            original=s.journal.intent
            def intent(op):original(op);self.b.nodes['b']['AXValue']='changed'
            s.journal.intent=intent
            s.execute(self.target,precondition=pre,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(self.b.calls,[])
    def test_protected_index_requires_expected_count(self):
        target=self.a.window(identifier='win').child(role='AXButton',index=0)
        with OperationSession(self.a,window={'identifier':'win'}) as s:
            receipt=s.execute(target,postcondition=self.post,timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_stop_set_during_intent_blocks_input(self):
        import threading
        stop=threading.Event()
        with OperationSession(self.a,window={'identifier':'win'},journal=Path(self.temp.name).resolve()/'ops.db',stop=stop) as s:
            original=s.journal.intent
            def intent(op):original(op);stop.set()
            s.journal.intent=intent
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(self.b.calls,[])
    def test_stop_signal_blocks_mutation(self):
        import threading
        stop=threading.Event();stop.set()
        with OperationSession(self.a,window={'identifier':'win'},stop=stop) as s:
            r=s.execute(self.target,postcondition=self.post,timeout=0)
        self.assertEqual(r['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
