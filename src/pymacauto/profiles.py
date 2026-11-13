"""Version-qualified app profiles; reports never include captured AX values."""
import hashlib
from .core import _selector
from .errors import UnsafeOperation,ElementNotFound
from .journal import canonical
from .query import window_scope


class AppProfile:
    def __init__(self,config):
        required={'bundle_id','version','build','window','controls'}
        if not isinstance(config,dict) or set(config)!=required:raise ValueError('Profile requires exact identity/window/controls fields')
        if not all(isinstance(config[k],str) and config[k] for k in ('bundle_id','version','build')):raise ValueError('Nonempty identity required')
        if not isinstance(config['controls'],dict) or not config['controls']:raise ValueError('Nonempty named controls required')
        import copy
        config=copy.deepcopy(config)
        self.config={**config,'window':_selector(config['window']),
                     'controls':{name:_selector(selector) for name,selector in config['controls'].items()}}
        if not all(isinstance(k,str) and k for k in self.config['controls']):raise ValueError('Nonempty control names required')
        self.sha256=hashlib.sha256(canonical(self.config)).hexdigest()
        self._config_bytes=canonical(self.config)
    def inspect(self,app):
        if canonical(self.config)!=self._config_bytes:raise UnsafeOperation('Profile changed after qualification')
        metadata=app.backend.app_metadata(app.pid)
        mismatch=[key for key in ('bundle_id','version','build') if metadata.get(key)!=self.config[key]]
        report={'qualified':False,'profile_sha256':self.sha256,'identity_mismatch':mismatch,'controls':{}}
        if mismatch:return report
        scope=window_scope(app,**self.config['window'])
        for name,selector in self.config['controls'].items():
            try:
                element=scope.find(**selector)
                report['controls'][name]={'status':'UNIQUE','role':element.get('AXRole')}
            except Exception as exc:
                report['controls'][name]={'status':'UNAVAILABLE','error':type(exc).__name__}
        report['qualified']=all(c['status']=='UNIQUE' for c in report['controls'].values())
        report['structure_sha256']=hashlib.sha256(canonical(report['controls'])).hexdigest()
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
