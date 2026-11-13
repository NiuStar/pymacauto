"""Public macOS Accessibility bindings, imported only when a backend is made.

No input-event injection, application activation or private APIs are used here.
Native AX errors remain failures; only kAXErrorNoValue maps to None in get().
"""
from __future__ import annotations

import math
import os
import sys

from .errors import AXError, AttributeUnsupported, MacAXError, PermissionDenied, PlatformError
from .validation import validate_pid


class _ReferenceKey:
    """Retain the CF reference and resolve CFHash collisions with CFEqual."""

    __slots__ = ("_ref", "_cf", "_hash")

    def __init__(self, ref, cf):
        self._ref, self._cf = ref, cf
        self._hash = int(cf.CFHash(ref))

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if not isinstance(other, _ReferenceKey):
            return NotImplemented
        return bool(self._cf.CFEqual(self._ref, other._ref))


class NativeBackend:
    """Synchronous AX backend with a per-application native RPC timeout.

    PyObjC's supported AXValueGetValue wrapper handles native struct layout;
    there is intentionally no ctypes/pointer or string-description fallback.
    """

    def __init__(self, rpc_timeout=1.0):
        if sys.platform != "darwin":
            raise PlatformError("pymacauto native automation requires macOS")
        if (isinstance(rpc_timeout, bool) or not isinstance(rpc_timeout, (int, float))
                or not math.isfinite(rpc_timeout) or rpc_timeout <= 0):
            raise ValueError("rpc_timeout must be a positive finite number of seconds")
        try:
            import ApplicationServices
            import CoreFoundation
            from AppKit import NSWorkspace
        except ImportError as exc:
            raise PlatformError(
                "pymacauto requires PyObjC on macOS; install with this interpreter: "
                "python -m pip install 'pyobjc-framework-ApplicationServices>=10' "
                "'pyobjc-framework-Cocoa>=10'"
            ) from exc
        self._ax, self._cf = ApplicationServices, CoreFoundation
        self._workspace = NSWorkspace.sharedWorkspace()
        self.rpc_timeout = float(rpc_timeout)

    def trusted(self, prompt=False):
        if not isinstance(prompt, bool):
            raise TypeError("prompt must be a bool")
        return bool(self._ax.AXIsProcessTrustedWithOptions({
            self._ax.kAXTrustedCheckOptionPrompt: prompt,
        }))

    def apps(self):
        return [
            {"pid": int(app.processIdentifier()),
             "name": str(app.localizedName() or ""),
             "bundle_id": (str(app.bundleIdentifier())
                           if app.bundleIdentifier() is not None else None)}
            for app in self._workspace.runningApplications()
        ]

    def root(self, pid):
        validate_pid(pid)
        try:
            os.kill(pid, 0)  # Probe existence only; never sends a signal.
        except OSError as exc:
            raise MacAXError(f'Cannot attach PID {pid}: {exc.strerror}') from exc
        if not self.trusted():
            raise PermissionDenied(
                "Grant Accessibility permission to this Python executable or its "
                "terminal in System Settings > Privacy & Security > Accessibility"
            )
        ref = self._ax.AXUIElementCreateApplication(pid)
        if ref is None:
            raise MacAXError(f"AXUIElementCreateApplication({pid}) returned no reference")
        self._check("AXUIElementSetMessagingTimeout", self._ax.AXUIElementSetMessagingTimeout(
            ref, self.rpc_timeout,
        ))
        return ref

    def _check(self, operation, code):
        if code == self._ax.kAXErrorSuccess:
            return
        if code == self._ax.kAXErrorAttributeUnsupported:
            raise AttributeUnsupported(f"{operation}: AX attribute unsupported ({code})")
        if code == self._ax.kAXErrorAPIDisabled:
            raise PermissionDenied(f"{operation}: Accessibility API disabled ({code}); check Accessibility permission")
        raise AXError(operation, int(code))

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not name:
            raise TypeError("AX attribute/action name must be a nonempty string")
        return name

    def get(self, ref, attribute):
        attribute = self._name(attribute)
        operation = f"AXUIElementCopyAttributeValue({attribute})"
        code, value = self._ax.AXUIElementCopyAttributeValue(ref, attribute, None)
        if code == self._ax.kAXErrorNoValue:
            return None
        self._check(operation, code)
        return self._normalize(value, operation)

    def get_many(self, ref, attributes, *, optional=()):
        """One public AX RPC, preserving per-field failures and ordering."""
        if not isinstance(attributes,(list,tuple)) or not attributes:
            raise ValueError('attributes must be a nonempty sequence')
        names=[self._name(name) for name in attributes]
        if len(set(names))!=len(names):raise ValueError('Duplicate attributes')
        optional=set(optional)
        if not optional<=set(names):raise ValueError('Optional attributes must be requested')
        operation='AXUIElementCopyMultipleAttributeValues'
        code,values=self._ax.AXUIElementCopyMultipleAttributeValues(ref,names,0,None)
        self._check(operation,code)
        if values is None or len(values)!=len(names):raise MacAXError('Batch AX result length mismatch')
        result={}
        for name,value in zip(names,values):
            try:
                result[name]=self._normalize(value,operation+'('+name+')')
            except AttributeUnsupported:
                if name not in optional:raise
                result[name]=None
            except AXError as exc:
                if exc.code!=self._ax.kAXErrorNoValue:raise
                result[name]=None
        return result

    def attributes(self, ref):
        code, names = self._ax.AXUIElementCopyAttributeNames(ref, None)
        self._check("AXUIElementCopyAttributeNames", code)
        return self._names(names, "AXUIElementCopyAttributeNames")

    def actions(self, ref):
        code, names = self._ax.AXUIElementCopyActionNames(ref, None)
        self._check("AXUIElementCopyActionNames", code)
        return self._names(names, "AXUIElementCopyActionNames")

    @staticmethod
    def _names(names, operation):
        if names is None:
            raise MacAXError(f"{operation}: success without an array")
        result = list(names)
        if not all(isinstance(name, str) for name in result):
            raise MacAXError(f"{operation}: expected string names")
        return result

    def is_settable(self, ref, attribute):
        attribute = self._name(attribute)
        code, writable = self._ax.AXUIElementIsAttributeSettable(ref, attribute, None)
        self._check(f'AXUIElementIsAttributeSettable({attribute})', code)
        return bool(writable)

    def set(self, ref, attribute, value):
        attribute = self._name(attribute)
        if type(value) not in (str, bool, int, float):
            raise TypeError("AX writes require a JSON scalar: str, bool, int or finite float")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("AX writes require a finite float")
        self._check(f"AXUIElementSetAttributeValue({attribute})",
                    self._ax.AXUIElementSetAttributeValue(ref, attribute, value))

    def perform(self, ref, action):
        action = self._name(action)
        self._check(f"AXUIElementPerformAction({action})",
                    self._ax.AXUIElementPerformAction(ref, action))

    def key(self, ref):
        return _ReferenceKey(ref, self._cf)

    def _normalize(self, value, operation):
        if value is None:
            return None
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, str):
            return str(value)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return float(value)
        if isinstance(value, self._ax.AXUIElementRef):
            return value
        if isinstance(value, self._ax.AXValueRef):
            return self._geometry(value, operation)
        if isinstance(value, (list, tuple)):
            return [self._normalize(item, operation) for item in value]
        type_id = self._cf.CFGetTypeID(value)
        if type_id == self._cf.CFArrayGetTypeID():
            return [self._normalize(item, operation) for item in value]
        if type_id == self._cf.CFBooleanGetTypeID():
            return bool(value)
        if type_id == self._cf.CFNumberGetTypeID():
            return float(value) if self._cf.CFNumberIsFloatType(value) else int(value)
        raise MacAXError(f"{operation}: unsupported native value type {type(value).__name__}")

    def _geometry(self, value, operation):
        ax = self._ax
        kind = ax.AXValueGetType(value)
        supported = (ax.kAXValueTypeCGPoint, ax.kAXValueTypeCGSize,
                     ax.kAXValueTypeCGRect, ax.kAXValueTypeCFRange,
                     ax.kAXValueTypeAXError)
        if kind not in supported:
            raise MacAXError(f"{operation}: unsupported AXValue type {kind}")
        ok, data = ax.AXValueGetValue(value, kind, None)
        if not ok:
            raise MacAXError(f"{operation}: AXValueGetValue failed for type {kind}")
        if kind == ax.kAXValueTypeCGPoint:
            return {"x": float(data[0]), "y": float(data[1])}
        if kind == ax.kAXValueTypeCGSize:
            return {"width": float(data[0]), "height": float(data[1])}
        if kind == ax.kAXValueTypeCGRect:
            return {"x": float(data[0][0]), "y": float(data[0][1]),
                    "width": float(data[1][0]), "height": float(data[1][1])}
        if kind == ax.kAXValueTypeCFRange:
            return {"location": int(data[0]), "length": int(data[1])}
        # An AXError wrapped in an AXValue is still an error, never a match.
        self._check(f"{operation}/AXValue", int(data))
        return int(data)
