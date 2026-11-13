"""Thread-affine AX observer with explicit unsupported-notification fallback."""
import threading
import time
from .core import _positive
from .errors import UnsafeOperation


class AXEvents:
    def __init__(self,app,*,targets=None,notifications=('AXValueChanged','AXCreated','AXUIElementDestroyed')):
        self.app=app;self.targets=list(targets) if targets is not None else [app._root]
        if not self.targets or not notifications or not all(isinstance(n,str) and n.startswith('AX') for n in notifications):
            raise ValueError('Explicit AX targets and notifications required')
        self.notifications=tuple(notifications)
        if len(set(self.notifications))!=len(self.notifications):raise ValueError('Duplicate notifications')
        self.received=0;self.unsupported=[]
        self._registered=[];self._observer=None;self._closed=True
        self._thread=threading.get_ident()
    def _owner(self):
        if threading.get_ident()!=self._thread:raise UnsafeOperation('AXEvents must run on its owning thread')
    def __enter__(self):
        self._owner()
        if not self._closed:raise UnsafeOperation('Observer already open')
        import CoreFoundation as cf
        ax=self.app.backend._ax
        self._cf,self._ax=cf,ax
        import objc
        @objc.callbackFor(ax.AXObserverCreate)
        def callback(observer,element,name,context):self.received+=1
        self._callback=callback
        code,observer=ax.AXObserverCreate(self.app.pid,callback,None)
        self.app.backend._check('AXObserverCreate',code)
        self._observer=observer;self._closed=False
        self._loop=None;self._source=None
        try:
            self._loop=cf.CFRunLoopGetCurrent();self._source=ax.AXObserverGetRunLoopSource(observer)
            for target in self.targets:
                for name in self.notifications:
                    code=ax.AXObserverAddNotification(observer,target,name,None)
                    if code==ax.kAXErrorNotificationUnsupported:
                        self.unsupported.append(name);continue
                    self.app.backend._check('AXObserverAddNotification',code)
                    self._registered.append((target,name))
            cf.CFRunLoopAddSource(self._loop,self._source,cf.kCFRunLoopDefaultMode)
        except BaseException:
            self.close();raise
        return self
    @property
    def mode(self):return 'events+poll' if self._registered else 'poll'
    def pause(self,seconds):
        self._owner();_positive(seconds,'seconds',zero=True)
        if self._closed:raise UnsafeOperation('Observer closed')
        if self._registered:
            self._cf.CFRunLoopRunInMode(self._cf.kCFRunLoopDefaultMode,seconds,True)
        else:time.sleep(seconds)
    def close(self):
        self._owner()
        if self._closed:return
        self._closed=True
        failures=[]
        try:
            if self._loop is not None and self._source is not None:
                self._cf.CFRunLoopRemoveSource(self._loop,self._source,self._cf.kCFRunLoopDefaultMode)
        finally:
            for target,name in self._registered:
                try:
                    code=self._ax.AXObserverRemoveNotification(self._observer,target,name)
                    self.app.backend._check('AXObserverRemoveNotification',code)
                except Exception as exc:failures.append(type(exc).__name__)
            self._registered.clear();self._observer=None;self._callback=None
        if failures:
            from .errors import MacAXError
            raise MacAXError('Observer cleanup failed: '+','.join(failures))
    def __exit__(self,kind,value,traceback):
        try:self.close()
        except Exception as exc:
            if value is None:raise
            if hasattr(value,'add_note'):value.add_note('Observer cleanup: '+type(exc).__name__)


def wait_condition(condition,*,timeout=5,fallback_interval=.25,before_check=None):
    """Read immediately and after notifications/bounded fallback; no actions."""
    _positive(timeout,'timeout',zero=True);_positive(fallback_interval,'fallback_interval')
    app=condition.locator.app;start=time.monotonic();checks=0
    from .errors import ElementNotFound
    try:targets=[app._root,condition.locator.resolve().ref]
    except ElementNotFound:targets=[app._root]
    with AXEvents(app,targets=targets) as events:
        while True:
            if before_check is not None:before_check()
            checks+=1
            if condition.check():return {'verified':True,'mode':events.mode,'events':events.received,
                'checks':checks,'elapsed_seconds':time.monotonic()-start,'unsupported':sorted(set(events.unsupported))}
            remaining=timeout-(time.monotonic()-start)
            if remaining<=0:
                from .errors import WaitTimeout
                raise WaitTimeout('Event-assisted condition not observed')
            events.pause(min(fallback_interval,remaining))
