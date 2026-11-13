"""Explicit foreground verification helpers; never activate apps implicitly."""
import time
from .core import _positive


def current_front(workspace):
    from Foundation import NSRunLoop,NSDate
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.001))
    front=workspace.frontmostApplication()
    return int(front.processIdentifier()) if front else None


def wait_for(predicate,seconds):
    _positive(seconds,'seconds',zero=True)
    deadline=time.monotonic()+seconds
    while True:
        value=predicate()
        if value:return value
        remaining=deadline-time.monotonic()
        if remaining<=0:return None
        time.sleep(min(.03,remaining))
