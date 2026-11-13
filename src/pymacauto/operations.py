"""Single-dispatch operations with explicit independent postconditions.

Receipts distinguish no dispatch from uncertain dispatch. They deliberately
omit target values, selectors and exception messages, which may be private.
"""
import copy
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
from .errors import ElementNotFound, UnsafeOperation,StopRequested,LayoutChanged
from .query import window_scope, QueryScope


class Condition:
    def __init__(self,locator,*,state='exists',**criteria):
        if state not in ('exists','gone') or (state=='gone' and criteria):
            raise ValueError('Condition state must be exists or gone')
        self.locator,self.state=locator,state
        self.criteria=_selector(criteria) if criteria else {}

    def describe(self):
        return {'state':self.state,'criteria':copy.deepcopy(self.criteria)}

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
    def __init__(self,app,*,window,journal=None,profile=None,stop=None,readonly=False):
        self.app=app;self.window=_selector(window);self.profile=profile;self.stop=stop;self.readonly=readonly
        self._lock=threading.RLock();self._closed=False;self._receipts={};self._fingerprints={}
        from .journal import Journal
        identity=getattr(app.backend,'process_identity',None)
        self.identity=identity(app.pid) if callable(identity) and journal is not None else dict(app.info)
        self.journal=Journal(journal,readonly=True) if journal is not None and readonly else (Journal(journal) if journal is not None else None)

    def _request(self,target,postcondition,precondition,action):
        def locator(value):
            if value.app is not self.app or (self.journal is not None and value.root is not None):
                raise ValueError('Durable operations require application-rooted lazy Locators')
            result={'chain':value.chain,'root':None if value.root is None else id(value.root)}
            if hasattr(value,'descriptor'):result['descriptor']=copy.deepcopy(value.descriptor)
            return result
        def condition(value):
            if value is None:return None
            if type(value) is Condition:return {'locator':locator(value.locator),'state':value.state,'criteria':value.criteria}
            return {'locator':locator(value.locator),'condition':value.describe()}
        return {'identity':self.identity,'profile':self.profile.sha256 if self.profile is not None else None,'window':self.window,'target':locator(target),
                'action':action,'post':condition(postcondition),'pre':condition(precondition)}

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True
            if self.journal is not None:self.journal.close()

    def _check_stop(self):
        if self.stop is not None:
            if hasattr(self.stop,'is_set'):stopped=self.stop.is_set()
            else:
                try:Path(self.stop).lstat();stopped=True
                except FileNotFoundError:stopped=False
            if stopped:raise StopRequested('Cooperative stop requested')

    def _guard(self,target):
        self._check_stop()
        identity=getattr(self.app.backend,'process_identity',None)
        if self.journal is not None and callable(identity) and identity(self.app.pid)!=self.identity:
            raise UnsafeOperation('Application process identity changed')
        if self.profile is not None:self.profile.require(self.app)
        scope=window_scope(self.app,**self.window)
        b=self.app.backend
        windows=b.get(self.app._root,'AXWindows')
        if not isinstance(windows,(list,tuple)):raise UnsafeOperation('Window list unavailable')
        # Query-local membership evidence, never retained across operations.
        approved_members=set()
        for window in windows:
            if _get(b,window,'AXModal') is True or _get(b,window,'AXSubrole') in ('AXDialog','AXSystemDialog') or _get(b,window,'AXRole')=='AXSheet':
                raise UnsafeOperation('Unexpected modal window')
            for ref,role in QueryScope(self.app,window,leaf_roles=('AXTable','AXList','AXOutline')).walk():
                if b.key(window)==b.key(scope.root):approved_members.add(b.key(ref))
                if role=='AXSheet' or _get(b,ref,'AXSheets') or _get(b,ref,'AXModal') is True:
                    raise UnsafeOperation('Unexpected sheet')
        for step in target.chain:
            if step.get('$path') and step.get('index') is not None and step.get('expected_count') is None:
                raise UnsafeOperation('Protected indexed paths require expected_count')
        element=target.resolve()
        if element.app is not self.app:raise UnsafeOperation('Target belongs to another connection')
        if b.key(element.ref) not in approved_members:
            members={b.key(ref) for ref,_ in QueryScope(self.app,scope.root).walk()}
            if b.key(element.ref) not in members:raise UnsafeOperation('Target outside approved window')
        element._writable()
        role=_get(b,element.ref,'AXRole');enabled=_get(b,element.ref,'AXEnabled')
        if enabled is not True and not (enabled is None and role in ('AXRow','AXCell','AXTabGroup')):
            raise UnsafeOperation('Target not explicitly enabled')
        return element

    def _guard_same(self,target,element):
        fresh=self._guard(target)
        if self.app.backend.key(fresh.ref)!=self.app.backend.key(element.ref):
            raise LayoutChanged('Target identity changed during multi-step operation')

    def previous(self,target,*,postcondition,precondition=None,operation_id,action='AXPress'):
        """Validate replay identity without observing or dispatching input."""
        from .journal import canonical
        import hashlib
        with self._lock:
            if self._closed:raise UnsafeOperation('Session closed')
            request=self._request(target,postcondition,precondition,action)
            fingerprint=self.journal.fingerprint(request) if self.journal else hashlib.sha256(canonical(request)).hexdigest()
            if operation_id in self._receipts:
                if fingerprint!=self._fingerprints[operation_id]:raise UnsafeOperation('Operation ID conflict')
                return copy.deepcopy(self._receipts[operation_id])
            return self.journal.lookup(operation_id,fingerprint) if self.journal else None

    def remember_observation(self,target,*,postcondition,precondition=None,operation_id):
        """Reserve an ID for an already-observed state, never causal success."""
        if self.readonly:raise UnsafeOperation('Read-only session cannot reserve an operation')
        if not isinstance(operation_id,str) or not operation_id or len(operation_id)>128:raise ValueError('Invalid operation_id')
        from .journal import canonical
        import hashlib
        with self._lock:
            self._check_stop()
            existing=self.previous(target,postcondition=postcondition,precondition=precondition,operation_id=operation_id)
            if existing is not None:return existing
            if len(self._receipts)>=1024:raise UnsafeOperation('Receipt capacity reached; new session required')
            request=self._request(target,postcondition,precondition,'AXPress')
            fingerprint=self.journal.fingerprint(request) if self.journal else hashlib.sha256(canonical(request)).hexdigest()
            receipt={'operation_id':operation_id,'status':'NOT_DISPATCHED','dispatch_attempted':False,
                     'attempts':0,'verified':False,'observed':True,'error':None}
            if self.journal is not None:
                existing=self.journal.claim(operation_id,fingerprint)
                if existing is not None:return existing
                self.journal.finish(operation_id,receipt)
            self._receipts[operation_id]=copy.deepcopy(receipt);self._fingerprints[operation_id]=fingerprint
            return receipt

    def recover(self,operation_id,target,*,postcondition,precondition=None,action='AXPress',timeout=5,interval=.05):
        """Observation only, never promotes uncertainty to causal confirmation."""
        _positive(timeout,'timeout',zero=True);_positive(interval,'interval')
        with self._lock:
            if self._closed or self.journal is None:raise UnsafeOperation('Open durable session required')
            request=self._request(target,postcondition,precondition,action)
            identity=getattr(self.app.backend,'process_identity',None)
            if callable(identity) and identity(self.app.pid)!=self.identity:raise UnsafeOperation('Application identity changed')
            record=self.journal.lookup(operation_id,self.journal.fingerprint(request))
            if record is None:raise UnsafeOperation('No original operation')
            start=time.monotonic()
            while True:
                self._check_stop()
                if postcondition.check():return {**record,'status':'RECOVERY_OBSERVED','verified':False,'observed':True,'recovered':True}
                remaining=timeout-(time.monotonic()-start)
                if remaining<=0:return {**record,'observed':False,'recovered':True}
                time.sleep(min(interval,remaining))

    def apply(self,target,kind,*,value=None,postcondition=None,precondition=None,operation_id=None,timeout=5,events=False):
        if kind not in ('fill','check','numeric','select','tab','choose'):raise ValueError('Unknown protected control operation')
        if kind=='fill' and not isinstance(value,str):raise ValueError('fill requires a string')
        if postcondition is None:
            if kind in ('tab','choose','select'):raise ValueError('Independent postcondition required for selection')
            if kind=='check':postcondition=Condition(target,value=int(value) if type(value) is bool else value)
            else:postcondition=Condition(target,value=value)
        return self.execute(target,postcondition=postcondition,precondition=precondition,
            action={'kind':kind,'value':value},operation_id=operation_id,timeout=timeout,events=events)

    def execute(self,target,*,postcondition,precondition=None,action='AXPress',timeout=5,interval=.05,operation_id=None,events=False):
        if self.readonly:raise UnsafeOperation('Read-only session cannot dispatch')
        from .deadlines import Deadline,classify_error
        budget=Deadline(timeout)
        action=copy.deepcopy(action)
        if not isinstance(postcondition,Condition) or (precondition is not None and not isinstance(precondition,Condition)):
            raise ValueError('Explicit Condition required')
        if postcondition.locator.app is not self.app or (precondition and precondition.locator.app is not self.app):
            raise ValueError('Conditions must use the same application connection')
        if type(events) is not bool:raise ValueError('events must be bool')
        _positive(timeout,'timeout',zero=True);_positive(interval,'interval')
        if operation_id is not None and (not isinstance(operation_id,str) or not operation_id or len(operation_id)>128):
            raise ValueError('operation_id must be a nonempty string of at most 128 characters')
        from .journal import canonical
        import hashlib
        request=self._request(target,postcondition,precondition,action)
        fingerprint=self.journal.fingerprint(request) if self.journal is not None else hashlib.sha256(canonical(request)).hexdigest()
        start=time.monotonic()
        receipt={'operation_id':operation_id or uuid.uuid4().hex,'status':'NOT_DISPATCHED','dispatch_attempted':False,
                 'verified':False,'attempts':0,'error':None,'timings':{}}
        with self._lock:
            if operation_id in self._receipts:
                if fingerprint is not None and self._fingerprints[operation_id]!=fingerprint:raise UnsafeOperation('Operation ID conflict')
                return copy.deepcopy(self._receipts[operation_id])
            if self.journal is not None and not self._closed:
                existing=self.journal.lookup(receipt['operation_id'],fingerprint)
                if existing is not None:return existing
            lock=_app_lock(self.app.pid);held=False;fd=None;claimed=False
            error_stage='preflight'
            try:
                if len(self._receipts)>=1024:raise UnsafeOperation('Receipt capacity reached; new session required')
                if not lock.acquire(blocking=False):raise UnsafeOperation('Application operation busy')
                held=True;fd=_file_lock(self.app.pid)
                if self._closed:raise UnsafeOperation('Session closed')
                stage=time.monotonic()
                if precondition is not None and not precondition.check():
                    raise UnsafeOperation('Precondition not met')
                if postcondition.check():raise UnsafeOperation('Postcondition already satisfied; use a distinct result')
                element=self._guard(target)
                window_key=self.app.backend.key(window_scope(self.app,**self.window).root)
                receipt['timings']['preflight_seconds']=time.monotonic()-stage
                if isinstance(action,str):
                    if action not in element.backend.actions(element.ref):raise UnsafeOperation('Action unavailable')
                elif not isinstance(action,dict) or set(action)!={'kind','value'}:
                    raise ValueError('Invalid control operation')
                error_stage='pre_dispatch'
                if timeout>0:budget.require(error_stage)
                stage=time.monotonic()
                if self.journal is not None:
                    previous=self.journal.claim(receipt['operation_id'],fingerprint)
                    if previous is not None:return previous
                    claimed=True
                    # Commit acknowledgement may fail after disk commit: be
                    # conservative about intent even when intent() raises.
                    receipt.update(status='DISPATCHED_UNCONFIRMED',dispatch_attempted=True,attempts=1)
                    self.journal.intent(receipt['operation_id'])
                receipt['timings']['intent_seconds']=time.monotonic()-stage
                stage=time.monotonic()
                # Intent fsync may give the UI time to change: resolve and
                # guard again, but never substitute a replacement reference.
                self._guard_same(target,element)
                if self.app.backend.key(window_scope(self.app,**self.window).root)!=window_key:raise LayoutChanged('Window changed before dispatch')
                if precondition is not None and not precondition.check():raise UnsafeOperation('Precondition changed before dispatch')
                if postcondition.check():raise UnsafeOperation('Postcondition changed before dispatch')
                self._check_stop()
                if timeout>0:budget.require('pre_dispatch')
                error_stage='dispatch'
                receipt.update(status='DISPATCHED_UNCONFIRMED',dispatch_attempted=True,attempts=1)
                if isinstance(action,str):element.perform(action)
                else:
                    from .controls import Control
                    def before_input():
                        self._guard_same(target,element)
                        if timeout>0:budget.require('dispatch')
                    control=Control(element,before_input=before_input);kind=action['kind'];value=action['value']
                    if kind=='fill':
                        if _get(element.backend,element.ref,'AXRole') not in ('AXTextField','AXTextArea','AXComboBox'):raise UnsafeOperation('Editable text role required')
                        before_input()
                        element.set_value(value,verify_timeout=budget.remaining())
                    elif kind=='check':control.set_checked(value,timeout=budget.remaining())
                    elif kind=='numeric':control.set_numeric(value,timeout=budget.remaining())
                    elif kind=='select':control.select(timeout=budget.remaining())
                    elif kind=='tab':control.select_tab(value,timeout=budget.remaining())
                    elif kind=='choose':control.choose(value,timeout=budget.remaining())
                    else:raise ValueError('Unknown control operation')
                receipt['timings']['dispatch_seconds']=time.monotonic()-stage
                stage=time.monotonic()
                error_stage='observation'
                if timeout>0:budget.require(error_stage)
                if events:
                    from .events import wait_condition
                    observation=wait_condition(postcondition,timeout=budget.remaining(),fallback_interval=max(interval,.25),before_check=self._check_stop)
                    if timeout>0:budget.require('observation')
                    receipt.update(status='CONFIRMED',verified=True,observation=observation)
                while not receipt['verified']:
                    self._check_stop()
                    if timeout>0:budget.require('observation')
                    if postcondition.check():
                        if timeout>0:budget.require('observation')
                        receipt.update(status='CONFIRMED',verified=True);break
                    remaining=budget.remaining()
                    if remaining<=0:
                        from .errors import WaitTimeout
                        raise WaitTimeout('Total observation budget exhausted')
                    time.sleep(min(interval,remaining))
                receipt['timings']['observation_seconds']=time.monotonic()-stage
            except Exception as exc:
                receipt['error']=type(exc).__name__
                receipt['error_category']=classify_error(exc)
                receipt['error_stage']=error_stage
                if hasattr(exc,'code') and hasattr(exc,'operation'):
                    receipt['native_error']={'code':exc.code,'operation':exc.operation}
            finally:
                # Record uncertainty even when KeyboardInterrupt/SystemExit
                # interrupts a native call; replay must not repeat the input.
                receipt['elapsed_seconds']=time.monotonic()-start
                if operation_id is not None and len(self._receipts)<1024:
                    self._receipts[operation_id]=copy.deepcopy(receipt);self._fingerprints[operation_id]=fingerprint
                try:
                    if claimed:self.journal.finish(receipt['operation_id'],receipt)
                except Exception as exc:
                    receipt['persistence_error']=type(exc).__name__
                    receipt['verified']=False
                    if receipt['dispatch_attempted']:receipt['status']='DISPATCHED_UNCONFIRMED'
                    if operation_id is not None:self._receipts[operation_id]=copy.deepcopy(receipt)
                try:
                    if fd is not None:os.close(fd)
                finally:
                    if held:lock.release()
            return receipt
