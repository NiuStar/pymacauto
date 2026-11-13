"""Run real AX integration against only the owned AppKit fixture.

On Mac: .venv/bin/python scripts/native_check.py
Never uses open/activate; preserves the foreground application and reaps child.
"""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if '--installed' not in sys.argv:
    sys.path.insert(0, str(ROOT / 'src'))


def main():
    if sys.platform != 'darwin':
        print(json.dumps({'status': 'BLOCKED', 'reason': 'macOS required'}))
        return 2
    from pymacauto.native import NativeBackend
    from pymacauto import Application, AXError, ElementNotFound, WaitTimeout
    from AppKit import NSWorkspace
    native = NativeBackend()
    if not native.trusted():
        print(json.dumps({'status': 'BLOCKED', 'reason': 'Accessibility permission required; no prompt opened'}))
        return 2
    workspace = NSWorkspace.sharedWorkspace()
    from pymacauto.focus import current_front
    current_front(workspace)
    front = workspace.frontmostApplication()
    original_pid = int(front.processIdentifier()) if front else None
    report = {'status': 'FAIL', 'fixture_only': True, 'checks': {}, 'foreground_before': original_pid}
    import pymacauto
    import pymacauto.cli
    report['sdk_module'] = str(Path(pymacauto.__file__).resolve())
    report['version'] = pymacauto.__version__
    cli_env = ({**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
               if '--installed' not in sys.argv else
               {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'})
    probe = subprocess.run([sys.executable, '-c',
                            'import json,pymacauto,pymacauto.cli; print(json.dumps({"sdk":pymacauto.__file__,"cli":pymacauto.cli.__file__,"version":pymacauto.__version__}))'],
                           env=cli_env, capture_output=True, text=True, timeout=15, check=True)
    report['cli_imports'] = json.loads(probe.stdout)
    if '--installed' in sys.argv:
        site_root = Path(sys.prefix).resolve()
        for module_path in (report['sdk_module'], report['cli_imports']['sdk'], report['cli_imports']['cli']):
            path = Path(module_path).resolve()
            if site_root not in path.parents or ROOT / 'src' in path.parents:
                raise RuntimeError(f'Installed validation imported outside venv: {path}')
        if report['cli_imports']['version'] != report['version']:
            raise RuntimeError('SDK and CLI versions differ')
        report['checks']['installed_imports_verified'] = True
    bundle = ROOT / 'build/native/MacAXFixture.app'
    contents = bundle / 'Contents'
    macos = contents / 'MacOS'
    macos.mkdir(parents=True, exist_ok=True)
    binary = macos / 'MacAXFixture'
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'org.pymacauto.fixture', 'CFBundleExecutable': 'MacAXFixture',
        'CFBundleName': 'MacAXFixture', 'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '1', 'CFBundleShortVersionString':'1.0','LSUIElement': True,
    }))
    subprocess.run(['swiftc', str(ROOT / 'tests/native/Fixture.swift'),
                    '-o', str(binary), '-framework', 'AppKit'], check=True, timeout=90)
    child = None
    code = 1
    log_path = ROOT / 'build/native/fixture.log'
    try:
        with log_path.open('w') as log:
            child = subprocess.Popen([str(binary)], stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            app = None
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(f'Fixture exited {child.returncode}: {log_path.read_text()}')
                try:
                    app = Application.connect(pid=child.pid)
                    app.child_window(identifier='pymacauto.input').wait(timeout=0.25)
                    break
                except (ElementNotFound, WaitTimeout):
                    time.sleep(0.1)
                except AXError as exc:
                    # Newly spawned Cocoa process may not have its AX server
                    # listening yet. This is fixture readiness, not SDK retry.
                    if exc.code != -25204:
                        raise
                    time.sleep(0.1)
            else:
                import ApplicationServices as ax
                raw = ax.AXUIElementCreateApplication(child.pid)
                diagnostics = {'registered': [a for a in native.apps() if a['pid'] == child.pid],
                               'fixture_log': log_path.read_text(),
                               'attributes': repr(ax.AXUIElementCopyAttributeNames(raw, None)),
                               'children': repr(ax.AXUIElementCopyAttributeValue(raw, 'AXChildren', None))}
                if app is not None:
                    diagnostics['tree'] = app.dump_tree()
                report['diagnostics'] = diagnostics
                raise RuntimeError('Fixture did not expose its AX input in 15 seconds')
            report['fixture_pid'] = child.pid
            report['checks']['connected'] = True
            tree = app.dump_tree()
            json.dumps(tree, allow_nan=False)
            report['checks']['tree_nodes'] = len(tree)
            from pymacauto.inspector import inspect_application
            inspection = inspect_application(app)
            assert inspection['complete'], inspection['limits_hit']
            assert inspection['node_count'] == len(tree)
            assert any(n['settable'].get('AXValue') is True for n in inspection['nodes'])
            report['checks']['inspector_complete'] = True
            report['checks']['inspector_settable_value'] = True
            report['checks']['position'] = app.child_window(identifier='pymacauto.input').resolve().get('AXPosition')
            field = app.child_window(identifier='pymacauto.input')
            initial = field.info()['value']
            assert initial == 'initial', f'Unexpected initial value: {initial!r}'
            report['checks']['initial_value'] = initial
            report['checks']['set_value'] = field.set_edit_text('hello AX')
            report['checks']['press'] = app.child_window(identifier='pymacauto.apply').click()
            result = app.child_window(identifier='pymacauto.result').wait(value='applied:hello AX', timeout=3)
            report['checks']['business_readback'] = result.info()['value']
            cli = subprocess.run([sys.executable, '-m', 'pymacauto', 'find', '--pid', str(child.pid),
                                  '--identifier', 'pymacauto.result'], capture_output=True, text=True,
                                 env=cli_env, timeout=15)
            assert cli.returncode == 0, cli.stderr + cli.stdout
            cli_value = json.loads(cli.stdout)['result']['value']
            assert cli_value == 'applied:hello AX', cli_value
            report['checks']['cli_readback'] = cli_value
            windows=app.windows()
            assert len(windows)==1
            assert windows[0].child_window(identifier='pymacauto.input').get_value()=='hello AX'
            assert windows[0].labelled_field('Input').get_value()=='hello AX'
            assert app.child_window(identifier='pymacauto.input').get_value()=='hello AX'
            # Structural hierarchy, filtered sibling index and independent fingerprint.
            path=[{'relation':'window','selector':{'identifier':'pymacauto.window'}},
                  {'relation':'child','selector':{'role':'AXTextField'},'index':0,
                   'expected_count':1,'verify':{'identifier':'pymacauto.input'}}]
            indexed=app.locator_path(path)
            assert indexed.get_value()=='hello AX'
            indexed.set_edit_text('hello AX')
            assert windows[0].child(role='AXTextField',index=0,expected_count=1).get_value()=='hello AX'
            cli_path=subprocess.run([sys.executable,'-m','pymacauto','get-value','--pid',str(child.pid),
                '--path',json.dumps(path)],capture_output=True,text=True,env=cli_env,timeout=15)
            assert cli_path.returncode==0 and json.loads(cli_path.stdout)['result']=='hello AX'
            report['checks']['hierarchy_type_index']=True
            report['checks']['convenience_sdk'] = True
            cli_fill=subprocess.run([sys.executable,'-m','pymacauto','fill','--pid',str(child.pid),
                '--window-identifier','pymacauto.window','--label','Input','--value','CLI text','--execute'],
                capture_output=True,text=True,env=cli_env,timeout=15)
            assert cli_fill.returncode==0,cli_fill.stdout+cli_fill.stderr
            assert json.loads(cli_fill.stdout)['result']['verified']
            assert windows[0].labelled_field('Input').get_value()=='CLI text'
            report['checks']['labelled_cli_fill'] = True
            private_output=ROOT/'build/native'/('value-'+str(time.time_ns())+'.json')
            cli_get=subprocess.run([sys.executable,'-m','pymacauto','get-value','--pid',str(child.pid),
                '--window-identifier','pymacauto.window','--identifier','pymacauto.input','--output',str(private_output)],
                capture_output=True,text=True,env=cli_env,timeout=15)
            assert cli_get.returncode==0,cli_get.stdout+cli_get.stderr
            assert json.loads(private_output.read_text())['result']=='CLI text'
            assert private_output.stat().st_mode & 0o777==0o600
            report['checks']['private_cli_output'] = True
            from pymacauto.controls import Control
            check=Control(app.child_window(identifier='pymacauto.check'))
            assert check.set_checked(True)['verified']
            assert check.set_checked(True)['verified']
            assert check.set_checked(False)['verified']
            assert Control(app.child_window(identifier='pymacauto.slider')).set_numeric(7)['verified']
            assert Control(app.child_window(identifier='pymacauto.popup')).choose('Two')['verified']
            assert Control(app.child_window(identifier='pymacauto.radio')).select()['verified']
            assert Control(app.child_window(identifier='pymacauto.tabs')).select_tab('Second')['verified']
            report['checks']['native_controls']=True
            from pymacauto.operations import OperationSession,Condition
            session=OperationSession(app,window={'identifier':'pymacauto.window'})
            target=app.child_window(identifier='pymacauto.apply')
            post=Condition(app.child_window(identifier='pymacauto.result'),value='applied:CLI text')
            receipt=session.execute(target,postcondition=post,timeout=2)
            assert receipt['status']=='CONFIRMED',receipt
            assert session.execute(target,postcondition=Condition(app.child_window(identifier='pymacauto.result'),value='never'),timeout=0)['status']=='DISPATCHED_UNCONFIRMED'
            from pymacauto.events import AXEvents
            condition=Condition(app.child_window(identifier='pymacauto.result'),value='delayed ready')
            with AXEvents(app,targets=[app.child_window(identifier='pymacauto.result').resolve().ref]) as events:
                app.child_window(identifier='pymacauto.delayed').click()
                deadline=time.monotonic()+2;checks=0;started=time.monotonic()
                while not condition.check():
                    checks+=1
                    assert time.monotonic()<deadline
                    events.pause(min(.5,max(0,deadline-time.monotonic())))
                assert events.received>0,'No actual AX notification received'
                report['checks']['ax_events']={'received':events.received,'checks':checks,'mode':events.mode,'ms':(time.monotonic()-started)*1000}
            event_pairs=[]
            for pair in range(3):
                for mode in (('poll','events') if pair%2==0 else ('events','poll')):
                    app.child_window(identifier='pymacauto.apply').click()
                    result_ref=app.child_window(identifier='pymacauto.result').resolve().ref
                    with AXEvents(app,targets=[result_ref]) as watcher:
                        app.child_window(identifier='pymacauto.delayed').click()
                        started=time.monotonic();n=0
                        while True:
                            n+=1
                            if condition.check():break
                            assert time.monotonic()-started<3
                            if mode=='events':watcher.pause(.5)
                            else:time.sleep(.01)
                        event_pairs.append({'pair':pair,'mode':mode,'checks':n,
                            'events':watcher.received,'elapsed_seconds':time.monotonic()-started,
                            'exact_value_equal':condition.locator.get_value()=='delayed ready'})
            assert all(r['exact_value_equal'] for r in event_pairs)
            assert sum(r['events'] for r in event_pairs if r['mode']=='events')>0
            report['checks']['event_poll_pairs']=event_pairs
            native_session=app.session(identifier='pymacauto.window')
            same=native_session.execute(target,postcondition=post,operation_id='owned-once',timeout=2,events=True)
            assert same['status']=='CONFIRMED',same
            assert native_session.execute(target,postcondition=post,operation_id='owned-once',timeout=0)==same
            # OS file-lock contention across a real child process.
            from pymacauto.operations import _file_lock
            lock_fd=_file_lock(app.pid)
            try:
                child_lock=subprocess.run([sys.executable,'-c',
                    'from pymacauto.operations import _file_lock;import sys;_file_lock(int(sys.argv[1]))',str(app.pid)],
                    capture_output=True,text=True,env=cli_env,timeout=10)
                assert child_lock.returncode!=0 and 'BlockingIOError' in child_lock.stderr
            finally:os.close(lock_fd)
            native_session.close()
            assert native_session.execute(target,postcondition=post,timeout=0)['status']=='NOT_DISPATCHED'
            report['checks']['session_reuse_and_cross_process_exclusion']=True
            app.child_window(identifier='pymacauto.input').set_edit_text('CLI verified')
            cli_verified=subprocess.run([sys.executable,'-m','pymacauto','verified-action','--pid',str(child.pid),
                '--window','{"identifier":"pymacauto.window"}',
                '--target','{"identifier":"pymacauto.apply"}',
                '--expect','{"identifier":"pymacauto.result"}','--expect-value','applied:CLI verified','--execute'],
                capture_output=True,text=True,env=cli_env,timeout=15)
            assert cli_verified.returncode==0,cli_verified.stdout+cli_verified.stderr
            assert json.loads(cli_verified.stdout)['result']['status']=='CONFIRMED'
            report['checks']['verified_cli']=True
            journal_directory=ROOT/'build/native'/('journal-'+str(time.time_ns()))
            journal_directory.mkdir(mode=0o700)
            journal_path=journal_directory/'operations.sqlite'
            app.child_window(identifier='pymacauto.input').set_edit_text('durable test')
            durable_post=Condition(app.child_window(identifier='pymacauto.result'),value='applied:durable test')
            with app.session(identifier='pymacauto.window',journal=journal_path) as durable:
                first=durable.execute(target,postcondition=durable_post,operation_id='native-durable',timeout=2)
                assert first['status']=='CONFIRMED',first
            with app.session(identifier='pymacauto.window',journal=journal_path) as durable:
                assert durable.execute(target,postcondition=durable_post,operation_id='native-durable',timeout=0)==first
                observed=durable.recover('native-durable',target,postcondition=durable_post,timeout=0)
                assert observed['status']=='RECOVERY_OBSERVED'
            from pymacauto.journal import audit_journal
            before_bytes=journal_path.read_bytes()
            audited=audit_journal(journal_path)
            assert len(audited['operations'])==1 and journal_path.read_bytes()==before_bytes
            with app.session(identifier='pymacauto.window',journal=journal_path,readonly=True) as observer:
                assert observer.recover('native-durable',target,postcondition=durable_post,timeout=0)['observed']
            assert journal_path.read_bytes()==before_bytes
            report['checks']['readonly_journal_audit_observe']=True
            report['checks']['durable_reopen_no_replay']=True
            with app.session(identifier='pymacauto.window') as protected:
                assert protected.apply(app.child_window(identifier='pymacauto.input'),'fill',value='protected')['status']=='CONFIRMED'
                assert protected.apply(app.child_window(identifier='pymacauto.check'),'check',value=True)['status']=='CONFIRMED'
                assert protected.apply(app.child_window(identifier='pymacauto.slider'),'numeric',value=4)['status']=='CONFIRMED'
            from pymacauto import AXMetrics
            with AXMetrics(app.backend) as metrics:
                with app.session(identifier='pymacauto.window') as protected:
                    metric_receipt=protected.apply(app.child_window(identifier='pymacauto.input'),'fill',value='metric value')
                    assert metric_receipt['status']=='CONFIRMED'
            report['checks']['operation_metrics']={'timings':metric_receipt['timings'],**metrics.summary()}
            from pymacauto import AppProfile
            profile=AppProfile({**app.backend.app_metadata(app.pid),'window':{'identifier':'pymacauto.window'},
                'controls':{'input':{'path':[{'relation':'descendant','selector':{'identifier':'pymacauto.input'}}],'settable':['AXValue']},
                            'apply':{'identifier':'pymacauto.apply'},'result':{'identifier':'pymacauto.result'}}})
            with app.automation(profile) as ui:
                assert ui.control('input').fill('facade')['status']=='CONFIRMED'
                assert ui.control('input').read()=='facade'
                assert ui.control('apply').click(expect=ui.condition('result',value='applied:facade'))['status']=='CONFIRMED'
            report['checks']['named_automation_native']=True
            report['checks']['unified_protected_controls']=True
            # Identical readonly query in fresh processes vs interpreter reuse.
            reuse=[];spawn=[]
            for _ in range(3):
                started=time.perf_counter()
                value=app.child_window(identifier='pymacauto.result').get_value()
                reuse.append(time.perf_counter()-started)
                started=time.perf_counter()
                proc=subprocess.run([sys.executable,'-m','pymacauto','get-value','--pid',str(child.pid),
                    '--identifier','pymacauto.result'],capture_output=True,text=True,env=cli_env,timeout=15)
                spawn.append(time.perf_counter()-started)
                assert proc.returncode==0 and json.loads(proc.stdout)['result']==value
            report['checks']['reuse_vs_process']={'reuse_seconds':reuse,'fresh_process_seconds':spawn,'exact_values_equal':True}
            # Same interpreter/backend/session: observer and journal lifecycle churn.
            import threading,resource
            cycles=int(os.environ.get('PYMACAUTO_SOAK_CYCLES','12'))
            if not 1<=cycles<=10000:raise ValueError('soak cycles must be 1..10000')
            duration=float(os.environ.get('PYMACAUTO_SOAK_SECONDS','0'))
            interval=float(os.environ.get('PYMACAUTO_SOAK_INTERVAL','0'))
            import math
            if not math.isfinite(duration) or not 0<=duration<=86400 or not math.isfinite(interval) or not 0<=interval<=60:raise ValueError('Invalid soak seconds/interval')
            resources=[];loop_start=time.monotonic()
            with app.session(identifier='pymacauto.window') as persistent:
                cycle=0
                while cycle<cycles or time.monotonic()-loop_start<duration:
                    import objc
                    with objc.autorelease_pool():
                        desired='cycle-'+str(cycle)
                        receipt=persistent.apply(indexed,'fill',value=desired,timeout=2)
                        assert receipt['status']=='CONFIRMED',receipt
                        with AXEvents(app,targets=[indexed.resolve().ref]) as watcher:watcher.pause(.001)
                    if cycle%50==0:
                        import gc
                        gc.collect()
                    if cycle==0 or cycle%max(1,cycles//2)==0:
                        fds=subprocess.check_output(['/bin/ps','-p',str(os.getpid()),'-o','rss='],text=True).strip()
                        resources.append({'cycle':cycle,'rss_kb':int(fds),'threads':threading.active_count(),
                                          'peak_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'fd_count':len(os.listdir('/dev/fd'))})
                    cycle+=1
                    if interval:time.sleep(interval)
                stop=threading.Event();stop.set()
                with app.session(identifier='pymacauto.window',stop=stop) as stopped:
                    blocked=stopped.apply(indexed,'fill',value='must not write',timeout=0)
                    assert blocked['status']=='NOT_DISPATCHED'
                assert indexed.get_value()=='cycle-'+str(cycle-1)
            report['checks']['same_process_soak']={'cycles':cycle,'requested_cycles':cycles,'requested_seconds':duration,'elapsed_seconds':time.monotonic()-loop_start,'resources':resources,'stop_prevents_input':True}
            app.child_window(identifier='pymacauto.sheet').click()
            deadline=time.monotonic()+3
            from pymacauto.core import _get
            while not app.descendants(role='AXSheet'):
                assert time.monotonic()<deadline,'Sheet not observed'
                time.sleep(.02)
            blocked=session.execute(target,postcondition=post,timeout=0)
            assert blocked['status']=='NOT_DISPATCHED' and blocked['attempts']==0,blocked
            session.close()
            report['checks']['single_dispatch_postcondition']=True
            report['checks']['modal_blocks_input']=True
            current_front(workspace)
            after = workspace.frontmostApplication()
            report['foreground_after'] = int(after.processIdentifier()) if after else None
            assert report['foreground_after'] == original_pid, 'Foreground app changed during integration'
            report['checks']['foreground_preserved'] = True
            report['status'] = 'PASS'
            code = 0
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            report['fixture_reaped'] = child.poll() is not None
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
