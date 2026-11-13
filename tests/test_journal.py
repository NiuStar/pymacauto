import tempfile
from pathlib import Path
import unittest
from pymacauto import Application,Condition,UnsafeOperation
from pymacauto.operations import OperationSession
from test_core import MemoryAX

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ops.sqlite'
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window']
        self.b.nodes['window']['AXIdentifier']='win'
        self.b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        self.app=Application.connect(pid=42,backend=self.b)
        self.target=self.app.child_window(identifier='apply')
        self.post=Condition(self.app.child_window(identifier='result'),value='after')
    def session(self):return OperationSession(self.app,window={'identifier':'win'},journal=self.path)
    def test_reopen_uncertain_never_dispatches_again(self):
        with self.session() as s:
            result=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        with self.session() as s:
            recovered=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(result['status'],'DISPATCHED_UNCONFIRMED')
        self.assertEqual(recovered['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(len(self.b.calls),1)
    def test_same_id_different_request_refused(self):
        with self.session() as s:
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        with self.session() as s:
            with self.assertRaises(UnsafeOperation):
                s.execute(self.app.child_window(identifier='result'),postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(len(self.b.calls),1)
    def test_corrupt_stage_cannot_authorize_dispatch(self):
        with self.session() as s:
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
            with s.journal.db:s.journal.db.execute("UPDATE operations SET stage='unknown',receipt=NULL")
        with self.session() as s:
            with self.assertRaises(UnsafeOperation):s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(len(self.b.calls),1)
    def test_intent_write_failure_prevents_action(self):
        from unittest.mock import patch
        with self.session() as s:
            with patch.object(s.journal,'intent',side_effect=OSError('disk full')):
                result=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(result['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(self.b.calls,[])
    def test_pid_reuse_refuses_dispatch(self):
        self.b.process_identity=lambda pid:{'pid':pid,'launch':1}
        with self.session() as s:
            self.b.process_identity=lambda pid:{'pid':pid,'launch':2}
            result=s.execute(self.target,postcondition=self.post,operation_id='new',timeout=0)
        self.assertEqual(result['status'],'NOT_DISPATCHED');self.assertEqual(self.b.calls,[])
    def test_terminal_write_failure_leaves_intent_to_block_replay(self):
        from unittest.mock import patch
        with self.session() as s:
            with patch.object(s.journal,'finish',side_effect=OSError('disk full')):
                result=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertIn('persistence_error',result)
        with self.session() as s:again=s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.assertEqual(again['status'],'DISPATCHED_UNCONFIRMED');self.assertEqual(len(self.b.calls),1)
    def test_missing_authority_table_does_not_reinitialize(self):
        with self.session() as s:
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
            with s.journal.db:s.journal.db.execute('ALTER TABLE operations RENAME TO lost_operations')
        with self.assertRaises(UnsafeOperation):self.session()
        self.assertEqual(len(self.b.calls),1)
    def test_prepared_record_cannot_claim_confirmation(self):
        import json
        with self.session() as s:
            s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
            with s.journal.db:
                s.journal.db.execute("UPDATE operations SET stage='PREPARED',receipt=?",(json.dumps({'operation_id':'one','status':'CONFIRMED','verified':True,'dispatch_attempted':True,'attempts':1}),))
        with self.session() as s:
            with self.assertRaises(UnsafeOperation):s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
    def test_recover_is_observation_only(self):
        with self.session() as s:s.execute(self.target,postcondition=self.post,operation_id='one',timeout=0)
        self.b.nodes['b']['AXValue']='after'
        with self.session() as s:
            result=s.recover('one',self.target,postcondition=self.post,timeout=0)
        self.assertEqual(result['status'],'RECOVERY_OBSERVED')
        self.assertEqual(len(self.b.calls),1)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
