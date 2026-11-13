import unittest
from pymacauto.focus import ForegroundGuard
from pymacauto import Application,Condition
from test_core import MemoryAX

class ForegroundGuardTests(unittest.TestCase):
    def test_transition_latches_and_preserves_first_identity(self):
        state=[{'pid':10,'bundle_id':'test.original','launch_epoch':1}]
        guard=ForegroundGuard(lambda:dict(state[0]))
        self.assertFalse(guard.is_set())
        state[0]={'pid':20,'bundle_id':'test.changed','launch_epoch':2}
        self.assertTrue(guard.is_set())
        state[0]={'pid':10,'bundle_id':'test.original','launch_epoch':1}
        self.assertTrue(guard.is_set())
        self.assertEqual(guard.report()['first_change']['after']['pid'],20)
    def test_changed_during_intent_prevents_native_dispatch(self):
        import tempfile
        from pathlib import Path
        state=[{'pid':10,'bundle_id':'test.original'}]
        guard=ForegroundGuard(lambda:dict(state[0]))
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        app=Application.connect(pid=42,backend=b)
        with tempfile.TemporaryDirectory() as directory:
            with app.session(identifier='win',journal=Path(directory).resolve()/'ops.db',stop=guard) as s:
                original=s.journal.intent
                def intent(op):original(op);state[0]={'pid':20,'bundle_id':'test.changed'}
                s.journal.intent=intent
                receipt=s.execute(app.child_window(identifier='apply'),postcondition=Condition(app.child_window(identifier='result'),value='after'),operation_id='one',timeout=0)
        self.assertEqual(b.calls,[])
        self.assertEqual(receipt['error_category'],'STOPPED')
        self.assertEqual(guard.report()['first_change']['after']['bundle_id'],'test.changed')
    def test_same_pid_different_identity_stops(self):
        state=[{'pid':10,'bundle_id':'test.original','launch_epoch':1}]
        guard=ForegroundGuard(lambda:dict(state[0]))
        state[0]['launch_epoch']=2
        self.assertTrue(guard.is_set())
    def test_notification_center_transition_is_not_ignored(self):
        state=[{'pid':1052,'bundle_id':'com.google.Chrome','launch_epoch':1}]
        guard=ForegroundGuard(lambda:dict(state[0]))
        state[0]={'pid':1849,'bundle_id':'com.apple.UserNotificationCenter','launch_epoch':None}
        self.assertTrue(guard.is_set())
        self.assertEqual(guard.report()['first_change']['after'],state[0])
        state[0]={'pid':1052,'bundle_id':'com.google.Chrome','launch_epoch':1}
        self.assertTrue(guard.is_set())
    def test_unavailable_identity_is_not_approved(self):
        with self.assertRaises(ValueError):ForegroundGuard(lambda:None)
