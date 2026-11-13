#!/usr/bin/env python3
"""Attach-only fixture smoke; never launches, activates or quits applications.

Run ``python tests/native/smoke.py --backend-checks`` on any platform for
isolated backend contract tests (PyObjC is simulated, not native acceptance).
On macOS run without that flag against an already-running org.pymacauto.fixture.
The fixture result is an NSTextField label exposing AXValue, not AXTitle.
"""
from __future__ import annotations

import argparse
import math
import sys
import types
import unittest
from unittest.mock import patch


def backend_checks():
    from pymacauto.errors import AXError, AttributeUnsupported, PermissionDenied, PlatformError
    from pymacauto.native import NativeBackend

    class Ref:
        def __init__(self, identity):
            self.identity = identity

    class Value:
        def __init__(self, kind, value):
            self.kind, self.value = kind, value

    class App:
        def processIdentifier(self): return 42
        def localizedName(self): return "Fixture"
        def bundleIdentifier(self): return "org.pymacauto.fixture"

    class Workspace:
        @classmethod
        def sharedWorkspace(cls): return cls()
        def runningApplications(self): return [App()]

    class BackendContract(unittest.TestCase):
        def setUp(self):
            self.code, self.value = 0, "hello"
            self.timeout_code = 0
            self.timeouts, self.writes, self.performed = [], [], []
            self.trust = True
            self.ax = types.ModuleType("ApplicationServices")
            self.ax.__dict__.update(
                kAXErrorSuccess=0, kAXErrorNoValue=-25212,
                kAXErrorAttributeUnsupported=-25205, kAXErrorAPIDisabled=-25211,
                kAXValueTypeCGPoint=1, kAXValueTypeCGSize=2,
                kAXValueTypeCGRect=3, kAXValueTypeCFRange=4,
                kAXValueTypeAXError=5, kAXTrustedCheckOptionPrompt="prompt",
                AXUIElementRef=Ref, AXValueRef=Value,
                AXIsProcessTrustedWithOptions=lambda options: self.trust,
                AXUIElementCreateApplication=lambda pid: Ref(pid),
                AXUIElementSetMessagingTimeout=self.timeout,
                AXUIElementCopyAttributeValue=lambda *a: (self.code, self.value),
                AXUIElementCopyAttributeNames=lambda *a: (self.code, ["AXValue"]),
                AXUIElementCopyActionNames=lambda *a: (self.code, ["AXPress"]),
                AXUIElementSetAttributeValue=self.set_value,
                AXUIElementPerformAction=self.perform,
                AXValueGetType=lambda val: val.kind,
                AXValueGetValue=lambda val, kind, out: (True, val.value),
            )
            self.cf = types.ModuleType("CoreFoundation")
            self.cf.__dict__.update(
                CFHash=lambda val: 7,  # deliberate collisions
                CFEqual=lambda left, right: left.identity == right.identity,
                CFGetTypeID=lambda val: 3 if isinstance(val, list) else 99,
                CFArrayGetTypeID=lambda: 3,
            )
            self.appkit = types.ModuleType("AppKit")
            self.appkit.NSWorkspace = Workspace
            self.modules = patch.dict(sys.modules, {
                "ApplicationServices": self.ax, "CoreFoundation": self.cf,
                "AppKit": self.appkit,
            })
            self.modules.start()
            self.platform = patch.object(sys, "platform", "darwin")
            self.platform.start()
            def probe(pid, signal):
                if pid != 42:
                    raise ProcessLookupError(3, 'No such process')
            self.pid_probe = patch('pymacauto.native.os.kill', side_effect=probe)
            self.pid_probe.start()
            self.addCleanup(self.pid_probe.stop)
            self.addCleanup(self.modules.stop)
            self.addCleanup(self.platform.stop)
            self.backend = NativeBackend(rpc_timeout=0.25)

        def timeout(self, ref, seconds):
            self.timeouts.append((ref, seconds))
            return self.timeout_code

        def set_value(self, *args):
            self.writes.append(args)
            return self.code

        def perform(self, *args):
            self.performed.append(args)
            return self.code

        def test_root_validates_pid_and_applies_timeout(self):
            root = self.backend.root(42)
            self.assertEqual(root.identity, 42)
            self.assertEqual(self.timeouts, [(root, 0.25)])
            from pymacauto.errors import MacAXError
            for pid in (0, -1, True, "42", 999):
                with self.subTest(pid=pid), self.assertRaises((ValueError, TypeError, MacAXError)):
                    self.backend.root(pid)
            self.assertEqual(len(self.timeouts), 1)

        def test_timeout_error_is_not_ignored(self):
            self.timeout_code = -25204
            with self.assertRaises(AXError) as caught:
                self.backend.root(42)
            self.assertEqual(caught.exception.code, -25204)

        def test_permission_and_missing_pyobjc_are_explicit(self):
            self.trust = False
            self.assertFalse(self.backend.trusted())
            with self.assertRaises(PermissionDenied): self.backend.root(42)
            self.code = -25211
            with self.assertRaises(PermissionDenied): self.backend.get(Ref(42), "AXValue")
            with patch.dict(sys.modules, {"ApplicationServices": None}):
                with self.assertRaises(PlatformError): NativeBackend()
            with patch.object(sys, "platform", "linux"):
                with self.assertRaises(PlatformError): NativeBackend()

        def test_no_value_unsupported_and_failure_are_distinct(self):
            self.code = -25212
            self.assertIsNone(self.backend.get(Ref(42), "AXValue"))
            self.code = -25205
            with self.assertRaises(AttributeUnsupported): self.backend.get(Ref(42), "AXValue")
            for code in (-25202, -25204):
                self.code = code
                with self.assertRaises(AXError) as caught:
                    self.backend.get(Ref(42), "AXValue")
                self.assertEqual(caught.exception.code, code)

        def test_enumeration_errors_are_not_empty_lists(self):
            self.assertEqual(self.backend.attributes(Ref(42)), ["AXValue"])
            self.assertEqual(self.backend.actions(Ref(42)), ["AXPress"])
            self.code = -25204
            for method in (self.backend.attributes, self.backend.actions):
                with self.assertRaises(AXError): method(Ref(42))

        def test_reference_key_uses_equality_not_hash_alone(self):
            key = self.backend.key
            self.assertEqual(key(Ref(42)), key(Ref(42)))
            self.assertNotEqual(key(Ref(42)), key(Ref(43)))
            self.assertEqual(len({key(Ref(42)), key(Ref(43)), key(Ref(42))}), 2)

        def test_scalar_array_and_geometry_conversion(self):
            ref = Ref(42)
            cases = [
                ("text", "text"), (True, True), (2, 2), (1.5, 1.5),
                ([ref, "text", True], [ref, "text", True]),
                (Value(1, (2, 3)), {"x": 2.0, "y": 3.0}),
                (Value(2, (4, 5)), {"width": 4.0, "height": 5.0}),
                (Value(3, ((2, 3), (4, 5))), {"x": 2.0, "y": 3.0, "width": 4.0, "height": 5.0}),
                (Value(4, (2, 3)), {"location": 2, "length": 3}),
            ]
            for value, expected in cases:
                self.value = value
                self.assertEqual(self.backend.get(ref, "AXValue"), expected)
            self.value = Value(5, -25204)
            with self.assertRaises(AXError): self.backend.get(ref, "AXValue")

        def test_native_booleans_and_numbers_are_python_primitives(self):
            class Number:
                def __init__(self, value, kind): self.value, self.kind = value, kind
                def __bool__(self): return bool(self.value)
                def __int__(self): return int(self.value)
                def __float__(self): return float(self.value)
            self.cf.CFGetTypeID = lambda val: val.kind if isinstance(val, Number) else 99
            self.cf.CFBooleanGetTypeID = lambda: 10
            self.cf.CFNumberGetTypeID = lambda: 11
            self.cf.CFNumberIsFloatType = lambda val: isinstance(val.value, float)
            for native, expected in [(Number(True, 10), True), (Number(3, 11), 3),
                                     (Number(2.5, 11), 2.5)]:
                self.value = native
                actual = self.backend.get(Ref(42), "AXValue")
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))

        def test_set_accepts_only_finite_json_scalars(self):
            for val in ("hello", True, 1, 1.5):
                self.backend.set(Ref(42), "AXValue", val)
            self.assertEqual(len(self.writes), 4)
            for val in (None, [], {}, math.nan, math.inf, -math.inf):
                with self.subTest(value=val), self.assertRaises((TypeError, ValueError)):
                    self.backend.set(Ref(42), "AXValue", val)
            self.assertEqual(len(self.writes), 4)
            self.code = -25204
            with self.assertRaises(AXError): self.backend.set(Ref(42), "AXValue", "fail")
            with self.assertRaises(AXError): self.backend.perform(Ref(42), "AXPress")

        def test_apps_contract(self):
            self.assertEqual(self.backend.apps(), [{
                "pid": 42, "name": "Fixture", "bundle_id": "org.pymacauto.fixture",
            }])

    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BackendContract)
    ).wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="PID of the already-running fixture")
    parser.add_argument("--backend-checks", action="store_true")
    args = parser.parse_args()
    if args.backend_checks:
        return 0 if backend_checks() else 1

    from pymacauto import Application
    from pymacauto.native import NativeBackend
    from AppKit import NSWorkspace

    backend = NativeBackend()
    if not backend.trusted():
        parser.error("Accessibility permission required for this Python/terminal; no prompt was requested")
    workspace = NSWorkspace.sharedWorkspace()
    front = workspace.frontmostApplication()
    front_pid = None if front is None else int(front.processIdentifier())
    app = Application.connect(pid=args.pid) if args.pid else Application.connect(bundle_id="org.pymacauto.fixture")
    # Check the target identity before any mutation, including explicit --pid.
    fixture_pids = {entry["pid"] for entry in backend.apps()
                    if entry["bundle_id"] == "org.pymacauto.fixture"}
    if args.pid is not None and args.pid not in fixture_pids:
        parser.error("--pid must identify org.pymacauto.fixture")
    app.child_window(identifier="pymacauto.input").set_edit_text("hello AX")
    app.child_window(identifier="pymacauto.apply").click()
    app.child_window(identifier="pymacauto.result").wait(value="applied:hello AX", timeout=3)
    after = workspace.frontmostApplication()
    after_pid = None if after is None else int(after.processIdentifier())
    if after_pid != front_pid:
        raise AssertionError(f"frontmost application changed: {front_pid} -> {after_pid}; concurrent user activity may also cause this")
    print("PASS: AXValue set + AXPress + result AXValue readback; frontmost PID unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
