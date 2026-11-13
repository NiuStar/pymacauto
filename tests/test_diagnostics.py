import io
import json
import tempfile
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest
from pymacauto import Application,Condition
from pymacauto.operations import OperationSession
from pymacauto.journal import audit_journal
from pymacauto.cli import main
from test_core import MemoryAX

class DiagnosticsTests(unittest.TestCase):
    def test_stopped_recovery_refuses_observation(self):
        import threading
        from pymacauto import UnsafeOperation
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        a=Application.connect(pid=42,backend=b);target=a.child_window(identifier='apply')
        post=Condition(a.child_window(identifier='apply'),value='after')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'ops.db'
            with OperationSession(a,window={'identifier':'win'},journal=path) as s:s.execute(target,postcondition=post,operation_id='one',timeout=0)
            stop=__import__('threading').Event();stop.set()
            with OperationSession(a,window={'identifier':'win'},journal=path,readonly=True,stop=stop) as s:
                with self.assertRaises(UnsafeOperation):s.recover('one',target,postcondition=post,timeout=0)
    def test_cli_observe_and_inspect_are_readonly(self):
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        a=Application.connect(pid=42,backend=b)
        target=a.window(identifier='win').child_window(identifier='apply')
        post=Condition(a.window(identifier='win').child_window(identifier='result'),value='after')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'ops.db'
            with OperationSession(a,window={'identifier':'win'},journal=path) as session:
                session.execute(target,postcondition=post,operation_id='one',timeout=0)
            before={p.name:p.read_bytes() for p in path.parent.iterdir()}
            b.nodes['b']['AXValue']='after'
            args=['journal-observe','--pid','42','--window','{"identifier":"win"}',
                  '--target','{"identifier":"apply"}','--expect','{"identifier":"result"}',
                  '--expect-value','after','--journal',str(path),'--operation-id','one','--timeout','0']
            output=io.StringIO()
            with patch('pymacauto.native.NativeBackend',return_value=b),redirect_stdout(output):code=main(args)
            self.assertEqual(code,0,output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['result']['status'],'RECOVERY_OBSERVED')
            audit=audit_journal(path)
            self.assertEqual(len(audit['operations']),1)
            self.assertEqual(before,{p.name:p.read_bytes() for p in path.parent.iterdir()})
            self.assertEqual(len(b.calls),1)
