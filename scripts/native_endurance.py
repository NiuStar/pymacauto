"""Owned-window sustained acceptance plus optional current-panel THS reads.

No financial UI actions, activation or navigation. THS observations can change
naturally; every individual strict snapshot must pass. Raw rows are not logged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import threading
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=float,default=300)
    p.add_argument('--interval',type=float,default=2)
    p.add_argument('--ths-interval',type=float,default=60)
    p.add_argument('--allow-ths-read',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stop-file',type=Path)
    p.add_argument('--max-rss-growth-mb',type=float,default=128)
    args=p.parse_args()
    import math
    if any(not math.isfinite(v) or v<=0 for v in (args.seconds,args.interval,args.ths_interval,args.max_rss_growth_mb)) or args.seconds>86400:
        p.error('finite positive limits required, seconds <=86400')
    root=Path(__file__).resolve().parents[1]
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    def reserve(name):return os.fdopen(os.open(args.output/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w')
    terminal=reserve('terminal.json');records=reserve('samples.jsonl')
    child=None;status={'status':'FAIL','requested_seconds':args.seconds,'cycles':0,'ths_reads':0,'fixture_reaped':False}
    begin=time.monotonic()
    try:
        phase='imports'
        from pymacauto import Application,AXEvents,PageSession,read_table
        from pymacauto.focus import current_front,foreground_identity,ForegroundGuard
        from AppKit import NSWorkspace
        import objc
        import pymacauto
        # Freeze installed bytes in every witness.
        module=Path(pymacauto.__file__).resolve().parent
        if Path(sys.prefix).resolve() not in module.parents or root/'src' in module.parents:
            raise RuntimeError('Installed package required')
        status['harness_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        status['fixture_sha256']=hashlib.sha256((root/'tests/native/Fixture.swift').read_bytes()).hexdigest()
        status['module_sha256']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in module.glob('*.py')}
        status['version']=pymacauto.__version__
        ws=NSWorkspace.sharedWorkspace();front=current_front(ws)
        ownership=ForegroundGuard(lambda:foreground_identity(ws))
        bundle=args.output/'EnduranceFixture.app/Contents';binary=bundle/'MacOS/EnduranceFixture'
        phase='fixture_start'
        binary.parent.mkdir(parents=True)
        (bundle/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.pymacauto.endurance','CFBundleExecutable':'EnduranceFixture','CFBundleName':'EnduranceFixture','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1','LSUIElement':True}))
        subprocess.run(['swiftc',str(root/'tests/native/Fixture.swift'),'-o',str(binary),'-framework','AppKit'],check=True,timeout=90,capture_output=True)
        child=subprocess.Popen([str(binary)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+15
        while True:
            try:
                app=Application.connect(pid=child.pid)
                app.child_window(identifier='pymacauto.input').resolve();break
            except Exception:
                if child.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.1)
        field=app.window(identifier='pymacauto.window').child(role='AXTextField',index=0,expected_count=1,verify={'identifier':'pymacauto.input'})
        phase='qualification'
        from pymacauto import AppProfile
        metadata=app.backend.app_metadata(app.pid)
        profile=AppProfile({**{k:metadata[k] for k in ('bundle_id','version','build')},
            'window':{'identifier':'pymacauto.window'},'controls':{
            'input':{'path':[{'relation':'descendant','selector':{'identifier':'pymacauto.input'}}],
                     'settable':['AXValue']},
            'apply':{'path':[{'relation':'descendant','selector':{'identifier':'pymacauto.apply'}}],
                     'actions':['AXPress']}}})
        status['capability_qualification']=profile.require(app)['qualified']
        status['locator_explanation']=field.explain()['complete']
        status['candidate_roundtrip']=app.backend.key(app.locator_path(field.export()['path']).resolve().ref)==app.backend.key(field.resolve().ref)
        status['children_readonly']=app.window(identifier='pymacauto.window').inspect_children()['read_only']
        if not all(status[k] for k in ('capability_qualification','locator_explanation','candidate_roundtrip','children_readonly')):raise RuntimeError('Qualification failed')
        stop=threading.Event();last_ths=0;rss0=None;fds0=None;threads0=None
        def rss():return int(subprocess.check_output(['/bin/ps','-p',str(os.getpid()),'-o','rss='],text=True).strip())
        loop_start=time.monotonic()
        phase='workload'
        class StopSource:
            def is_set(self):
                return stop.is_set() or (args.stop_file is not None and args.stop_file.exists()) or ownership.is_set()
        with app.session(identifier='pymacauto.window',stop=StopSource()) as session:
            while time.monotonic()-loop_start<args.seconds:
                if args.stop_file and args.stop_file.exists():
                    status['status']='STOPPED';break
                if child.poll() is not None:raise RuntimeError('Owned fixture exited')
                if ownership.is_set():raise RuntimeError('Foreground ownership changed')
                started=time.monotonic()
                with objc.autorelease_pool():
                    value='endurance-'+str(status['cycles'])
                    receipt=session.apply(field,'fill',value=value,timeout=5)
                    if receipt['status']!='CONFIRMED':raise RuntimeError('Protected operation failed:'+str(receipt.get('error')))
                    with AXEvents(app,targets=[field.resolve().ref]) as watcher:watcher.pause(.001)
                    status['cycles']+=1
                    sample={'cycle':status['cycles'],'elapsed_seconds':time.monotonic()-loop_start,
                            'operation_seconds':time.monotonic()-started,'rss_kb':rss(),
                            'fd_count':len(os.listdir('/dev/fd')),'threads':threading.active_count()}
                    if args.allow_ths_read and time.monotonic()-last_ths>=args.ths_interval:
                        from pymacauto.ths_profile import PROFILE
                        ths=Application.connect(bundle_id='cn.com.10jqka.macstockPro',max_nodes=14000,max_depth=80)
                        meta=ths.backend.app_metadata(ths.pid)
                        if meta['version']!='5.3.5' or meta['build']!='7.0.62':raise RuntimeError('THS version not qualified')
                        pages=PageSession(ths,window=PROFILE['window'],pages=PROFILE['pages'],content_path=PROFILE.get('content_path'),trigger_children_only=PROFILE.get('trigger_children_only',False))
                        page=pages.detect();table=read_table(ths.backend,page['table'])
                        sample['ths']={'page':page['page'],'rows':table['row_count'],'columns':table['column_count'],'sha256':table['sha256']}
                        status['ths_reads']+=1;last_ths=time.monotonic()
                    if ownership.is_set():raise RuntimeError('Foreground changed during observation')
                if rss0 is None:rss0=sample['rss_kb'];fds0=sample['fd_count'];threads0=sample['threads']
                if sample['rss_kb']-rss0>args.max_rss_growth_mb*1024:raise RuntimeError('RSS growth guard')
                if sample['fd_count']>fds0+4 or sample['threads']>threads0+2:raise RuntimeError('Resource growth guard')
                records.write(json.dumps(sample)+'\n');records.flush();os.fsync(records.fileno())
                if status['cycles']%20==0:__import__('gc').collect()
                time.sleep(args.interval)
            else:status['status']='PASS'
            phase='stop_check'
            stop.set()
            blocked=session.apply(field,'fill',value='MUST_NOT_WRITE',timeout=0)
            if blocked['status']!='NOT_DISPATCHED' or blocked.get('error_category')!='STOPPED':raise RuntimeError('Stop failed')
            status['stop_prevents_input']=True
        status['foreground_preserved']=not ownership.is_set()
        if not status['foreground_preserved']:status['status']='FAIL'
        status['actual_seconds']=time.monotonic()-loop_start
    except BaseException as exc:
        status.update(status='FAIL',error=type(exc).__name__,error_stage=locals().get('phase','setup'))
        # Messages are confined to a private receipt and this owned harness's
        # own bounded reason codes, never raw account/backend exception text.
        if type(exc) is RuntimeError:status['reason']=str(exc)[:160]
        if 'loop_start' in locals():status['actual_seconds']=time.monotonic()-loop_start
    finally:
        if 'ownership' in locals():status['foreground_diagnostics']=ownership.report()
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
            status['fixture_reaped']=child.poll() is not None
        records.close()
        status['total_seconds']=time.monotonic()-begin
        if not status['fixture_reaped']:status['status']='FAIL'
        terminal.write(json.dumps(status,ensure_ascii=False));terminal.flush();os.fsync(terminal.fileno());terminal.close()
        print(json.dumps(status,ensure_ascii=False))
    return 0 if status['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
