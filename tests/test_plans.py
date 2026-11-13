"""Compiled selector contracts; supplementary, not native AX evidence."""
import importlib
import unittest


class Reader:
    def __init__(self, **attributes):
        self.attributes = attributes
        self.calls = []

    def get(self, ref, attr):
        self.calls.append((ref, attr))
        value = self.attributes.get(attr)
        if isinstance(value, Exception):
            raise value
        return value

    def many(self, ref, attrs):
        raise AssertionError('No eager reads across a selector failure')

    get_many = many


class PlanTests(unittest.TestCase):
    def test_compile_preserves_description_without_sharing_mutable_dicts(self):
        try:
            plans = importlib.import_module('pymacauto.plans')
        except ModuleNotFoundError:
            self.fail('The compiled selector module is not implemented')
        criteria = {'title_re': 'Apply', 'role': 'AXButton'}
        plan = plans.compile_selector(criteria)
        self.assertIsInstance(plan, plans.SelectorPlan)
        self.assertEqual(list(plan.description.items()), list(criteria.items()))
        criteria['role'] = 'AXWindow'
        description = plan.description
        description['title_re'] = 'Changed'
        self.assertEqual(plan.description,
                         {'title_re': 'Apply', 'role': 'AXButton'})

    def test_matches_in_insertion_order_and_shortcircuits(self):
        from pymacauto.plans import compile_selector
        reader = Reader(AXTitle='Other', AXRole=RuntimeError('unreachable'))
        plan = compile_selector({'title': 'Apply', 'role': 'AXButton'})
        self.assertFalse(plan.matches(reader, 'node'))
        self.assertEqual(reader.calls, [('node', 'AXTitle')])

    def test_regex_search_is_precompiled_and_reused(self):
        from unittest.mock import patch
        from pymacauto.plans import compile_selector
        plan = compile_selector({'title_re': 'Appl[yY]', 'role': 'AXButton'})
        reader = Reader(AXTitle='Click Apply now', AXRole='AXButton')
        with patch('re.compile', side_effect=AssertionError('recompiled')), \
                patch('re.search', side_effect=AssertionError('not compiled')):
            self.assertTrue(plan.matches(reader, 'one'))
            self.assertTrue(plan.matches(reader, 'two'))
        self.assertEqual(reader.calls, [('one', 'AXTitle'), ('one', 'AXRole'),
                                        ('two', 'AXTitle'), ('two', 'AXRole')])

    def test_secure_guard_precedes_value_read(self):
        from pymacauto.errors import UnsafeOperation
        from pymacauto.plans import compile_selector
        reader = Reader(AXSubrole='AXSecureTextField',
                        AXValue=AssertionError('secret value requested'))
        plan = compile_selector({'value': 'secret', 'title': 'Title'})
        with self.assertRaises(UnsafeOperation):
            plan.matches(reader, 'secure')
        self.assertEqual(reader.calls, [('secure', 'AXSubrole')])

    def test_earlier_failure_skips_even_secure_guard(self):
        from pymacauto.plans import compile_selector
        reader = Reader(AXTitle='Other', AXSubrole='AXSecureTextField')
        plan = compile_selector({'title': 'Title', 'value': 'secret'})
        self.assertFalse(plan.matches(reader, 'secure'))
        self.assertEqual(reader.calls, [('secure', 'AXTitle')])

    def test_regex_requires_immutable_text_pattern(self):
        import re
        from pymacauto.plans import compile_selector
        for pattern in (b'Apply', re.compile(b'Apply'), bytearray(b'Apply')):
            with self.subTest(pattern=pattern):
                with self.assertRaises((ValueError, TypeError)):
                    compile_selector({'title_re': pattern})
        pattern = re.compile('apply', re.IGNORECASE)
        plan = compile_selector({'title_re': pattern})
        self.assertIs(plan.description['title_re'], pattern)
        self.assertTrue(plan.matches(Reader(AXTitle='Click APPLY'), 'node'))

    def test_frozen_plan_contains_only_immutable_specification_tuples(self):
        from dataclasses import FrozenInstanceError, fields
        import re
        from pymacauto.plans import compile_selector
        plan = compile_selector({'title_re': 'Apply', 'value': 1})
        with self.assertRaises(FrozenInstanceError):
            plan._description = ()
        for field in fields(plan):
            self.assertIsInstance(getattr(plan, field.name), tuple)
        self.assertIsInstance(plan._predicates[0][2], re.Pattern)
        self.assertIsInstance(hash(plan), int)

    def test_core_validation_is_reused(self):
        import re
        from unittest.mock import patch
        from pymacauto import core
        from pymacauto.plans import compile_selector
        criteria = {'title': 'Apply'}
        with patch.object(core, '_selector', wraps=core._selector) as validate:
            compile_selector(criteria)
        validate.assert_called_once_with(criteria)
        invalid = ({}, {'unknown': 'x'}, {'enabled_re': 'x'}, {'enabled': 1},
                   {'title': None}, {'value': []}, {'value': {}},
                   {'value': float('inf')}, {'value': float('nan')},
                   {'title_re': '['}, {'title_re': 1})
        for selector in invalid:
            with self.subTest(selector=selector):
                with self.assertRaises((ValueError, TypeError, re.error)):
                    compile_selector(selector)

    def test_matches_and_read_order_agree_with_core(self):
        from pymacauto.core import _matches, _selector
        from pymacauto.errors import AttributeUnsupported
        from pymacauto.plans import compile_selector
        cases = [
            ({'value': True}, {'AXValue': 1}),
            ({'value': 1}, {'AXValue': True}),
            ({'value': False}, {'AXValue': 0}),
            ({'value': 0}, {'AXValue': False}),
            ({'value': 1}, {'AXValue': 1.0}),
            ({'value': 1.0}, {'AXValue': 1}),
            ({'value': None}, {}),
            ({'enabled': True}, {'AXEnabled': 1}),
            ({'title_re': 'Apply'}, {'AXTitle': 1}),
            ({'title_re': 'Apply'}, {}),
            ({'title': 'Apply'}, {'AXTitle': AttributeUnsupported('missing')}),
            ({'value': None}, {'AXValue': AttributeUnsupported('missing')}),
            ({'value_re': 'partial'}, {'AXValue': 'a partial value'}),
            ({'value': 'ordinary'}, {'AXValue': 'ordinary',
                                    'AXSubrole': AttributeUnsupported('missing')}),
            ({'role': 'AXButton', 'value': 'ordinary'},
             {'AXRole': 'AXButton', 'AXValue': 'ordinary'}),
        ]
        for selector, attributes in cases:
            with self.subTest(selector=selector, attributes=attributes):
                old_reader = Reader(**attributes)
                new_reader = Reader(**attributes)
                expected = _matches(old_reader, 'node', _selector(selector))
                self.assertEqual(compile_selector(selector).matches(new_reader, 'node'),
                                 expected)
                self.assertEqual(new_reader.calls, old_reader.calls)

    def test_later_exception_is_not_suppressed_or_reordered(self):
        from pymacauto.plans import compile_selector
        error = RuntimeError('native failure')
        reader = Reader(AXTitle='Apply', AXRole=error)
        plan = compile_selector({'title': 'Apply', 'role': 'AXButton'})
        with self.assertRaises(RuntimeError) as raised:
            plan.matches(reader, 'node')
        self.assertIs(raised.exception, error)
        self.assertEqual(reader.calls, [('node', 'AXTitle'), ('node', 'AXRole')])

    def test_each_value_predicate_rechecks_secure_guard(self):
        from pymacauto.errors import UnsafeOperation
        from pymacauto.plans import compile_selector

        class ChangingReader(Reader):
            def get(self, ref, attr):
                value = super().get(ref, attr)
                if attr == 'AXValue':
                    self.attributes['AXSubrole'] = 'AXSecureTextField'
                return value

        reader = ChangingReader(AXSubrole='AXTextField', AXValue='ordinary')
        plan = compile_selector({'value': 'ordinary', 'value_re': 'ordinary'})
        with self.assertRaises(UnsafeOperation):
            plan.matches(reader, 'node')
        self.assertEqual(reader.calls, [('node', 'AXSubrole'), ('node', 'AXValue'),
                                        ('node', 'AXSubrole')])

    def test_plan_retains_neither_reader_nor_reference_nor_result(self):
        import gc
        import weakref
        from pymacauto.plans import compile_selector

        class Ref:
            pass

        plan = compile_selector({'title': 'Apply'})
        reader = Reader(AXTitle='Apply')
        ref = Ref()
        reader_weak, ref_weak = weakref.ref(reader), weakref.ref(ref)
        before = hash(plan)
        self.assertTrue(plan.matches(reader, ref))
        reader.attributes['AXTitle'] = 'Changed'
        self.assertFalse(plan.matches(reader, ref))
        self.assertEqual(hash(plan), before)
        del reader, ref
        gc.collect()
        self.assertIsNone(reader_weak())
        self.assertIsNone(ref_weak())

    def test_description_preserves_serialized_identity(self):
        import json
        from pymacauto.plans import compile_selector
        selector = {'title_re': '中文 .*', 'value': 1.0, 'enabled': False}
        original = json.dumps(selector, ensure_ascii=False)
        self.assertEqual(json.dumps(compile_selector(selector).description,
                                   ensure_ascii=False), original)


if __name__ == '__main__':
    unittest.main()
