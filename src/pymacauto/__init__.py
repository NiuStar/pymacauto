"""pymacauto: control macOS apps through public Accessibility APIs."""
from .core import Application, Element, Locator
from .query import QueryScope, window_scope
from .pages import PageSession
from .tables import read_table
from .fields import labelled_field
from .controls import Control
from .operations import OperationSession,Condition
from .events import AXEvents,wait_condition
from .profiles import AppProfile
from .collection import collect_pages
from .metrics import AXMetrics
from .errors import (AXError, AmbiguousMatch, AttributeUnsupported, ElementNotFound,
                     MacAXError, PermissionDenied, PlatformError,
                     SearchLimitExceeded, UnsafeOperation, VerificationFailed, WaitTimeout)

__version__ = '0.5.0'
__all__ = ['AXMetrics','AppProfile','collect_pages','Control','OperationSession','Condition','AXEvents','wait_condition','labelled_field', 'QueryScope', 'window_scope', 'PageSession', 'read_table', 'Application', 'Element', 'Locator', 'AXError', 'AmbiguousMatch',
           'AttributeUnsupported', 'ElementNotFound', 'MacAXError',
           'PermissionDenied', 'PlatformError', 'SearchLimitExceeded',
           'UnsafeOperation', 'VerificationFailed', 'WaitTimeout']
