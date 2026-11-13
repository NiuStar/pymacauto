"""Observation deadlines; not hard cancellation of native AX RPCs."""
import time
from .core import _positive
from .errors import WaitTimeout

class Deadline:
    def __init__(self,seconds):
        _positive(seconds,'timeout',zero=True)
        self.expires=time.monotonic()+seconds
    def remaining(self):return max(0,self.expires-time.monotonic())
    def require(self,stage):
        if time.monotonic()>=self.expires:raise WaitTimeout('Total budget exhausted at '+stage)


def classify_error(exc):
    from .errors import (PermissionDenied,ElementNotFound,AmbiguousMatch,SearchLimitExceeded,
                         WaitTimeout,UnsafeOperation,AXError,VerificationFailed,StopRequested,LayoutChanged)
    import sqlite3
    if isinstance(exc,StopRequested):return 'STOPPED'
    if isinstance(exc,LayoutChanged):return 'LAYOUT_CHANGED'
    if isinstance(exc,PermissionDenied):return 'PERMISSION_DENIED'
    if isinstance(exc,ElementNotFound):return 'TARGET_MISSING'
    if isinstance(exc,(AmbiguousMatch,SearchLimitExceeded)):return 'TARGET_UNQUALIFIED'
    if isinstance(exc,WaitTimeout):return 'DEADLINE_EXCEEDED'
    if isinstance(exc,AXError):return 'NATIVE_ERROR'
    if isinstance(exc,VerificationFailed):return 'POSTCONDITION_UNCONFIRMED'
    if isinstance(exc,UnsafeOperation):return 'SAFETY_REJECTED'
    if isinstance(exc,(OSError,sqlite3.Error)):return 'PERSISTENCE_OR_OS_ERROR'
    if isinstance(exc,(TypeError,ValueError)):return 'INVALID_REQUEST'
    return 'UNEXPECTED_ERROR'
