"""Native baseline/candidate measurement on owned AppKit data-heavy pages."""
from collections import Counter
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
if '--installed' not in sys.argv:sys.path.insert(0,str(ROOT/'src'))
from pymacauto import Application
from pymacauto.pages import PageSession
from pymacauto.query import window_scope


def main():
    bundle=ROOT/'build/perf/MacAXPerf.app/Contents'
    binary=bundle/'MacOS/MacAXPerf';binary.parent.mkdir(parents=True,exist_ok=True)
    (bundle/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.pymacauto.perf',
      'CFBundleExecutable':'MacAXPerf','CFBundleName':'MacAXPerf','CFBundlePackageType':'APPL','LSUIElement':True}))
    subprocess.run(['swiftc',str(ROOT/'tests/native/Performance.swift'),'-o',str(binary),'-framework','AppKit'],check=True,timeout=90)
    from AppKit import NSWorkspace
    from Foundation import NSRunLoop,NSDate
    def front():
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.05))
        return int(NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier())
    before=front();child=subprocess.Popen([str(binary)])
    results=[]
    try:
        deadline=time.monotonic()+15
        while True:
            try:
                app=Application.connect(pid=child.pid,max_nodes=10000,max_depth=80)
                app.child_window(identifier='page.A').resolve();break
            except Exception:
                if child.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.1)
        b=app.backend;counts=Counter();original=b.get
        def counted(ref,attr):counts['get']+=1;return original(ref,attr)
        b.get=counted
        profile={name:{'trigger':{'role':'AXButton','identifier':'page.'+name},
                       'table':{'role':'AXTable','identifier':'grid.'+name},
                       'headers':['Field0','Field1','Field2','Field3','Field4']} for name in ('A','B')}
        session=PageSession(app,window={'identifier':'perf.window'},pages=profile)
        for round_index in range(3):
            for mode in (('baseline','candidate') if round_index % 2 == 0 else ('candidate','baseline')):
                counts.clear();start=time.monotonic();snapshots=[]
                for name in ('B','A'):
                    if mode=='baseline':
                        app.child_window(role='AXButton',identifier='page.'+name).click()
                        table=app.child_window(role='AXTable',identifier='grid.'+name).resolve().ref
                    else:
                        table=session.switch(name)['table']
                    # Independent exact native value sampling, same for both modes.
                    rows=b.get(table,'AXRows');values=[]
                    for row in rows:
                        fields=[]
                        for cell in b.get(row,'AXChildren'):
                            try:value=b.get(cell,'AXValue')
                            except Exception:value=None
                            if value is None:
                                children=b.get(cell,'AXChildren') or []
                                value=[b.get(c,'AXValue') for c in children]
                            fields.append(value)
                        values.append(fields)
                    assert len(values)==100 and all(len(row)==5 for row in values)
                    for ri,row in enumerate(values):
                        for ci,value in enumerate(row):
                            expected=f'{name}:{ri}:c{ci}'
                            assert value==expected or value==[expected], (ri,ci,value)
                    snapshots.append(values)
                results.append({'round':round_index,'mode':mode,'elapsed':time.monotonic()-start,
                                'get_calls':counts['get'],'rows':len(rows),'values':snapshots})
        for i in range(0,len(results),2):
            assert results[i]['values']==results[i+1]['values'],'Native value mismatch'
        assert all(r['rows']==100 for r in results)
        for r in results:
            import hashlib
            r['data_sha256']=hashlib.sha256(json.dumps(r.pop('values'),ensure_ascii=False).encode()).hexdigest()
        config_path=ROOT/'build/perf/pages.json'
        config_path.write_text(json.dumps({'window':{'identifier':'perf.window'},'pages':profile}))
        cli_env=({**os.environ,'PYTHONPATH':str(ROOT/'src')} if '--installed' not in sys.argv else
                 {k:v for k,v in os.environ.items() if k!='PYTHONPATH'})
        cli=subprocess.run([sys.executable,'-m','pymacauto','page','--pid',str(child.pid),
            '--config',str(config_path),'--to','B','--execute'],capture_output=True,text=True,env=cli_env,timeout=15)
        assert cli.returncode==0,cli.stdout+cli.stderr
        assert json.loads(cli.stdout)['result']['page']=='B'
        assert session.detect()['page']=='B'
        assert PageSession.from_config(app,json.loads(config_path.read_text())).switch('A')['page']=='A'
        assert front()==before,'Fixture changed foreground'
        assert child.poll() is None,'Fixture exited early'
        print(json.dumps({'status':'PASS','fixture':'owned_appkit_100x5','measurements':results,
                          'foreground_preserved':True,'cli_page_verified':True,'config_constructor_verified':True,'module':__import__('pymacauto.query',fromlist=['']).__file__}))
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)

if __name__=='__main__':main()
