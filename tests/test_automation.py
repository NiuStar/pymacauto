"""In-memory facade contracts; native Mac qualification is separate."""
import copy
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pymacauto import Application, UnsafeOperation
from pymacauto.core import Locator
from pymacauto.operations import Condition, OperationSession
from pymacauto.profiles import AppProfile
from test_core import MemoryAX


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.b = MemoryAX()
        self.b.nodes['app']['AXWindows'] = ['window']
        self.b.nodes['window']['AXIdentifier'] = 'win'
        self.b.nodes['a'].update(AXRole='AXTextField', AXValue=' raw 01 ')
        self.b.nodes['b'].update(AXIdentifier='result', AXValue='before')
        self.metadata = {'bundle_id': 'org.pymacauto.demo', 'version': '1', 'build': '1'}
        self.b.app_metadata = lambda pid: dict(self.metadata)
        self.b.is_settable = lambda ref, name: name == 'AXValue'
        self.app = Application.connect(pid=42, backend=self.b)
        self.config = {**self.metadata, 'window': {'identifier': 'win'}, 'controls': {
            'field': {'path': [{'relation': 'child', 'selector': {'identifier': 'apply'}}],
                      'settable': ['AXValue']},
            'result': {'identifier': 'result'}}}
        self.profile = AppProfile(self.config)

    def automation(self, **kwargs):
        from pymacauto.automation import Automation
        result = Automation(self.app, self.profile, **kwargs)
        self.addCleanup(result.close)
        return result

    def test_read_is_raw_window_rooted_and_reacquires_rebuilt_window(self):
        with self.automation() as automation:
            control = automation.control('field')
            self.assertEqual(control.read(), ' raw 01 ')
            self.assertIsInstance(control.locator, Locator)
            self.assertIsNone(control.locator.root)
            self.assertEqual(control.locator.chain[0]['relation'], 'window')
            self.b.nodes['new-window'] = dict(self.b.nodes['window'], AXChildren=['new-field', 'b'])
            self.b.nodes['new-field'] = dict(self.b.nodes['a'], AXValue='new 02')
            self.b.nodes['app']['AXWindows'] = ['new-window']
            self.b.nodes['app']['AXChildren'] = []
            self.assertEqual(control.read(), 'new 02')
            condition = automation.condition('field', value='new 02')
            self.assertIsInstance(condition, Condition)
            self.assertTrue(condition.check())
        with self.assertRaises(UnsafeOperation):
            control.read()
        with self.assertRaises(UnsafeOperation):
            automation.control('field')
        self.assertEqual(self.b.calls, [])

    def test_fill_uses_owner_apply_and_matches_generic_durable_request(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name).resolve() / 'ops.sqlite'
        writes = []
        original = self.b.set
        def set_value(ref, name, value):
            writes.append((ref, name, value))
            original(ref, name, value)
        self.b.set = set_value
        with self.automation(journal=path) as automation:
            first = automation.control('field').fill(' 001 中文 ', operation_id='fill-1', timeout=0)
            self.assertEqual(first['status'], 'CONFIRMED')
            self.assertEqual(automation.control('field').read(), ' 001 中文 ')
        target = self.app.locator_path([
            {'relation': 'window', 'selector': {'identifier': 'win'}},
            {'relation': 'child', 'selector': {'identifier': 'apply'}}])
        with OperationSession(self.app, window={'identifier': 'win'}, profile=self.profile, journal=path) as generic:
            replay = generic.apply(target, 'fill', value=' 001 中文 ', operation_id='fill-1', timeout=0)
        self.assertEqual(first, replay)
        self.assertEqual(writes, [('a', 'AXValue', ' 001 中文 ')])

    def test_click_requires_explicit_condition_and_never_retries_unknown_effect(self):
        self.b.nodes['a']['AXRole'] = 'AXButton'
        with self.automation() as automation:
            button = automation.control('field')
            with self.assertRaises(TypeError):
                button.click()
            with self.assertRaises(ValueError):
                button.click(expect=lambda: True)
            self.assertEqual(self.b.calls, [])
            condition = automation.condition('result', value='after')
            first = button.click(expect=condition, operation_id='click-1', timeout=0)
            second = button.click(expect=condition, operation_id='click-1', timeout=0)
            self.assertEqual(first['status'], 'DISPATCHED_UNCONFIRMED')
            self.assertEqual(first, second)
            self.assertEqual(self.b.calls, [('a', 'AXPress')])
            def perform(ref, action):
                self.b.calls.append((ref, action))
                self.b.nodes['b']['AXValue'] = 'after'
            self.b.perform = perform
            confirmed = button.click(expect=condition, operation_id='click-2', timeout=0)
            self.assertEqual(confirmed['status'], 'CONFIRMED')

    def test_check_uses_protected_apply_and_refuses_closed_wrapper(self):
        self.b.nodes['a'].update(AXRole='AXCheckBox', AXValue=0)
        def perform(ref, action):
            self.b.calls.append((ref, action))
            self.b.nodes[ref]['AXValue'] = 1 - self.b.nodes[ref]['AXValue']
        self.b.perform = perform
        with self.automation() as automation:
            checkbox = automation.control('field')
            receipt = checkbox.check(True, operation_id='check-1', timeout=0)
            self.assertEqual(receipt['status'], 'CONFIRMED')
            self.assertEqual(checkbox.read(), 1)
            self.assertEqual(checkbox.check(True, operation_id='check-1', timeout=0), receipt)
        with self.assertRaises(UnsafeOperation):
            checkbox.check(False)
        with self.assertRaises(UnsafeOperation):
            checkbox.fill('no')
        with self.assertRaises(UnsafeOperation):
            checkbox.click(expect=Condition(checkbox.locator))
        self.assertEqual(self.b.calls, [('a', 'AXPress')])

    def test_read_table_returns_public_strict_result_and_forwards_limits(self):
        from pymacauto import MacAXError
        from pymacauto.core import Element
        from pymacauto.tables import read_table
        from test_tables import TableAX
        table = TableAX(rows=[['001', ' raw ']], headers=['ID', 'Value'])
        self.b.nodes.update(table.nodes)
        self.b.nodes['table']['AXIdentifier'] = 'table'
        self.b.nodes['window']['AXChildren'].append('table')
        config = copy.deepcopy(self.config)
        config['controls']['grid'] = {'identifier': 'table'}
        self.profile = AppProfile(config)
        with self.automation() as automation:
            control = automation.control('grid')
            expected = read_table(self.b, 'table')
            actual = control.read_table()
            for key in expected.keys() - {'captured_at', 'elapsed_seconds'}:
                self.assertEqual(actual[key], expected[key])
            self.assertTrue(expected['stable_double_read'])
            self.assertTrue(expected['row_column_crosscheck'])
            with self.assertRaises(MacAXError):
                control.read_table(max_cells=1)
            # A delegation boundary check: no summary/copy replaces the public result.
            with patch.object(Element, 'read_table', return_value=expected) as reader:
                self.assertIs(control.read_table(max_cells=12), expected)
                reader.assert_called_once_with(max_cells=12)
        with self.assertRaises(UnsafeOperation):
            control.read_table()

    def test_page_ensure_uses_same_owner_and_copies_configuration(self):
        import test_pages
        fixture = test_pages.PageTests()
        fixture.setUp()
        self.app, self.b = fixture.app, fixture.b
        self.b.app_metadata = lambda pid: dict(self.metadata)
        self.profile = AppProfile({**self.metadata, 'window': {'identifier': 'window'},
                                  'controls': {'A': {'identifier': 'page.A'}, 'B': {'identifier': 'page.B'}}})
        pages = {'window': {'identifier': 'window'}, 'pages': fixture.pages,
                 'trigger_children_only': True}
        with self.automation(pages=pages) as automation:
            page = automation.page('B')
            pages['pages']['B']['headers'].append('external mutation')
            with patch.object(automation.operations, 'execute', wraps=automation.operations.execute) as execute:
                result = page.ensure(timeout=1, operation_id='page-1')
            self.assertEqual(result['page'], 'B')
            self.assertTrue(result['receipt']['verified'])
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.kwargs['operation_id'], 'page-1')
            self.assertEqual(automation.page('B').ensure(timeout=0)['receipt']['status'], 'ALREADY_OBSERVED')
            self.assertEqual(self.b.calls, [('b', 'AXPress')])
            with self.assertRaises(ValueError):
                automation.page('missing')
        with self.assertRaises(UnsafeOperation):
            page.ensure()
        with self.assertRaises(UnsafeOperation):
            automation.page('B')

    def test_profile_drift_refuses_existing_and_new_wrappers_before_read(self):
        with self.automation() as automation:
            field = automation.control('field')
            self.profile.config['controls']['field']['path'][0]['selector']['identifier'] = 'result'
            with self.assertRaises(UnsafeOperation):
                field.read()
            with self.assertRaises(UnsafeOperation):
                automation.control('result')
            with self.assertRaises(UnsafeOperation):
                automation.condition('result')
        self.assertEqual(self.b.calls, [])

    def test_page_and_operation_scope_drift_refused_before_dispatch(self):
        pages = {'window': {'identifier': 'win'}, 'pages': {'A': {
            'trigger': {'identifier': 'apply'}, 'table': {'role': 'AXTable'}, 'headers': ['ID']}}}
        with self.automation(pages=pages) as automation:
            page = automation.page('A')
            automation._pages.window['identifier'] = 'other'
            with self.assertRaises(UnsafeOperation):
                page.ensure(timeout=0)
        with self.automation() as automation:
            field = automation.control('field')
            automation.operations.window['identifier'] = 'other'
            with self.assertRaises(UnsafeOperation):
                field.fill('no', timeout=0)
        self.assertEqual(self.b.calls, [])

    def test_unknown_names_and_no_pages_refuse_without_input(self):
        with self.automation() as automation:
            with self.assertRaises(ValueError):
                automation.control('missing')
            with self.assertRaises(ValueError):
                automation.condition('missing', value='x')
            with self.assertRaises(ValueError):
                automation.page('missing')
        self.assertEqual(self.b.calls, [])

    def test_bad_page_scope_closes_real_owner_and_journal(self):
        from pymacauto.automation import Automation
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name).resolve() / 'ops.sqlite'
        owners, databases = [], []
        def owner(*args, **kwargs):
            result = OperationSession(*args, **kwargs)
            owners.append(result)
            databases.append(result.journal.db)
            return result
        page = {'trigger': {'identifier': 'apply'}, 'table': {'role': 'AXTable'}, 'headers': ['ID']}
        for config in ({'window': {'identifier': 'other'}, 'pages': {'A': page}},
                       {'window': {'identifier': 'win'}, 'pages': {'A': page}, 'typo': True}):
            with self.subTest(config=config), patch('pymacauto.automation.OperationSession', side_effect=owner):
                with self.assertRaises(ValueError):
                    Automation(self.app, self.profile, journal=path, pages=config)
                self.assertTrue(owners[-1]._closed)
                with self.assertRaises(sqlite3.ProgrammingError):
                    databases[-1].execute('SELECT 1')
        self.assertEqual(self.b.calls, [])

    def test_profile_identity_or_capability_failure_cannot_initialize(self):
        from pymacauto.automation import Automation
        self.metadata['build'] = 'drift'
        with self.assertRaises(UnsafeOperation):
            Automation(self.app, self.profile)
        self.metadata['build'] = '1'
        self.b.is_settable = lambda ref, name: False
        with self.assertRaises(UnsafeOperation):
            Automation(self.app, self.profile)
        self.assertEqual(self.b.calls, [])

    def test_stop_and_modal_guards_are_real_and_prevent_input(self):
        stopped = threading.Event()
        with self.automation(stop=stopped) as automation:
            stopped.set()
            receipt = automation.control('field').fill('new', timeout=0)
            self.assertEqual(receipt['status'], 'NOT_DISPATCHED')
            self.assertEqual(receipt['error'], 'StopRequested')
        with self.automation() as automation:
            self.b.nodes['window']['AXSheets'] = ['sheet']
            receipt = automation.control('field').fill('new', timeout=0)
            self.assertEqual(receipt['status'], 'NOT_DISPATCHED')
            self.assertEqual(receipt['error'], 'UnsafeOperation')
        self.assertEqual(self.b.nodes['a']['AXValue'], ' raw 01 ')
        self.assertEqual(self.b.calls, [])

    def test_flat_control_is_descendant_of_approved_window_only(self):
        self.b.nodes['foreign'] = {'AXRole': 'AXWindow', 'AXIdentifier': 'foreign', 'AXChildren': ['outside']}
        self.b.nodes['outside'] = dict(self.b.nodes['b'], AXValue='foreign')
        self.b.nodes['app']['AXWindows'].append('foreign')
        self.b.nodes['app']['AXChildren'].append('foreign')
        with self.automation() as automation:
            control = automation.control('result')
            self.assertEqual(control.read(), 'before')
            self.assertEqual(control.locator.chain[0]['relation'], 'window')
            self.assertEqual(control.locator.chain[1]['relation'], 'descendant')
            self.assertIsNone(control.locator.root)
        self.assertEqual(self.b.calls, [])

    def test_externally_closed_owner_refuses_wrapper_reads(self):
        automation = self.automation()
        field = automation.control('field')
        automation.operations.close()
        with self.assertRaises(UnsafeOperation):
            field.read()

    def test_failed_context_entry_closes_acquired_journal(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        automation = self.automation(journal=Path(temp.name).resolve() / 'ops.sqlite')
        database = automation.operations.journal.db
        self.profile.sha256 = '0' * 64
        with self.assertRaises(UnsafeOperation):
            with automation:
                self.fail('Drifted context entered')
        self.assertTrue(automation.operations._closed)
        with self.assertRaises(sqlite3.ProgrammingError):
            database.execute('SELECT 1')


if __name__ == '__main__':
    unittest.main()
