"""Read THS positions/orders/deals into private local JSON; no order actions."""
import argparse
import uuid
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from pymacauto import Application
from pymacauto.tables import read_table
from .ths_profile import PROFILE
from .pages import PageSession
from pymacauto.errors import AXError, MacAXError
from AppKit import NSWorkspace, NSRunningApplication, NSApplicationActivateIgnoringOtherApps, NSBundle
from .focus import current_front, wait_for

TABLE_IDS={name:PROFILE['pages'][name]['table']['identifier'] for name in PROFILE['read_pages']}


def read_view(app, title, table=None):
    if table is None:
        table=PageSession(app,window=PROFILE['window'],pages=PROFILE['pages'],
                          content_path=PROFILE.get('content_path'),
                          trigger_children_only=PROFILE.get('trigger_children_only',False)).wait(title)['table']
    result=read_table(app.backend,table)
    if not set(PROFILE['pages'][title]['headers']) <= set(result['headers']): raise MacAXError('QUERY_SCHEMA_MISMATCH')
    result['view']=title
    result['table_identifier']=TABLE_IDS[title]
    result['query_filters']='CURRENT_UI_FILTERS_NOT_CHANGED'
    return result


def _main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-foreground',action='store_true',required=True)
    args=parser.parse_args(argv)
    workspace=NSWorkspace.sharedWorkspace()
    current_front(workspace)
    original_app=workspace.frontmostApplication()
    if original_app is None: raise RuntimeError('No foreground app')
    original_pid=int(original_app.processIdentifier())
    targets=NSRunningApplication.runningApplicationsWithBundleIdentifier_('cn.com.10jqka.macstockPro')
    if len(targets)!=1: raise RuntimeError('Expected exactly one THS')
    target=targets[0]; pid=int(target.processIdentifier())
    meta=NSBundle.bundleWithPath_(str(target.bundleURL().path())).infoDictionary()
    app_identity={'bundle_id':'cn.com.10jqka.macstockPro',
                  'version':str(meta.get('CFBundleShortVersionString')),
                  'build':str(meta.get('CFBundleVersion'))}
    if (app_identity['version'],app_identity['build'])!=('5.3.5','7.0.62'):
        raise RuntimeError('Unqualified THS version; refuse query actions')
    app=Application.connect(pid=pid,max_nodes=14000,max_depth=80)
    session=PageSession(app,window=PROFILE['window'],pages=PROFILE['pages'],
                          content_path=PROFILE.get('content_path'),
                          trigger_children_only=PROFILE.get('trigger_children_only',False))
    initial=session.wait()
    original_view=initial['page']
    if original_view not in PROFILE['pages']: raise RuntimeError('Original query view is not recognized; no action')
    import pymacauto
    report={'package_version':pymacauto.__version__,'module_path':str(Path(__file__).resolve()),
            'application':app_identity,
            'cross_table_atomic_snapshot':False,'schema':'pymacauto.ths.read.v2','status':'FAIL','pid':pid,'foreground_before':original_pid,
            'original_view':original_view,'order_actions':0,'input_writes':0,'tables':{},'errors':[]}
    start=time.monotonic()
    try:
        target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        if not wait_for(lambda:current_front(workspace)==pid,5): raise RuntimeError('Foreground not observed')
        for title in TABLE_IDS:
            if current_front(workspace)!=pid: raise RuntimeError('Lost foreground; no additional action')
            observed=session.switch(title)
            # Read-only table retries always discard the prior partial snapshot.
            deadline=time.monotonic()+15
            while True:
                try:
                    result=read_view(app,title,observed['table'])
                    break
                except AXError as exc:
                    report['errors'].append({'view':title,'operation':exc.operation,'code':exc.code})
                    if exc.code not in (-25201,-25202,-25204) or time.monotonic()>=deadline: raise
                    time.sleep(0.03)
                    observed=session.wait(title)
            report['tables'][title]=result
        report['status']='PASS'
    except Exception as exc:
        report['error']=f'{type(exc).__name__}:{exc}'
    finally:
        try:
            if current_front(workspace)!=pid: raise RuntimeError('Lost foreground; refuse restore click')
            restored=session.switch(original_view)
            if restored['headers']!=initial['headers']: raise RuntimeError('Original page headers changed')
            report['query_restored']=True
        except Exception as exc:
            report['status']='FAIL';report['restore_error']=f'{type(exc).__name__}:{exc}'
        try:
            original_app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            report['foreground_restored']=bool(wait_for(lambda:current_front(workspace)==original_pid,5))
            if not report['foreground_restored']:report['status']='FAIL'
        except Exception as exc:
            report['status']='FAIL';report['focus_restore_error']=type(exc).__name__
        report['read_poll_errors']=session.read_errors
        report['elapsed_seconds']=time.monotonic()-start
        directory=Path.home()/'pymacauto/evidence/ths'
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=directory/('tables-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex+'.json')
        content=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode()
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as handle:
            handle.write(content);handle.flush();os.fsync(handle.fileno())
        assert path.read_bytes()==content
        summary={key:value for key,value in report.items() if key!='tables'}
        summary['tables']={title:{k:v for k,v in table.items() if k!='rows'} for title,table in report['tables'].items()}
        summary.update(private_data_path=str(path),file_sha256=hashlib.sha256(content).hexdigest())
        print(json.dumps(summary,ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1


def main(argv=None):
    try:
        return _main(argv)
    except (MacAXError,RuntimeError,ValueError,OSError) as exc:
        print(json.dumps({'status':'FAIL','error':type(exc).__name__,
                          'stage':'preflight_or_persistence'},ensure_ascii=False))
        return 1


if __name__=='__main__':raise SystemExit(main())
