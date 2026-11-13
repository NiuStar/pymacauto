"""Single-dispatch operations with explicit independent postconditions.

Receipts distinguish no dispatch from uncertain dispatch. They deliberately
omit target values, selectors and exception messages, which may be private.
"""
import threading
import time
import uuid
import os
import stat
from pathlib import Path

_APP_LOCKS={}
_LOCKS_GUARD=threading.Lock()


def _app_lock(pid):
    with _LOCKS_GUARD:return _APP_LOCKS.setdefault(pid,threading.Lock())


def _file_lock(pid):
    import fcntl
    directory=Path.home()/'Library/Caches/pymacauto/locks'
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    meta=directory.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid!=os.getuid() or meta.st_mode & 0o077:
        raise UnsafeOperation('Lock directory is not private')
    fd=os.open(directory/(str(pid)+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid() or meta.st_mode & 0o077 or meta.st_nlink!=1:
            raise UnsafeOperation('Invalid lock file')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BaseException:
        os.close(fd);raise
    return fd
from .core import Element, _get, _matches, _selector, _positive
from .errors import ElementNotFound, UnsafeOperation
from .query import window_scope, QueryScope


class Condition:
    def __init__(self,locator,*,state='exists',**criteria):
        if state not in ('exists','gone') or (state=='gone' and criteria):
            raise ValueError('Condition state must be exists or gone')
        self.locator,self.state=locator,state
        self.criteria=_selector(criteria) if criteria else {}

    def check(self):
        try:element=self.locator.resolve()
        except ElementNotFound:return self.state=='gone'
        return self.state=='exists' and _matches(element.backend,element.ref,self.criteria)


class OperationSession:
    """Explicit target window, serialized operations, no implicit focus or retry.

    Reuse within a with-block. Closing does not quit the target application.
    A postcondition is an observation supplied by the caller, not a claim that
    the library understands transactions. It may deliberately describe a modal
    result; modals are rejected before input, not automatically dismissed.
    """
    def __init__(self,app,*,window):
        self.app=app;self.window=_selector(window)
        self._lock=threading.RLock();self._closed=False;self._receipts={}

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        with self._lock:self._closed=True

    def _guard(self,target):
        scope=window_scope(self.app,**self.window)
        b=self.app.backend
        windows=b.get(self.app._root,'AXWindows')
        if not isinstance(windows,(list,tuple)):raise UnsafeOperation('Window list unavailable')
        # Inspect structural nodes but exclude data-heavy table/list subtrees.
        for window in windows:
            if _get(b,window,'AXModal') is True or _get(b,window,'AXSubrole') in ('AXDialog','AXSystemDialog') or _get(b,window,'AXRole')=='AXSheet':
                raise UnsafeOperation('Unexpected modal window')
            for ref,_ in QueryScope(self.app,window,leaf_roles=('AXTable','AXList','AXOutline')).walk():
                if _get(b,ref,'AXRole')=='AXSheet' or _get(b,ref,'AXSheets') or _get(b,ref,'AXModal') is True:
                    raise UnsafeOperation('Unexpected sheet')
        element=target.resolve()
        if element.app is not self.app:raise UnsafeOperation('Target belongs to another connection')
        members={b.key(ref) for ref,_ in QueryScope(self.app,scope.root).walk()}
        if b.key(element.ref) not in members:raise UnsafeOperation('Target outside approved window')
        element._writable()
        if _get(b,element.ref,'AXEnabled') is not True:
            raise UnsafeOperation('Target not explicitly enabled')
        return element

    def execute(self,target,*,postcondition,precondition=None,action='AXPress',timeout=5,interval=.05,operation_id=None,events=False):
        if not isinstance(postcondition,Condition) or (precondition is not None and not isinstance(precondition,Condition)):
            raise ValueError('Explicit Condition required')
        if postcondition.locator.app is not self.app or (precondition and precondition.locator.app is not self.app):
            raise ValueError('Conditions must use the same application connection')
        if type(events) is not bool:raise ValueError('events must be bool')
        _positive(timeout,'timeout',zero=True);_positive(interval,'interval')
        if operation_id is not None and (not isinstance(operation_id,str) or not operation_id or len(operation_id)>128):
            raise ValueError('operation_id must be a nonempty string of at most 128 characters')
        start=time.monotonic()
        receipt={'operation_id':operation_id or uuid.uuid4().hex,'status':'NOT_DISPATCHED','dispatch_attempted':False,
                 'verified':False,'attempts':0,'error':None}
        with self._lock:
            if operation_id in self._receipts:return dict(self._receipts[operation_id])
            lock=_app_lock(self.app.pid);held=False;fd=None
            try:
                if len(self._receipts)>=1024:raise UnsafeOperation('Receipt capacity reached; new session required')
                if not lock.acquire(blocking=False):raise UnsafeOperation('Application operation busy')
                held=True;fd=_file_lock(self.app.pid)
                if self._closed:raise UnsafeOperation('Session closed')
                if precondition is not None and not precondition.check():
                    raise UnsafeOperation('Precondition not met')
                if postcondition.check():raise UnsafeOperation('Postcondition already satisfied; use a distinct result')
                element=self._guard(target)
                if action not in element.backend.actions(element.ref):raise UnsafeOperation('Action unavailable')
                receipt.update(status='DISPATCHED_UNCONFIRMED',dispatch_attempted=True,attempts=1)
                element.perform(action)
                if events:
                    from .events import wait_condition
                    observation=wait_condition(postcondition,timeout=timeout,fallback_interval=max(interval,.25))
                    receipt.update(status='CONFIRMED',verified=True,observation=observation)
                deadline=time.monotonic()+timeout
                while not receipt['verified']:
                    if postcondition.check():
                        receipt.update(status='CONFIRMED',verified=True);break
                    remaining=deadline-time.monotonic()
                    if remaining<=0:break
                    time.sleep(min(interval,remaining))
            except Exception as exc:
                receipt['error']=type(exc).__name__
            finally:
                # Record uncertainty even when KeyboardInterrupt/SystemExit
                # interrupts a native call; replay must not repeat the input.
                receipt['elapsed_seconds']=time.monotonic()-start
                if operation_id is not None and len(self._receipts)<1024:self._receipts[operation_id]=dict(receipt)
                try:
                    if fd is not None:os.close(fd)
                finally:
                    if held:lock.release()
            return receipt
