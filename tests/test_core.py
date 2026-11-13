import unittest
from pymacauto import Application, AmbiguousMatch, ElementNotFound, SearchLimitExceeded

class MemoryAX:
    """Deterministic in-memory AX graph, NOT native integration evidence."""
    def __init__(self):
        self.nodes = {
            'app': {'AXRole': 'AXApplication', 'AXChildren': ['window']},
            'window': {'AXRole': 'AXWindow', 'AXTitle': 'Demo', 'AXChildren': ['a', 'b']},
            'a': {'AXRole': 'AXButton', 'AXTitle': 'Apply', 'AXIdentifier': 'apply', 'AXEnabled': True},
            'b': {'AXRole': 'AXButton', 'AXTitle': 'Apply', 'AXEnabled': True},
        }
        self.calls = []
    def trusted(self, prompt=False): return True
    def apps(self): return [{'pid': 42, 'name': 'Demo', 'bundle_id': 'org.pymacauto.demo'}]
    def root(self, pid): return 'app'
    def key(self, ref): return ref
    def get(self, ref, name): return self.nodes[ref].get(name)
    def actions(self, ref): return ['AXPress']
    def attributes(self, ref): return list(self.nodes[ref])
    def perform(self, ref, action): self.calls.append((ref, action))
    def set(self, ref, name, value): self.nodes[ref][name] = value

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryAX()
        self.app = Application.connect(pid=42, backend=self.backend)
    def test_ambiguous_selector_does_not_click(self):
        with self.assertRaises(AmbiguousMatch):
            self.app.child_window(title='Apply').click()
        self.assertEqual(self.backend.calls, [])

    def test_explicit_pid_can_attach_unregistered_ax_process(self):
        self.backend.apps = lambda: []
        app = Application.connect(pid=42, backend=self.backend)
        self.assertEqual(app.pid, 42)
        self.assertEqual(app.child_window(identifier='apply').resolve().ref, 'a')

    def test_lazy_locator_re_resolves_after_replacement(self):
        locator = self.app.child_window(identifier='apply')
        self.backend.nodes['window']['AXChildren'] = ['replacement']
        self.backend.nodes['replacement'] = dict(self.backend.nodes['a'])
        locator.click()
        self.assertEqual(self.backend.calls, [('replacement', 'AXPress')])

    def test_missing_is_distinct_from_ambiguous(self):
        self.assertFalse(self.app.child_window(title='missing').exists())
        with self.assertRaises(AmbiguousMatch):
            self.app.child_window(title='Apply').exists()

    def test_regex_and_scoped_locator(self):
        element = self.app.window(title='Demo').child_window(identifier_re='^app.*$').resolve()
        self.assertEqual(element.ref, 'a')

    def test_tree_budget_refuses_partial_unique_match(self):
        limited = Application.connect(pid=42, backend=self.backend, max_nodes=3)
        with self.assertRaises(SearchLimitExceeded):
            limited.child_window(identifier='apply').click()
        self.assertEqual(self.backend.calls, [])

    def test_depth_limit_refuses_partial_tree(self):
        limited = Application.connect(pid=42, backend=self.backend, max_depth=1)
        with self.assertRaises(SearchLimitExceeded):
            limited.dump_tree()

    def test_cycles_are_deduplicated(self):
        self.backend.nodes['a']['AXChildren'] = ['app']
        self.assertEqual(len(self.app.dump_tree()), 4)

    def test_set_value_reads_back(self):
        result = self.app.child_window(identifier='apply').set_value('中文 AX')
        self.assertTrue(result['verified'])
        self.assertEqual(self.backend.nodes['a']['AXValue'], '中文 AX')

    def test_action_dispatch_is_not_claimed_as_verified(self):
        result = self.app.child_window(identifier='apply').click()
        self.assertFalse(result['verified'])
        self.assertEqual(result['effect'], 'unverifiable')

    def test_disabled_and_secure_fields_refuse_mutation(self):
        from pymacauto import UnsafeOperation
        self.backend.nodes['a']['AXEnabled'] = False
        with self.assertRaises(UnsafeOperation):
            self.app.child_window(identifier='apply').click()
        self.backend.nodes['a']['AXEnabled'] = True
        self.backend.nodes['a']['AXSubrole'] = 'AXSecureTextField'
        self.backend.nodes['a']['AXValue'] = 'secret-fixture'
        self.assertEqual(self.app.child_window(identifier='apply').info()['value'], '<redacted>')
        with self.assertRaises(UnsafeOperation):
            self.app.child_window(identifier='apply').set_edit_text('x')
        with self.assertRaises(UnsafeOperation):
            self.app.child_window(value='secret-fixture').resolve()

    def test_permission_denial_is_explicit(self):
        from pymacauto import PermissionDenied
        self.backend.trusted = lambda prompt=False: False
        with self.assertRaises(PermissionDenied):
            Application.connect(pid=42, backend=self.backend)

    def test_ax_error_is_not_not_found(self):
        from pymacauto import AXError
        def broken(ref, name): raise AXError('read', -25204)
        self.backend.get = broken
        with self.assertRaises(AXError):
            self.app.child_window(title='missing').exists()

    def test_read_only_attribute_and_unsupported_action(self):
        from pymacauto import UnsafeOperation
        self.backend.actions = lambda ref: []
        with self.assertRaises(UnsafeOperation):
            self.app.child_window(identifier='apply').click()

    def test_set_readback_mismatch_is_not_success(self):
        from pymacauto import VerificationFailed
        self.backend.set = lambda *args: None
        with self.assertRaises(VerificationFailed):
            self.app.child_window(identifier='apply').set_value('nope', verify_timeout=0)

    def test_wait_for_exists_value_and_gone(self):
        from pymacauto import WaitTimeout
        self.assertEqual(self.app.child_window(identifier='apply').wait(timeout=0).ref, 'a')
        self.assertIsNone(self.app.child_window(title='absent').wait(timeout=0, state='gone'))
        with self.assertRaises(WaitTimeout):
            self.app.child_window(identifier='apply').wait(timeout=0, value='not-yet')

    def test_info_is_json_safe_for_nested_ax_references(self):
        import json
        self.backend.nodes['a']['AXValue'] = ['ok', object(), {'ref': object()}]
        info = self.app.child_window(identifier='apply').info()
        json.dumps(info, allow_nan=False)
        self.assertEqual(info['value'], ['ok', '<AX reference>', {'ref': '<AX reference>'}])

    def test_selector_and_limits_validation(self):
        for criteria in ({'foo': 'x'}, {'enabled': 'true'}, {'role': 5}, {'title_re': '['}):
            with self.assertRaises((ValueError, __import__('re').error)):
                self.app.child_window(**criteria)
        for limit in (0, -1, True, float('nan')):
            with self.assertRaises(ValueError):
                Application.connect(pid=42, backend=self.backend, max_nodes=limit)
        with self.assertRaises(ValueError):
            Application.connect(pid=42, name='Demo', backend=self.backend)

if __name__ == '__main__': unittest.main()
