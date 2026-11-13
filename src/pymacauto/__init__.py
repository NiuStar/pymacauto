"""pymacauto: control macOS apps through public Accessibility APIs."""
from .core import Application, Element, Locator
from .query import QueryScope, window_scope
from .pages import PageSession
from .tables import read_table
from .fields import labelled_field
from .errors import (AXError, AmbiguousMatch, AttributeUnsupported, ElementNotFound,
                     MacAXError, PermissionDenied, PlatformError,
                     SearchLimitExceeded, UnsafeOperation, VerificationFailed, WaitTimeout)

__version__ = '0.3.0'
__all__ = ['labelled_field', 'QueryScope', 'window_scope', 'PageSession', 'read_table', 'Application', 'Element', 'Locator', 'AXError', 'AmbiguousMatch',
           'AttributeUnsupported', 'ElementNotFound', 'MacAXError',
           'PermissionDenied', 'PlatformError', 'SearchLimitExceeded',
           'UnsafeOperation', 'VerificationFailed', 'WaitTimeout']
