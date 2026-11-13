"""Diagnostic graph tests; execute on the target Mac with the full suite."""
import unittest
from pymacauto import Application, AXError
from pymacauto.inspector import inspect_application
from test_core import MemoryAX


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryAX()
        self.backend.is_settable = lambda ref, name: name == 'AXValue'
        self.app = Application.connect(pid=42, backend=self.backend)

    def test_captures_paths_capabilities_without_reading_values_or_writing(self):
        self.backend.nodes['a']['AXValue'] = 'private account fixture'
        original = self.backend.get
        def get(ref, name):
            if name == 'AXValue':
                self.fail('Discovery must not read values')
            return original(ref, name)
        self.backend.get = get
        result = inspect_application(self.app)
        self.assertTrue(result['complete'])
        self.assertEqual(result['node_count'], 4)
        button = next(n for n in result['nodes'] if n['fields'].get('identifier') == 'apply')
        self.assertEqual(button['candidate_selector'], {'identifier': 'apply'})
        self.assertTrue(button['selector_unique_in_capture'])
        self.assertTrue(button['settable']['AXValue'])
        self.assertNotIn('private account fixture', __import__('json').dumps(result))
        self.assertEqual(self.backend.calls, [])

    def test_action_failure_is_preserved_as_partial_not_empty_success(self):
        original = self.backend.actions
        def actions(ref):
            if ref == 'a': raise AXError('actions', -25200)
            return original(ref)
        self.backend.actions = actions
        result = inspect_application(self.app)
        self.assertFalse(result['complete'])
        self.assertEqual(result['node_count'], 4)
        failed = next(n for n in result['nodes'] if n['fields'].get('identifier') == 'apply')
        self.assertEqual(failed['errors'][0]['code'], -25200)

    def test_relation_graph_deduplicates_nodes_and_preserves_edges(self):
        self.backend.nodes['app']['AXWindows'] = ['window']
        self.backend.nodes['a']['AXChildren'] = ['app']
        result = inspect_application(self.app)
        self.assertEqual(result['node_count'], 4)
        self.assertTrue(any(e['relation'] == 'AXWindows' for e in result['edges']))
        self.assertTrue(any(e['target'] == 0 and e['source'] != 0 for e in result['edges']))

    def test_limits_make_discovery_explicitly_incomplete(self):
        for limits in ({'max_nodes': 2}, {'max_depth': 1}):
            with self.subTest(limits=limits):
                result = inspect_application(self.app, **limits)
                self.assertFalse(result['complete'])
                self.assertTrue(result['limits_hit'])

    def test_secure_values_and_settable_not_exposed(self):
        self.backend.nodes['a']['AXSubrole'] = 'AXSecureTextField'
        self.backend.nodes['a']['AXValue'] = 'never-read'
        result = inspect_application(self.app)
        node = next(n for n in result['nodes'] if n['fields'].get('identifier') == 'apply')
        self.assertEqual(node['settable']['AXValue'], '<blocked-secure>')

    def test_help_and_combined_selector_handles_duplicate_ns_identifier(self):
        self.backend.nodes['a']['AXIdentifier'] = '_NS:42'
        self.backend.nodes['b']['AXIdentifier'] = '_NS:42'
        self.backend.nodes['a']['AXHelp'] = '点击切换至多股同列'
        self.assertEqual(self.app.child_window(role='AXButton', identifier='_NS:42', help='点击切换至多股同列').resolve().ref, 'a')

    def test_system_apple_menu_does_not_expand_recent_items(self):
        self.backend.nodes['b']['AXRole'] = 'AXMenuBarItem'
        self.backend.nodes['b']['AXTitle'] = 'Apple'
        self.backend.nodes['b']['AXChildren'] = ['private']
        self.backend.nodes['private'] = {'AXRole': 'AXMenuItem', 'AXTitle': 'private recent document'}
        result = inspect_application(self.app)
        self.assertEqual(result['node_count'], 4)
        self.assertNotIn('private recent document', __import__('json').dumps(result))

    def test_ambiguous_titles_do_not_generate_unique_selectors(self):
        del self.backend.nodes['a']['AXIdentifier']
        result = inspect_application(self.app)
        buttons = [n for n in result['nodes'] if n['fields'].get('role') == 'AXButton']
        self.assertTrue(all(not n['selector_unique_in_capture'] for n in buttons))
