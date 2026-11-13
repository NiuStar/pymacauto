"""One-shot JSON CLI. No implicit focus changes or mutation retries."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import sqlite3

from . import Application,MacAXError,UnsafeOperation,__version__


def parser():
    p=argparse.ArgumentParser(prog='pymacauto',description='macOS AX automation; writes require --execute')
    p.add_argument('--version',action='version',version='%(prog)s '+__version__)
    p.add_argument('--output',help='Create private JSON file exclusively; never overwrite')
    sub=p.add_subparsers(dest='command',required=True)
    audit=sub.add_parser('journal-inspect')
    audit.add_argument('--journal',required=True)
    audit.add_argument('--output',default=argparse.SUPPRESS)
    diff=sub.add_parser('profile-diff')
    diff.add_argument('--before',required=True);diff.add_argument('--after',required=True)
    diff.add_argument('--output',default=argparse.SUPPRESS)
    for command in ('doctor','apps','windows','tree','inspect','find','get-value',
                    'read-table','click','set-value','fill','action','wait','page','verified-action','profile-check','journal-observe','inspect-children','explain-locator','export-locator'):
        q=sub.add_parser(command)
        q.add_argument('--output',default=argparse.SUPPRESS,help='Create private JSON output file')
        if command=='doctor':q.add_argument('--prompt',action='store_true')
        if command in ('doctor','apps'):continue
        target=q.add_mutually_exclusive_group(required=True)
        target.add_argument('--pid',type=int);target.add_argument('--bundle-id');target.add_argument('--name')
        q.add_argument('--max-nodes',type=int,default=5000)
        q.add_argument('--max-depth',type=int,default=40)
        if command not in ('windows','tree','inspect','page','fill','profile-check'):
            q.add_argument('--path',help='JSON array of hierarchical locator steps')
            for field in ('role','subrole','title','identifier','description','help'):
                option='--ax-help' if field=='help' else '--'+field
                q.add_argument(option,dest=field)
                q.add_argument(option+'-re',dest=field+'_re')
        if command in ('find','get-value','read-table','click','set-value','action','wait','fill'):
            q.add_argument('--window-identifier',required=command=='fill',help='Unique top-level window scope')
        if command in ('click','set-value','fill','action','page','verified-action'):q.add_argument('--execute',action='store_true')
        if command=='set-value':
            value=q.add_mutually_exclusive_group(required=True)
            value.add_argument('--value');value.add_argument('--json-value')
        if command=='fill':
            q.add_argument('--label',required=True);q.add_argument('--value',required=True)
            q.add_argument('--alignment-tolerance',type=float,default=8)
            q.add_argument('--max-gap',type=float,default=220)
        if command=='action':q.add_argument('--action',required=True)
        if command=='read-table':
            q.add_argument('--max-cells',type=int,default=100000)
            q.add_argument('--timeout',type=float,default=15)
        if command=='wait':
            q.add_argument('--timeout',type=float,default=5)
            q.add_argument('--state',choices=('exists','gone'),default='exists')
            q.add_argument('--value')
        if command=='profile-check':q.add_argument('--config',required=True)
        if command in ('verified-action','journal-observe'):
            q.add_argument('--window',required=True,help='JSON top-level window selector')
            q.add_argument('--target',required=True,help='JSON control selector within approved window')
            q.add_argument('--expect',required=True,help='JSON postcondition selector within approved window')
            q.add_argument('--expect-value',required=True)
            q.add_argument('--timeout',type=float,default=5)
            q.add_argument('--events',action='store_true')
            q.add_argument('--journal',help='Private durable SQLite operation journal')
            q.add_argument('--operation-id',help='Stable request ID required with --journal')
        if command=='page':
            q.add_argument('--journal')
            q.add_argument('--operation-id')
            q.add_argument('--stop-file')
            q.add_argument('--config',required=True,help='JSON page fingerprint configuration')
            q.add_argument('--to',required=True,help='Target page name')
            q.add_argument('--timeout',type=float,default=5)
    return p


def run(args):
    if args.command in ('click','set-value','fill','action','page','verified-action') and not args.execute:
        raise UnsafeOperation('Mutation requires --execute; inspect the unique target first')
    if args.command=='journal-inspect':
        from .journal import audit_journal
        return audit_journal(args.journal)
    if args.command=='profile-diff':
        from .profiles import AppProfile
        return AppProfile.diff(json.loads(Path(args.before).read_text()),json.loads(Path(args.after).read_text()))
    from .native import NativeBackend
    backend=NativeBackend()
    if args.command=='doctor':
        trusted=backend.trusted(prompt=args.prompt)
        return {'platform':sys.platform,'version':__version__,'trusted':bool(trusted),'ready':bool(trusted),
                'permission_prompt_requested':args.prompt}
    if args.command=='apps':return backend.apps()
    app=Application.connect(pid=args.pid,bundle_id=args.bundle_id,name=args.name,backend=backend,
                            max_nodes=args.max_nodes,max_depth=args.max_depth)
    if args.command=='windows':return [e.info() for e in app.windows()]
    if args.command=='tree':return app.dump_tree()
    if args.command=='inspect':return app.inspect(max_nodes=args.max_nodes,max_depth=args.max_depth)
    if args.command=='profile-check':
        from .profiles import AppProfile
        return AppProfile(json.loads(Path(args.config).read_text())).inspect(app)
    if args.command in ('verified-action','journal-observe'):
        from .operations import Condition,OperationSession
        from .core import Locator,_selector
        from .query import window_scope
        if args.journal and not args.operation_id:raise ValueError('--journal requires --operation-id')
        window=json.loads(args.window)
        if not isinstance(window,dict):raise ValueError('window must be a selector object')
        target=json.loads(args.target);expected=json.loads(args.expect)
        if isinstance(target,dict):target=_selector(target)
        if isinstance(expected,dict):expected=_selector(expected)
        if not isinstance(target,(list,dict)) or not isinstance(expected,(list,dict)):raise ValueError('target/expect require selector objects or paths')
        root=lambda:window_scope(app,**window).root
        if isinstance(target,list) or isinstance(expected,list):
            if not isinstance(target,list) or not isinstance(expected,list):raise ValueError('Both target and expect must be paths')
            target_locator=app.locator_path(target);expect_locator=app.locator_path(expected)
        elif args.journal:
            # Journal requests must use serializable application-rooted chains.
            target_locator=app.window(**window).child_window(**target)
            expect_locator=app.window(**window).child_window(**expected)
        else:
            target_locator=Locator(app,(target,),root=root)
            expect_locator=Locator(app,(expected,),root=root)
        with OperationSession(app,window=window,journal=args.journal,readonly=args.command=='journal-observe') as session:
            if args.command=='journal-observe':
                if not args.journal or not args.operation_id:raise ValueError('journal-observe requires journal and operation-id')
                return session.recover(args.operation_id,target_locator,postcondition=Condition(expect_locator,value=args.expect_value),timeout=args.timeout)
            return session.execute(target_locator,
                postcondition=Condition(expect_locator,value=args.expect_value),
                timeout=args.timeout,events=args.events,operation_id=args.operation_id)
    if args.command=='page':
        from .pages import PageSession
        config=json.loads(Path(args.config).read_text(encoding='utf-8'))
        if args.journal and not args.operation_id:raise ValueError('--journal requires --operation-id')
        with app.session(**config['window'],journal=args.journal,stop=args.stop_file) as owner:
            result=PageSession.from_config(app,config,operations=owner).switch(args.to,timeout=args.timeout,operation_id=args.operation_id)
        return {'page':result['page'],'headers':result['headers'],'receipt':result['receipt'],
                'verified':True,'focus_changed_by_framework':False}
    if args.command=='fill':
        from .query import window_scope
        from .fields import labelled_field
        scope=window_scope(app,identifier=args.window_identifier)
        field=labelled_field(app,scope.root,args.label,alignment_tolerance=args.alignment_tolerance,max_gap=args.max_gap)
        return field.set_edit_text(args.value)
    keys=('role','subrole','title','identifier','description','help')
    criteria={key+suffix:getattr(args,key+suffix) for key in keys for suffix in ('','_re')
              if getattr(args,key+suffix) is not None}
    if args.path is not None:
        if criteria or getattr(args,'window_identifier',None):raise ValueError('--path cannot combine with flat/window selectors')
        locator=app.locator_path(json.loads(args.path))
    elif getattr(args,'window_identifier',None) is not None:
        from .query import window_scope
        scope=window_scope(app,identifier=args.window_identifier)
        if args.command=='read-table':
            from .tables import read_table
            scope=window_scope(app,identifier=args.window_identifier,leaf_roles=('AXTable',))
            return read_table(backend,scope.find(**criteria).ref,max_cells=args.max_cells,timeout=args.timeout)
        from .core import Locator,_selector
        locator=Locator(app,(_selector(criteria),),
                        root=lambda:window_scope(app,identifier=args.window_identifier).root)
    else:locator=app.child_window(**criteria)
    if args.command in ('inspect-children','explain-locator','export-locator'):
        from . import locator_diagnostics
        return getattr(locator_diagnostics,args.command.replace('-','_'))(locator)
    if args.command=='find':return locator.info()
    if args.command=='get-value':return locator.get_value()
    if args.command=='read-table':return locator.read_table(max_cells=args.max_cells,timeout=args.timeout)
    if args.command=='click':return locator.click()
    if args.command=='action':return locator.perform(args.action)
    if args.command=='set-value':return locator.set_value(args.value if args.json_value is None else json.loads(args.json_value))
    if args.command=='wait':
        expected={} if args.value is None else {'value':args.value}
        result=locator.wait(timeout=args.timeout,state=args.state,**expected)
        return {'state':args.state,'verified':True,'element':result.info() if result else None}
    raise ValueError('Unknown command')


def main(argv=None):
    args=parser().parse_args(argv)
    output_file=None
    try:
        # Reserve output BEFORE UI actions; never overwrite or repeat a write
        # merely because its result could not be saved to an existing file.
        if args.output:
            fd=os.open(args.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            output_file=os.fdopen(fd,'w',encoding='utf-8')
        result=run(args)
        text=json.dumps({'ok':True,'result':result},ensure_ascii=False,allow_nan=False)
        code=1 if ((args.command=='doctor' and not result['ready']) or
                   (args.command=='verified-action' and not result['verified']) or
                   (args.command=='profile-check' and not result['qualified'])) else 0
    except (MacAXError,ValueError,TypeError,OSError,re.error,sqlite3.Error) as exc:
        text=json.dumps({'ok':False,'error':type(exc).__name__,'message':str(exc)},ensure_ascii=False)
        code=2
    if output_file is not None:
        try:
            with output_file:
                output_file.write(text+'\n');output_file.flush();os.fsync(output_file.fileno())
            print(json.dumps({'ok':code==0,'output':str(Path(args.output)),'exit_code':code},ensure_ascii=False))
        except OSError:
            print(json.dumps({'ok':False,'error':'OutputWriteFailed','message':'Result persistence failed; do not blindly retry a mutation'}))
            return 2
    else:print(text)
    return code


if __name__=='__main__':raise SystemExit(main())
