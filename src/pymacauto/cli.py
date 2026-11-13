"""One-shot JSON CLI. No implicit focus changes or mutation retries."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from . import Application,MacAXError,UnsafeOperation,__version__


def parser():
    p=argparse.ArgumentParser(prog='pymacauto',description='macOS AX automation; writes require --execute')
    p.add_argument('--version',action='version',version='%(prog)s '+__version__)
    p.add_argument('--output',help='Create private JSON file exclusively; never overwrite')
    sub=p.add_subparsers(dest='command',required=True)
    for command in ('doctor','apps','windows','tree','inspect','find','get-value',
                    'read-table','click','set-value','fill','action','wait','page'):
        q=sub.add_parser(command)
        q.add_argument('--output',default=argparse.SUPPRESS,help='Create private JSON output file')
        if command=='doctor':q.add_argument('--prompt',action='store_true')
        if command in ('doctor','apps'):continue
        target=q.add_mutually_exclusive_group(required=True)
        target.add_argument('--pid',type=int);target.add_argument('--bundle-id');target.add_argument('--name')
        q.add_argument('--max-nodes',type=int,default=5000)
        q.add_argument('--max-depth',type=int,default=40)
        if command not in ('windows','tree','inspect','page','fill'):
            for field in ('role','subrole','title','identifier','description','help'):
                option='--ax-help' if field=='help' else '--'+field
                q.add_argument(option,dest=field)
                q.add_argument(option+'-re',dest=field+'_re')
        if command in ('find','get-value','read-table','click','set-value','action','wait','fill'):
            q.add_argument('--window-identifier',required=command=='fill',help='Unique top-level window scope')
        if command in ('click','set-value','fill','action','page'):q.add_argument('--execute',action='store_true')
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
        if command=='page':
            q.add_argument('--config',required=True,help='JSON page fingerprint configuration')
            q.add_argument('--to',required=True,help='Target page name')
            q.add_argument('--timeout',type=float,default=5)
    return p


def run(args):
    if args.command in ('click','set-value','fill','action','page') and not args.execute:
        raise UnsafeOperation('Mutation requires --execute; inspect the unique target first')
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
    if args.command=='page':
        from .pages import PageSession
        config=json.loads(Path(args.config).read_text(encoding='utf-8'))
        result=PageSession.from_config(app,config).switch(args.to,timeout=args.timeout)
        return {'page':result['page'],'headers':result['headers'],'verified':True,'focus_changed_by_framework':False}
    if args.command=='fill':
        from .query import window_scope
        from .fields import labelled_field
        scope=window_scope(app,identifier=args.window_identifier)
        field=labelled_field(app,scope.root,args.label,alignment_tolerance=args.alignment_tolerance,max_gap=args.max_gap)
        return field.set_edit_text(args.value)
    keys=('role','subrole','title','identifier','description','help')
    criteria={key+suffix:getattr(args,key+suffix) for key in keys for suffix in ('','_re')
              if getattr(args,key+suffix) is not None}
    if args.window_identifier is not None:
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
        code=1 if args.command=='doctor' and not result['ready'] else 0
    except (MacAXError,ValueError,TypeError,OSError,re.error) as exc:
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
