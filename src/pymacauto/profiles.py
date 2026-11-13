"""Version-qualified read-only app profiles; reports exclude captured AX values.

Named controls accept a flat selector (legacy) or an exact-key specification:
``{'path': [...], 'actions': ['AXPress'], 'settable': ['AXValue']}``.
Paths are relative to the profile's unique top-level window, not the app root.
Capability checks are declarations of native support, never action tests.
"""
import copy
import hashlib
import json
import re

from .core import Application, _selector
from .errors import UnsafeOperation
from .journal import canonical
from .query import window_scope


def _capability_names(names):
    if (not isinstance(names,list) or
            any(not isinstance(name,str) or re.fullmatch(r'AX[A-Za-z][A-Za-z0-9]*',name) is None for name in names) or
            len(set(names))!=len(names)):
        raise ValueError('Capabilities require distinct raw AX names in a list')
    return list(names)


def _control_spec(control):
    if not isinstance(control,dict):raise ValueError('Control must be an object')
    if not set(control)&{'path','actions','settable'}:return _selector(control)
    if 'path' not in control or set(control)-{'path','actions','settable'}:
        raise ValueError('Control specification requires path and known optional fields')
    path=control['path']
    if not isinstance(path,list) or not path:raise ValueError('Nonempty control path required')
    # Reuse the public validator without connecting to or resolving an app.
    # The actual app's depth budget is checked again on every inspection.
    validator=object.__new__(Application)
    validator.max_depth=len(path)
    validator.locator_path(path)
    if any(step['relation']=='window' for step in path):
        raise ValueError('Control path is relative to the profile window')
    result={'path':copy.deepcopy(path)}
    for key in ('actions','settable'):
        if key in control:result[key]=_capability_names(control[key])
    return result


def _capabilities(backend,ref,spec):
    actions={name:False for name in spec.get('actions',[])}
    settable={name:False for name in spec.get('settable',[])}
    errors={}
    if actions:
        try:
            available=backend.actions(ref)
            if not isinstance(available,(list,tuple)) or any(not isinstance(name,str) for name in available):
                raise ValueError('Invalid action names')
            actions={name:name in available for name in actions}
        except Exception as exc:errors['actions']=type(exc).__name__
    for name in settable:
        try:
            writable=backend.is_settable(ref,name)
            if not isinstance(writable,bool):raise ValueError('Invalid settable result')
            settable[name]=writable
        except Exception as exc:errors[name]=type(exc).__name__
    result={'actions':actions,'settable':settable,
            'ability_qualified':not errors and all(actions.values()) and all(settable.values())}
    if errors:result['capability_errors']=errors
    return result


class AppProfile:
    def __init__(self,config):
        required={'bundle_id','version','build','window','controls'}
        if not isinstance(config,dict) or set(config)!=required:raise ValueError('Profile requires exact identity/window/controls fields')
        if not all(isinstance(config[k],str) and config[k] for k in ('bundle_id','version','build')):raise ValueError('Nonempty identity required')
        if not isinstance(config['controls'],dict) or not config['controls']:raise ValueError('Nonempty named controls required')
        if not all(isinstance(k,str) and k for k in config['controls']):raise ValueError('Nonempty control names required')
        if not isinstance(config['window'],dict):raise ValueError('Window selector must be an object')
        config=copy.deepcopy(config)
        self.config={**config,'window':_selector(config['window']),
                     'controls':{name:_control_spec(control) for name,control in config['controls'].items()}}
        self._config_bytes=canonical(self.config)
        self.sha256=hashlib.sha256(self._config_bytes).hexdigest()

    def inspect(self,app):
        try:
            unchanged=(canonical(self.config)==self._config_bytes and
                       self.sha256==hashlib.sha256(self._config_bytes).hexdigest())
        except (TypeError,ValueError,RecursionError):unchanged=False
        if not unchanged:raise UnsafeOperation('Profile changed after qualification')
        # Use the frozen snapshot throughout this inspection, not public mutable
        # dictionaries a caller/backend might change while a native read runs.
        config=json.loads(self._config_bytes)
        metadata=app.backend.app_metadata(app.pid)
        mismatch=[key for key in ('bundle_id','version','build') if metadata.get(key)!=config[key]]
        report={'qualified':False,'profile_sha256':self.sha256,'identity_mismatch':mismatch,'controls':{},
                'structure_match':False,'ability_qualified':False,'action_tested':False}
        if mismatch:return report
        scope=window_scope(app,**config['window'])
        for name,spec in config['controls'].items():
            control={'status':'UNAVAILABLE','structure_match':False,'ability_qualified':False,
                     'actions':{action:False for action in spec.get('actions',[])},
                     'settable':{attribute:False for attribute in spec.get('settable',[])},'action_tested':False}
            try:
                if 'path' in spec:
                    locator=app.locator_path(spec['path'])
                    # A callable re-acquires AXWindows each resolution; never
                    # capture the initial window's native reference in a path.
                    locator.root=lambda:window_scope(app,**config['window']).root
                    element=locator.resolve()
                else:element=scope.find(**spec)
                control.update(status='UNIQUE',role=element.get('AXRole'),structure_match=True)
            except Exception as exc:control['error']=type(exc).__name__
            else:control.update(_capabilities(app.backend,element.ref,spec))
            report['controls'][name]=control
        report['structure_match']=all(c['structure_match'] for c in report['controls'].values())
        report['ability_qualified']=all(c['ability_qualified'] for c in report['controls'].values())
        report['qualified']=report['structure_match'] and report['ability_qualified']
        # Keep the legacy structure hash independent of capability availability.
        structure={name:{k:v for k,v in control.items() if k in ('status','role','error')}
                   for name,control in report['controls'].items()}
        report['structure_sha256']=hashlib.sha256(canonical(structure)).hexdigest()
        return report

    def require(self,app):
        report=self.inspect(app)
        if not report['qualified']:raise UnsafeOperation('Profile qualification failed')
        return report

    @staticmethod
    def diff(before,after):
        names=set(before.get('controls',{}))|set(after.get('controls',{}))
        return {'identity_changed':before.get('identity_mismatch')!=after.get('identity_mismatch'),
                'changed_controls':sorted(n for n in names if before.get('controls',{}).get(n)!=after.get('controls',{}).get(n)),
                'qualified':after.get('qualified') is True}
