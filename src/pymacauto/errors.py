"""Explicit failure states; never turn an AX failure into an empty search."""
class MacAXError(Exception):
    pass

class PlatformError(MacAXError):
    pass

class PermissionDenied(MacAXError):
    pass

class AttributeUnsupported(MacAXError):
    pass

class AXError(MacAXError):
    def __init__(self, operation, code):
        self.operation, self.code = operation, int(code)
        super().__init__(f"{operation}: AX error {code}")

class ElementNotFound(MacAXError):
    pass

class AmbiguousMatch(MacAXError):
    pass

class SearchLimitExceeded(MacAXError):
    pass

class WaitTimeout(MacAXError):
    pass

class UnsafeOperation(MacAXError):
    pass

class StopRequested(UnsafeOperation):
    pass

class LayoutChanged(UnsafeOperation):
    pass

class VerificationFailed(MacAXError):
    pass
