"""Opt-in in-process native call counters. Do not share backend while active."""
from collections import Counter
import time
from .errors import UnsafeOperation

class AXMetrics:
    def __init__(self,backend):self.backend=backend;self.counts=Counter();self.seconds=Counter();self.original={}
    def __enter__(self):
        if getattr(self.backend,'_metrics_active',False):raise UnsafeOperation('Backend metrics already active')
        self.backend._metrics_active=True
        for name in ('get','get_many','set','perform','actions','is_settable'):
            method=getattr(self.backend,name,None)
            if not callable(method):continue
            self.original[name]=method
            def wrapped(*args,_name=name,_method=method,**kwargs):
                start=time.monotonic();self.counts[_name]+=1
                try:return _method(*args,**kwargs)
                finally:self.seconds[_name]+=time.monotonic()-start
            setattr(self.backend,name,wrapped)
        return self
    def __exit__(self,*args):
        for name,method in self.original.items():setattr(self.backend,name,method)
        self.backend._metrics_active=False
    def summary(self):return {'calls':dict(self.counts),'native_seconds':dict(self.seconds)}
