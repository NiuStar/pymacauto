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
        'CFBundleVersion': '1', 'LSUIElement': True,
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
