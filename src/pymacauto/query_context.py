"""Short-lived read-only evidence for one synchronous structural phase.

Never spans an input, journal commit, wait iteration or table sample. Values
and arbitrary content attributes are read fresh; no backend is monkey-patched.
"""
from contextvars import ContextVar
import threading
from .errors import AttributeUnsupported,UnsafeOperation,SearchLimitExceeded

_ACTIVE=ContextVar('pymacauto_query_context',default=None)
_STRUCTURAL=frozenset(('AXRole','AXIdentifier','AXEnabled','AXChildren',
                      'AXWindows','AXSheets','AXModal'))


def active_context(backend):
    context=_ACTIVE.get()
    return context if context is not None and context.backend is backend else None


class QueryContext:
    def __init__(self,app,*,guard=False):
        self.app,self.backend=app,app.backend
        self._thread=threading.get_ident()
        self._cache={};self._keys={};self._plans={};self._token=None;self._closed=False;self.guard=guard
    def __enter__(self):
        if threading.get_ident()!=self._thread:raise UnsafeOperation('Query context thread mismatch')
        if self._closed or self._token is not None:raise UnsafeOperation('Query context cannot be reused')
        if _ACTIVE.get() is not None:raise UnsafeOperation('Nested query contexts not supported')
        self._token=_ACTIVE.set(self)
        return self
    def __exit__(self,*args):
        if self._token is not None:_ACTIVE.reset(self._token);self._token=None
        self._cache.clear();self._keys.clear();self._plans.clear();self._closed=True
    def _check(self):
        if threading.get_ident()!=self._thread:raise UnsafeOperation('Query context thread mismatch')
        if self._closed or self._token is None or _ACTIVE.get() is not self:
            raise UnsafeOperation('Inactive query context')
    def selector(self,criteria):
        self._check()
        key=tuple((name,type(value),value) for name,value in criteria.items())
        if key not in self._plans:
            from .plans import compile_selector
            self._plans[key]=compile_selector(criteria)
        return self._plans[key]

    def _key(self,ref):
        identity=id(ref)
        if identity not in self._keys:
            if len(self._keys)>=self.app.max_nodes*(self.app.max_depth+1):raise SearchLimitExceeded('Query identity budget')
            self._keys[identity]=(ref,self.backend.key(ref))
        return self._keys[identity][1]

    @staticmethod
    def _copy(value):
        # Retain native reference identity; copy only normalized containers.
        if isinstance(value,list):return [QueryContext._copy(v) for v in value]
        if isinstance(value,tuple):return tuple(QueryContext._copy(v) for v in value)
        if isinstance(value,dict):return {k:QueryContext._copy(v) for k,v in value.items()}
        return value
    def get(self,ref,attribute):
        self._check()
        if attribute=='AXValue':
            try:secure=self.backend.get(ref,'AXSubrole')=='AXSecureTextField'
            except AttributeUnsupported:secure=False
            if secure:raise UnsafeOperation('Secure field values are not exposed')
        key=(self._key(ref),attribute)
        if attribute in _STRUCTURAL and key in self._cache:return self._copy(self._cache[key])
        try:value=self.backend.get(ref,attribute)
        except AttributeUnsupported:value=None
        if attribute in _STRUCTURAL:
            if len(self._cache)>=self.app.max_nodes*len(_STRUCTURAL):raise SearchLimitExceeded('Query evidence budget')
            self._cache[key]=self._copy(value)
        return self._copy(value)
    def prefetch(self,ref,attributes):
        self._check()
        names=tuple(dict.fromkeys(attributes))
        if not names or any(n not in _STRUCTURAL for n in names):raise ValueError('Only structural attributes may be prefetched')
        missing=[n for n in names if (self._key(ref),n) not in self._cache]
        if not missing:return
        method=getattr(self.backend,'get_many',None)
        if not callable(method):
            for name in missing:self.get(ref,name)
            return
        if len(self._cache)+len(missing)>self.app.max_nodes*len(_STRUCTURAL):raise SearchLimitExceeded('Query evidence budget')
        values=method(ref,missing,optional=missing)
        if not isinstance(values,dict) or set(values)!=set(missing):raise UnsafeOperation('Incomplete structural batch')
        for name in missing:self._cache[(self._key(ref),name)]=self._copy(values[name])
    def set(self,*args,**kwargs):raise UnsafeOperation('Query contexts cannot mutate UI')
    def perform(self,*args,**kwargs):raise UnsafeOperation('Query contexts cannot mutate UI')
