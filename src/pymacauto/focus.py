"""Explicit foreground verification helpers; never activate apps implicitly."""
import time
from .core import _positive


def current_front(workspace):
    from Foundation import NSRunLoop,NSDate
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.001))
    front=workspace.frontmostApplication()
    return int(front.processIdentifier()) if front else None


def foreground_identity(workspace):
    """Fresh public identity only: no window titles, values or activation."""
    current_front(workspace)
    app=workspace.frontmostApplication()
    if app is None:return None
    launched=app.launchDate()
    return {'pid':int(app.processIdentifier()),'bundle_id':str(app.bundleIdentifier() or ''),
            'launch_epoch':float(launched.timeIntervalSince1970()) if launched is not None else None}


class ForegroundGuard:
    """Cooperative stop source; latch first observed transition, never restore."""
    def __init__(self,read_identity):
        import copy
        self._read=read_identity
        self._before=copy.deepcopy(read_identity())
        if not isinstance(self._before,dict) or type(self._before.get('pid')) is not int or self._before['pid']<=0:
            raise ValueError('Initial foreground identity unavailable')
        self._change=None
    def is_set(self):
        import copy
        if self._change is not None:return True
        after=self._read()
        if after!=self._before:
            self._change={'before':copy.deepcopy(self._before),'after':copy.deepcopy(after),
                          'observed_monotonic':time.monotonic()}
            return True
        return False
    def report(self):
        import copy
        return {'initial':copy.deepcopy(self._before),'first_change':copy.deepcopy(self._change),
                'changed':self._change is not None}


def wait_for(predicate,seconds):
    _positive(seconds,'seconds',zero=True)
    deadline=time.monotonic()+seconds
    while True:
        value=predicate()
        if value:return value
        remaining=deadline-time.monotonic()
        if remaining<=0:return None
        time.sleep(min(.03,remaining))
