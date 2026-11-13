"""Repeat owned native acceptance; no target business-app mutation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--rounds',type=int,default=3)
p.add_argument('--installed',action='store_true')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if not 1<=a.rounds<=10000:p.error('rounds must be 1..10000')
fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
root=Path(__file__).resolve().parents[1]
records=[];ok=True
with os.fdopen(fd,'w') as out:
    for index in range(a.rounds):
        start=time.monotonic()
        cmd=[sys.executable,str(root/'scripts/native_check.py')]+(['--installed'] if a.installed else [])
        child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        timed_out=False
        try:stdout,stderr=child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            import signal
            timed_out=True;os.killpg(child.pid,signal.SIGKILL)
            stdout,stderr=child.communicate(timeout=5)
        try:receipt=json.loads(stdout)
        except ValueError:receipt={'status':'INVALID_RECEIPT'}
        passed=not timed_out and child.returncode==0 and receipt.get('status')=='PASS' and receipt.get('fixture_reaped') is True
        record={'round':index,'passed':passed,'elapsed_seconds':time.monotonic()-start,'receipt':receipt,
                'stderr':stderr[-2000:],'timed_out':timed_out}
        out.write(json.dumps(record,ensure_ascii=False)+'\n');out.flush();os.fsync(out.fileno())
        records.append(record)
        if not passed:ok=False;break
print(json.dumps({'status':'PASS' if ok else 'FAIL','completed_rounds':len(records),'requested_rounds':a.rounds,
                  'all_fixture_children_reaped':all(r['receipt'].get('fixture_reaped') for r in records)}))
raise SystemExit(0 if ok else 1)
