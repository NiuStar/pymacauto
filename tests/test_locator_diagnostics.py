"""In-memory diagnostic contracts; these are not native macOS evidence."""
import copy
import json
import unittest

from pymacauto import Application
from pymacauto.locator_diagnostics import inspect_children, explain_locator, export_locator
from pymacauto.core import Locator
from pymacauto.errors import UnsafeOperation, SearchLimitExceeded, ElementNotFound, AXError
from test_core import MemoryAX


class DiagnosticAX(MemoryAX):
    def __init__(self):
        super().__init__()
        self.reads = []

    def get(self, ref, name):
        self.reads.append((ref, name))
        if name in ('AXValue', 'AXTitle', 'AXDescription', 'AXHelp'):
            raise AssertionError('Unexpected content read: ' + name)
        return super().get(ref, name)

    def set(self, *args):
        raise AssertionError('Diagnostics must not set attributes')

    def perform(self, *args):
        raise AssertionError('Diagnostics must not dispatch actions')

    def actions(self, *args):
        raise AssertionError('Diagnostics need no action enumeration')


class LocatorDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.backend = DiagnosticAX()
        self.app = Application.connect(pid=42, backend=self.backend)
        self.window = self.app.window()

    def test_children_are_safe_metadata_with_filtered_ordinals(self):
        self.backend.nodes['window']['AXChildren'] = ['a', 'label', 'b']
        self.backend.nodes['label'] = {'AXRole': 'AXStaticText', 'AXValue': 'private'}
        self.backend.nodes['b'].update(AXRole='AXTextField',
                                      AXSubrole='AXSecureTextField', AXValue='secret')
        before = copy.deepcopy(self.backend.nodes)
        result = inspect_children(self.window)
        self.assertTrue(result['complete'])
        self.assertFalse(result['authorizes_mutation'])
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['children'][2], {
            'ordinal': 2, 'index': 2, 'expected_count': 3,
            'role_index': 0, 'role_count': 1,
            'role': 'AXTextField', 'subrole': 'AXSecureTextField',
            'identifier': None, 'enabled': True})
        filtered = inspect_children(self.window, role='AXTextField')
        self.assertEqual(filtered['count'], 1)
        self.assertEqual(filtered['children'][0]['index'], 0)
        self.assertEqual(filtered['children'][0]['ordinal'], 2)
        self.assertEqual(filtered['children'][0]['expected_count'], 1)
        self.assertEqual(before, self.backend.nodes)
        self.assertEqual(self.backend.calls, [])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('AXValue', [name for _, name in self.backend.reads])

    def test_explain_preserves_scope_and_index_contract(self):
        self.backend.nodes['app']['AXChildren'].append('outside')
        self.backend.nodes['outside'] = {'AXRole': 'AXButton'}
        locator = self.window.child(role='AXButton', index=1, expected_count=2)
        result = explain_locator(locator)
        self.assertTrue(result['complete'])
        self.assertEqual(result['status'], 'resolved')
        self.assertFalse(result['authorizes_mutation'])
        self.assertEqual([level['match_count'] for level in result['levels']], [1, 2])
        self.assertEqual(result['levels'][1]['index'], 1)
        self.assertEqual(result['levels'][1]['selected_count'], 1)
        self.assertEqual(result['levels'][0]['relation'], 'descendant')
        self.assertEqual(result['levels'][1]['relation'], 'child')
        text = json.dumps(result)
        self.assertNotIn('AXButton', text)
        self.assertNotIn('AXWindow', text)
        self.assertNotIn('apply', text)

    def test_explain_distinguishes_resolution_failures(self):
        cases = [
            (self.window.child(role='AXButton'), 'ambiguous', 'AmbiguousMatch', 2),
            (self.window.child(identifier='absent'), 'missing', 'ElementNotFound', 0),
            (self.window.child(role='AXButton', index=2), 'index_out_of_range', 'ElementNotFound', 2),
            (self.window.child(role='AXButton', index=0, expected_count=3),
             'count_mismatch', 'LayoutChanged', 2),
            (self.window.child(role='AXButton', index=1, verify={'identifier': 'apply'}),
             'verify_mismatch', 'LayoutChanged', 2),
        ]
        for locator, status, failure, count in cases:
            with self.subTest(status=status):
                result = explain_locator(locator.child(role='AXGroup'))
                self.assertEqual(result['status'], status)
                self.assertFalse(result['complete'])
                self.assertEqual(result['levels'][1]['failure'], failure)
                self.assertEqual(result['levels'][1]['match_count'], count)
                self.assertEqual(result['levels'][1]['selected_count'], 0)
                self.assertEqual(result['levels'][2]['status'], 'blocked')

    def test_explain_budgets_never_publish_partial_unique(self):
        for limits in ({'max_nodes': 3}, {'max_depth': 1}):
            with self.subTest(limits=limits):
                app = Application.connect(pid=42, backend=self.backend, **limits)
                result = explain_locator(app.child_window(identifier='apply'))
                self.assertEqual(result['status'], 'budget_exceeded')
                self.assertFalse(result['complete'])
                self.assertIsNone(result['levels'][0]['match_count'])
                self.assertFalse(result['levels'][0]['search_complete'])
                self.assertEqual(result['levels'][0]['failure'], 'SearchLimitExceeded')

    def test_explain_uses_actual_prefix_resolution_contract(self):
        from unittest.mock import patch
        original = Locator.resolve
        lengths = []

        def resolve(prefix):
            lengths.append(len(prefix.chain))
            if len(prefix.chain) == 2:
                raise UnsafeOperation('private backend failure details')
            return original(prefix)

        with patch.object(Locator, 'resolve', resolve):
            result = explain_locator(self.window.child(identifier='apply'))
        self.assertIn(1, lengths)
        self.assertIn(2, lengths)
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'unsafe')
        self.assertNotIn('private', json.dumps(result))

    def test_captured_roots_refused_for_explanation(self):
        for root in ('window', lambda: 'window'):
            with self.assertRaises(UnsafeOperation):
                explain_locator(Locator(self.app, ({'role': 'AXButton'},), root))

    def test_value_selectors_rejected_before_any_backend_read(self):
        locators = [self.app.child_window(value='secret'),
                    self.app.child_window(value_re='secret'),
                    self.window.child(role='AXButton', index=0, verify={'value': 'secret'})]
        for locator in locators:
            with self.subTest(locator=locator.chain):
                self.backend.reads.clear()
                with self.assertRaises(UnsafeOperation):
                    explain_locator(locator)
                with self.assertRaises(UnsafeOperation):
                    inspect_children(locator)
                self.assertEqual(self.backend.reads, [])

    def test_export_serializable_path_preserves_all_fields_without_reads(self):
        locator = self.window.child(role='AXButton', index=0, expected_count=2,
                                    verify={'identifier': 'apply'})
        self.backend.reads.clear()
        result = export_locator(locator)
        self.assertEqual(result['status'], 'candidate')
        self.assertFalse(result['authorizes_mutation'])
        self.assertFalse(result['validated'])
        self.assertEqual(result['path'], [
            {'relation': 'descendant', 'selector': {'role': 'AXWindow'},
             'index': None, 'expected_count': None, 'verify': None},
            {'relation': 'child', 'selector': {'role': 'AXButton'},
             'index': 0, 'expected_count': 2, 'verify': {'identifier': 'apply'}}])
        self.assertEqual(self.backend.reads, [])
        path = json.loads(json.dumps(result))['path']
        self.assertEqual(self.app.locator_path(path).resolve().ref, 'a')
        result['path'][1]['verify']['identifier'] = 'changed'
        self.assertEqual(locator.resolve().ref, 'a')

    def test_export_refuses_captured_roots_and_value_selectors(self):
        for locator in (self.app.child_window(value='private'),
                        self.app.child_window(value_re='private'),
                        self.window.child(role='AXButton', verify={'value_re': 'private'}),
                        Locator(self.app, ({'role': 'AXButton'},), 'window'),
                        Locator(self.app, ({'role': 'AXButton'},), lambda: 'window')):
            with self.assertRaises(UnsafeOperation):
                export_locator(locator)
        self.assertEqual(self.backend.reads, [])

    def test_children_accept_element_and_only_direct_children(self):
        self.backend.nodes['window']['AXChildren'] = ['group', 'b', 'b']
        self.backend.nodes['group'] = {'AXRole': 'AXGroup', 'AXChildren': ['a']}
        result = inspect_children(self.window.resolve())
        self.assertEqual(result['total_count'], 2)
        self.assertEqual([row['role'] for row in result['children']], ['AXGroup', 'AXButton'])
        self.assertEqual(result['children'][1]['role_index'], 0)
        self.assertEqual(result['children'][1]['role_count'], 1)
        self.assertEqual(inspect_children(self.window, identifier='apply')['count'], 0)
        with self.assertRaises(ElementNotFound):
            inspect_children(self.window.child(identifier='absent'))
        with self.assertRaises(UnsafeOperation):
            inspect_children(self.window, value_re='private')

    def test_children_and_direct_explanation_enforce_node_budget(self):
        app = Application.connect(pid=42, backend=self.backend, max_nodes=1)
        from pymacauto.core import Element
        with self.assertRaises(SearchLimitExceeded):
            inspect_children(Element(app, 'window'))
        result = explain_locator(app.child(role='AXWindow').child(role='AXButton', index=0))
        self.assertEqual(result['status'], 'budget_exceeded')
        self.assertEqual(result['levels'][0]['selected_count'], 1)
        self.assertIsNone(result['levels'][1]['match_count'])
        self.assertEqual(result['levels'][1]['selected_count'], 0)

    def test_window_relation_uses_windows_not_recursive_children(self):
        self.backend.nodes['app']['AXWindows'] = ['detached', 'detached']
        self.backend.nodes['detached'] = {'AXRole': 'AXWindow', 'AXChildren': ['a']}
        locator = self.app.locator_path([
            {'relation': 'window', 'selector': {'role': 'AXWindow'},
             'index': 0, 'expected_count': 1},
            {'relation': 'child', 'selector': {'role': 'AXButton'},
             'index': 0, 'expected_count': 1, 'verify': {'identifier': 'apply'}}])
        result = explain_locator(locator)
        self.assertTrue(result['complete'])
        self.assertEqual([row['candidate_count'] for row in result['levels']], [1, 1])
        nested = self.app.locator_path([
            {'relation': 'child', 'selector': {'role': 'AXWindow'}},
            {'relation': 'window', 'selector': {'role': 'AXWindow'}}])
        result = explain_locator(nested)
        self.assertFalse(result['complete'])
        self.assertEqual(result['levels'][1]['failure'], 'ValueError')
        self.assertIsNone(result['levels'][1]['match_count'])

    def test_backend_errors_not_collapsed_to_missing_or_selector_content(self):
        def fail(ref, name):
            raise AXError('private-operation', -25204)
        self.backend.get = fail
        result = explain_locator(self.window)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['levels'][0]['failure'], 'AXError')
        self.assertFalse(result['levels'][0]['search_complete'])
        self.assertIsNone(result['levels'][0]['match_count'])
        self.assertNotIn('private', json.dumps(result))
        with self.assertRaises(AXError):
            inspect_children(self.window)

    def test_conflicting_enumeration_and_resolve_cannot_become_success(self):
        from unittest.mock import patch
        from pymacauto.core import Element
        original = Locator.resolve

        def replacement(prefix):
            if len(prefix.chain) == 2:
                return Element(self.app, 'b')
            return original(prefix)

        with patch.object(Locator, 'resolve', replacement):
            result = explain_locator(self.window.child(identifier='apply'))
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'changed')
        self.assertEqual(result['levels'][1]['selected_count'], 0)
        with patch.object(Locator, 'resolve', replacement):
            result = explain_locator(self.window.child(role='AXButton'))
        self.assertEqual(result['status'], 'changed')
        self.assertEqual(result['levels'][1]['match_count'], 2)
        self.assertEqual(result['levels'][1]['selected_count'], 0)

    def test_explanation_never_serializes_content_selector_or_exception(self):
        backend = MemoryAX()
        backend.nodes['a'].update(AXSubrole='AXSecureTextField', AXValue='hidden-value')
        app = Application.connect(pid=42, backend=backend)
        result = explain_locator(app.window(title='private-window-name'))
        self.assertEqual(result['status'], 'missing')
        text = json.dumps(result)
        for private in ('private-window-name', 'hidden-value', 'title', 'selector'):
            self.assertNotIn(private, text)
        locator = app.window(title='Demo').child(identifier='apply')
        self.assertTrue(explain_locator(locator)['complete'])
        self.assertEqual(backend.calls, [])

    def test_role_filtered_indices_use_filtered_counts_not_sibling_positions(self):
        self.backend.nodes['window']['AXChildren'] = ['a', 'label', 'b']
        self.backend.nodes['label'] = {'AXRole': 'AXStaticText'}
        result = inspect_children(self.window, role='AXButton')
        self.assertEqual([row['ordinal'] for row in result['children']], [0, 2])
        self.assertEqual([row['index'] for row in result['children']], [0, 1])
        self.assertEqual([row['expected_count'] for row in result['children']], [2, 2])
        self.assertEqual([row['role_index'] for row in result['children']], [0, 1])
        self.assertEqual([row['role_count'] for row in result['children']], [2, 2])

    def test_identity_keys_deduplicate_aliases_before_counting(self):
        self.backend.nodes['alias'] = self.backend.nodes['a']
        self.backend.nodes['window']['AXChildren'] = ['a', 'alias', 'b']
        self.backend.key = lambda ref: 'a' if ref == 'alias' else ref
        self.assertEqual(inspect_children(self.window)['count'], 2)
        result = explain_locator(self.window.child(role='AXButton', index=1, expected_count=2))
        self.assertTrue(result['complete'])
        self.assertEqual(result['levels'][1]['match_count'], 2)

    def test_export_rejects_non_serializable_regex_and_empty_path(self):
        import re
        for locator in (self.app.child_window(identifier_re=re.compile('apply')),
                        Locator(self.app, ())):
            with self.assertRaises(ValueError):
                export_locator(locator)
        self.assertEqual(self.backend.reads, [])
