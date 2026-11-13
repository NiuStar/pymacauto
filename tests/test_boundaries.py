"""Review regressions; native bridge tests below never send a real OS signal."""
import unittest
from unittest.mock import patch
from pymacauto import Application, ElementNotFound, VerificationFailed, WaitTimeout
from pymacauto.native import NativeBackend
from test_core import MemoryAX
import test_cli


class ValueBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryAX()
        self.app = Application.connect(pid=42, backend=self.backend)

    def test_boolean_number_selectors_are_distinct(self):
        for actual, requested in ((True, 1), (False, 0), (1, True), (0, False), (True, 1.0)):
            with self.subTest(actual=actual, requested=requested):
                self.backend.nodes['a']['AXValue'] = actual
                with self.assertRaises(ElementNotFound):
                    self.app.child_window(identifier='apply', value=requested).resolve()

    def test_boolean_number_noop_write_is_not_verified(self):
        self.backend.set = lambda *args: None
        for actual, requested in ((True, 1), (False, 0), (1, True), (0, False)):
            with self.subTest(actual=actual, requested=requested):
                self.backend.nodes['a']['AXValue'] = actual
                with self.assertRaises(VerificationFailed):
                    self.app.child_window(identifier='apply').set_value(requested, verify_timeout=0)

    def test_wait_boolean_is_not_numeric_postcondition(self):
        self.backend.nodes['a']['AXValue'] = True
        with self.assertRaises(WaitTimeout):
            self.app.child_window(identifier='apply').wait(timeout=0, value=1)

    def test_same_boolean_and_equivalent_numbers_remain_valid(self):
        for actual, expected in ((True, True), (False, False), (1, 1.0), (0.5, 0.5)):
            self.backend.nodes['a']['AXValue'] = actual
            self.assertEqual(self.app.child_window(identifier='apply', value=expected).resolve().ref, 'a')
            self.backend.set = lambda *args: None
            self.assertTrue(self.app.child_window(identifier='apply').set_value(expected, verify_timeout=0)['verified'])


class PIDBoundaryTests(unittest.TestCase):
    def test_sdk_rejects_out_of_range_pid_before_backend_access(self):
        backend = MemoryAX()
        backend.trusted = lambda *args: self.fail('Backend must not be accessed for invalid PID')
        for pid in (2147483648, 10 ** 400, 0, -1, True):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                Application.connect(pid=pid, backend=backend)

    def test_native_root_rejects_out_of_range_before_os_probe(self):
        native = object.__new__(NativeBackend)
        with patch('pymacauto.native.os.kill') as probe:
            for pid in (2147483648, 10 ** 400):
                with self.subTest(pid=pid), self.assertRaises(ValueError):
                    native.root(pid)
            probe.assert_not_called()

    def test_cli_out_of_range_pid_is_structured_json_failure(self):
        invoke = test_cli.CLITests().invoke
        for pid in ('2147483648', '1' + '0' * 400):
            with self.subTest(pid=pid):
                code, report = invoke(['find', '--pid', pid, '--identifier', 'apply'])
                self.assertEqual(code, 2)
                self.assertEqual(report['error'], 'ValueError')

    def test_enormous_timeout_is_validation_error_not_overflow(self):
        app = Application.connect(pid=42, backend=MemoryAX())
        with self.assertRaises(ValueError):
            app.child_window(identifier='apply').wait(timeout=10 ** 400)
