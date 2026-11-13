"""Supplemental in-memory qualification tests, not native Mac acceptance."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from pymacauto import Application, UnsafeOperation
from pymacauto.journal import canonical
from pymacauto.profiles import AppProfile
from test_core import MemoryAX


class ProfileCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryAX()
        self.backend.nodes['app']['AXWindows'] = ['window']
        self.backend.nodes['window']['AXIdentifier'] = 'win'
        self.metadata = {'bundle_id': 'org.pymacauto.demo', 'version': '1', 'build': '1'}
        self.backend.app_metadata = lambda pid: dict(self.metadata)
        self.reads = []
        original_get = self.backend.get
        def get(ref, name):
            self.reads.append((ref, name))
            return original_get(ref, name)
        self.backend.get = get
        self.capability_calls = []
        def actions(ref):
            self.capability_calls.append(('actions', ref))
            return ['AXPress', 'private-unrequested-action']
        def is_settable(ref, name):
            self.capability_calls.append(('settable', ref, name))
            return name == 'AXValue'
        self.backend.actions = actions
        self.backend.is_settable = is_settable
        self.app = Application.connect(pid=42, backend=self.backend)
        self.path = [{'relation': 'child', 'selector': {'identifier': 'apply'}}]

    def config(self, control=None):
        if control is None:
            control = {'path': copy.deepcopy(self.path), 'actions': ['AXPress'], 'settable': ['AXValue']}
        return {**self.metadata, 'window': {'identifier': 'win'}, 'controls': {'apply': control}}

    def test_extended_control_is_structurally_and_capability_qualified(self):
        report = AppProfile(self.config()).require(self.app)
        control = report['controls']['apply']
        self.assertEqual(control['status'], 'UNIQUE')
        self.assertEqual(control['role'], 'AXButton')
        self.assertTrue(control['structure_match'])
        self.assertTrue(control['ability_qualified'])
        self.assertEqual(control['actions'], {'AXPress': True})
        self.assertEqual(control['settable'], {'AXValue': True})
        self.assertTrue(report['structure_match'])
        self.assertTrue(report['ability_qualified'])
        self.assertFalse(control['action_tested'])
        self.assertFalse(report['action_tested'])
        self.assertEqual(self.backend.calls, [])
        self.assertFalse(any(name == 'AXValue' for _, name in self.reads))
        self.assertNotIn('private-unrequested-action', json.dumps(report))

    def test_flat_selector_remains_qualified_without_capability_probes(self):
        config = self.config({'identifier': 'apply'})
        report = AppProfile(config).require(self.app)
        self.assertEqual(report['controls']['apply']['status'], 'UNIQUE')
        self.assertTrue(report['controls']['apply']['ability_qualified'])
        self.assertEqual(self.capability_calls, [])
        self.assertEqual(report['profile_sha256'], hashlib.sha256(canonical(config)).hexdigest())

    def test_missing_action_preserves_unique_structure_but_refuses_require(self):
        profile = AppProfile(self.config())
        before = profile.require(self.app)
        self.backend.actions = lambda ref: []
        after = profile.inspect(self.app)
        self.assertEqual(after['controls']['apply']['status'], 'UNIQUE')
        self.assertTrue(after['structure_match'])
        self.assertFalse(after['qualified'])
        self.assertFalse(after['ability_qualified'])
        self.assertEqual(after['controls']['apply']['actions'], {'AXPress': False})
        self.assertEqual(before['structure_sha256'], after['structure_sha256'])
        self.assertEqual(profile.diff(before, after)['changed_controls'], ['apply'])
        with self.assertRaises(UnsafeOperation):
            profile.require(self.app)

    def test_missing_settable_is_not_qualified(self):
        self.backend.is_settable = lambda ref, name: False
        report = AppProfile(self.config()).inspect(self.app)
        self.assertFalse(report['qualified'])
        self.assertEqual(report['controls']['apply']['settable'], {'AXValue': False})
        self.assertEqual(report['controls']['apply']['status'], 'UNIQUE')

    def test_capability_errors_fail_closed_without_exception_text(self):
        def broken(*args):
            raise RuntimeError('private-input-do-not-report')
        self.backend.actions = broken
        self.backend.is_settable = broken
        report = AppProfile(self.config()).inspect(self.app)
        self.assertFalse(report['qualified'])
        self.assertTrue(report['structure_match'])
        self.assertEqual(report['controls']['apply']['status'], 'UNIQUE')
        self.assertIn('RuntimeError', json.dumps(report))
        self.assertNotIn('private-input-do-not-report', json.dumps(report))

    def test_non_boolean_settable_result_fails_closed(self):
        self.backend.is_settable = lambda ref, name: 'yes'
        self.assertFalse(AppProfile(self.config()).inspect(self.app)['qualified'])

    def test_path_only_and_empty_requirements_do_not_probe_capabilities(self):
        for control in ({'path': self.path}, {'path': self.path, 'actions': [], 'settable': []}):
            with self.subTest(control=control):
                self.assertTrue(AppProfile(self.config(control)).require(self.app)['qualified'])
        self.assertEqual(self.capability_calls, [])

    def test_path_uses_public_validator_and_fresh_callable_window_root(self):
        profile = AppProfile(self.config())
        original = self.app.locator_path
        roots = []
        def locator_path(steps):
            locator = original(steps)
            original_resolve = locator.resolve
            def resolve():
                roots.append(locator.root)
                return original_resolve()
            locator.resolve = resolve
            return locator
        with patch.object(self.app, 'locator_path', side_effect=locator_path) as validator:
            self.assertTrue(profile.inspect(self.app)['qualified'])
            self.backend.nodes['new-window'] = dict(self.backend.nodes['window'], AXChildren=['new'])
            self.backend.nodes['new'] = dict(self.backend.nodes['a'])
            self.backend.nodes['app']['AXWindows'] = ['new-window']
            self.backend.nodes['app']['AXChildren'] = ['new-window']
            self.assertTrue(profile.inspect(self.app)['qualified'])
        self.assertEqual(validator.call_count, 2)
        self.assertTrue(all(callable(root) for root in roots))
        self.assertIn(('actions', 'new'), self.capability_calls)

    def test_entire_path_stays_in_profile_window(self):
        self.backend.nodes['other'] = {'AXRole': 'AXWindow', 'AXIdentifier': 'other', 'AXChildren': ['outside']}
        self.backend.nodes['outside'] = {'AXRole': 'AXButton', 'AXIdentifier': 'apply'}
        self.backend.nodes['app']['AXWindows'].append('other')
        self.backend.nodes['app']['AXChildren'].append('other')
        self.backend.nodes['window']['AXChildren'] = ['b']
        profile = AppProfile(self.config())
        report = profile.inspect(self.app)
        self.assertFalse(report['qualified'])
        self.assertEqual(report['controls']['apply']['status'], 'UNAVAILABLE')
        self.assertEqual(self.capability_calls, [])

    def test_direct_child_index_count_and_verify_are_preserved(self):
        path = [{'relation': 'child', 'selector': {'role': 'AXButton'}, 'index': 0,
                 'expected_count': 2, 'verify': {'identifier': 'apply'}}]
        profile = AppProfile(self.config({'path': path}))
        self.assertTrue(profile.inspect(self.app)['qualified'])
        self.backend.nodes['window']['AXChildren'] = ['b', 'a']
        self.assertFalse(profile.inspect(self.app)['qualified'])

    def test_multistep_descendant_path(self):
        self.backend.nodes['group'] = {'AXRole': 'AXGroup', 'AXIdentifier': 'panel', 'AXChildren': ['a']}
        self.backend.nodes['window']['AXChildren'] = ['group', 'b']
        path = [{'relation': 'descendant', 'selector': {'identifier': 'panel'}}, *self.path]
        self.assertTrue(AppProfile(self.config({'path': path})).inspect(self.app)['qualified'])

    def test_invalid_paths_fail_at_construction_without_resolution(self):
        invalid = ([], None, 'path', [{}], [{'relation': 'typo', 'selector': {'role': 'AXButton'}}],
                   [{'relation': 'child', 'selector': {}}],
                   [{'relation': 'child', 'selector': {'role': 'AXButton'}, 'typo': True}],
                   [{'relation': 'child', 'selector': {'role': 'AXButton'}, 'index': True}])
        for path in invalid:
            with self.subTest(path=path), self.assertRaises(ValueError):
                AppProfile(self.config({'path': path}))
        self.assertEqual(self.reads, [])

    def test_construction_validates_paths_without_resolving(self):
        with patch('pymacauto.core.Locator.resolve', side_effect=AssertionError('must not resolve')):
            AppProfile(self.config())
        self.assertEqual(self.reads, [])
        self.assertEqual(self.capability_calls, [])

    def test_actual_application_path_depth_budget_is_enforced(self):
        profile = AppProfile(self.config({'path': [
            {'relation': 'child', 'selector': {'identifier': 'group'}}, *self.path]}))
        self.app.max_depth = 1
        report = profile.inspect(self.app)
        self.assertFalse(report['qualified'])
        self.assertEqual(report['controls']['apply']['error'], 'SearchLimitExceeded')
        self.assertEqual(self.capability_calls, [])

    def test_malformed_action_inventory_does_not_qualify(self):
        for available in ('AXPress', None, ['AXPress', object()]):
            with self.subTest(available=available):
                self.backend.actions = lambda ref: available
                report = AppProfile(self.config()).inspect(self.app)
                self.assertFalse(report['qualified'])
                self.assertEqual(report['controls']['apply']['status'], 'UNIQUE')

    def test_window_relation_cannot_escape_the_profile_scope(self):
        path = [{'relation': 'window', 'selector': {'identifier': 'other'}}, *self.path]
        with self.assertRaises(ValueError):
            AppProfile(self.config({'path': path}))

    def test_extended_spec_requires_path_and_exact_known_fields(self):
        for control in ({'actions': ['AXPress']}, {'path': self.path, 'selector': {'identifier': 'apply'}},
                        {'path': self.path, 'typo': True}, {'path': self.path, 'identifier': 'apply'}):
            with self.subTest(control=control), self.assertRaises(ValueError):
                AppProfile(self.config(control))

    def test_capability_names_require_lists_of_distinct_raw_ax_names(self):
        for field in ('actions', 'settable'):
            for names in (None, 'AXPress', [1], [''], ['Press'], ['AX'], ['AXPress', 'AXPress'], ['AXPress\nprivate']):
                with self.subTest(field=field, names=names), self.assertRaises(ValueError):
                    AppProfile(self.config({'path': self.path, field: names}))

    def test_source_config_is_deepcopied_and_profile_mutation_is_refused(self):
        config = self.config()
        profile = AppProfile(config)
        original_hash = profile.sha256
        config['controls']['apply']['path'][0]['selector']['identifier'] = 'changed'
        config['controls']['apply']['actions'].append('AXOther')
        self.assertTrue(profile.inspect(self.app)['qualified'])
        self.assertEqual(profile.sha256, original_hash)
        profile.config['controls']['apply']['path'][0]['selector']['identifier'] = 'changed'
        self.reads.clear()
        with self.assertRaises(UnsafeOperation):
            profile.inspect(self.app)
        self.assertEqual(self.reads, [])

    def test_unserializable_profile_mutation_is_refused(self):
        profile = AppProfile(self.config())
        profile.config['controls']['apply']['actions'].append(object())
        with self.assertRaises(UnsafeOperation):
            profile.inspect(self.app)

    def test_profile_hash_mutation_is_refused(self):
        profile = AppProfile(self.config())
        profile.sha256 = '0' * 64
        with self.assertRaises(UnsafeOperation):
            profile.inspect(self.app)

    def test_identity_mismatch_does_not_query_structure_or_capabilities(self):
        profile = AppProfile(self.config())
        self.metadata['build'] = '2'
        report = profile.inspect(self.app)
        self.assertFalse(report['qualified'])
        self.assertFalse(report['structure_match'])
        self.assertFalse(report['ability_qualified'])
        self.assertEqual(report['identity_mismatch'], ['build'])
        self.assertEqual(self.reads, [])
        self.assertEqual(self.capability_calls, [])

    def test_safe_report_never_includes_selector_or_value_inputs(self):
        self.backend.nodes['a']['AXValue'] = 'private-selector-value'
        profile = AppProfile(self.config({'value': 'private-selector-value'}))
        report = profile.require(self.app)
        self.assertNotIn('private-selector-value', json.dumps(report))
        self.assertNotIn('AXValue', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
