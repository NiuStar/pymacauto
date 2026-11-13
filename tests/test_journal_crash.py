"""Real owned child SIGKILL tests; synthetic UI explicitly not native AX."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WORKER=r'''
import os,sys
from pathlib import Path
from pymacauto import Application,Condition
from pymacauto.operations import OperationSession
from test_core import MemoryAX
root=Path(sys.argv[1]);phase=sys.argv[2]
b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
b.nodes['b'].update(AXIdentifier='result',AXValue='before')
a=Application.connect(pid=42,backend=b)
s=OperationSession(a,window={'identifier':'win'},journal=root/'ops.db')
def barrier():
 print('READY',flush=True);sys.stdin.read(1)
original=s.journal.intent
if phase=='prepared':s.journal.intent=lambda operation_id:barrier()
if phase=='intent':
 def intent(operation_id):original(operation_id);barrier()
 s.journal.intent=intent
def perform(*args):
 fd=os.open(root/'calls',os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
 with os.fdopen(fd,'a') as f:f.write('dispatch\n');f.flush();os.fsync(f.fileno())
 if phase=='after':barrier()
b.perform=perform
r=s.execute(a.child_window(identifier='apply'),postcondition=Condition(a.child_window(identifier='result'),value='after'),operation_id='one',timeout=0)
print(__import__('json').dumps(r),flush=True)
s.close()
'''

class CrashTests(unittest.TestCase):
    def test_sigkill_at_each_durable_boundary_never_replays(self):
        for phase in ('prepared','intent','after'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                env=dict(os.environ)
                env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).resolve().parent),env.get('PYTHONPATH','')])
                child=subprocess.Popen([sys.executable,'-u','-c',WORKER,folder,phase],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
                try:
                    import selectors
                    selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ)
                    try:self.assertTrue(selector.select(10),'Child did not reach selected boundary')
                    finally:selector.close()
                    self.assertEqual(child.stdout.readline().strip(),'READY')
                    child.kill();child.communicate(timeout=5)
                    result=subprocess.run([sys.executable,'-u','-c',WORKER,folder,'retry'],capture_output=True,text=True,env=env,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    receipt=json.loads(result.stdout)
                    self.assertIn(receipt['status'],('RECOVERY_REQUIRED','DISPATCHED_UNCONFIRMED'))
                    calls=Path(folder)/'calls'
                    self.assertEqual(calls.read_text().count('dispatch') if calls.exists() else 0,1 if phase=='after' else 0)
                finally:
                    if child.poll() is None:child.kill();child.communicate(timeout=5)
