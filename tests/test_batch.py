"""Batch native error semantics; no fabricated native-acceptance claim."""
import unittest
from types import SimpleNamespace
from pymacauto.native import NativeBackend
from pymacauto import AXError,MacAXError,AttributeUnsupported

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.b=object.__new__(NativeBackend)
        self.calls=[];self.result=(0,['AXButton',None])
        self.b._ax=SimpleNamespace(kAXErrorSuccess=0,kAXErrorAttributeUnsupported=-25205,
                                  kAXErrorAPIDisabled=-25211,kAXErrorNoValue=-25212)
        def copy(ref,names,options,out):
            self.calls.append((ref,names,options));return self.result
        self.b._ax.AXUIElementCopyMultipleAttributeValues=copy
        def normalize(value,operation):
            if isinstance(value,Exception):raise value
            return value
        self.b._normalize=normalize
    def test_one_native_call_and_attribute_order(self):
        self.assertEqual(self.b.get_many('ref',['AXRole','AXSubrole']),{'AXRole':'AXButton','AXSubrole':None})
        self.assertEqual(len(self.calls),1)
    def test_optional_missing_is_none_not_general_error(self):
        self.result=(0,['AXButton',AttributeUnsupported('unsupported')])
        self.assertEqual(self.b.get_many('ref',['AXRole','AXSubrole'],optional=('AXSubrole',))['AXSubrole'],None)
        with self.assertRaises(AttributeUnsupported):self.b.get_many('ref',['AXRole','AXSubrole'])
    def test_stale_error_is_not_optional_none(self):
        self.result=(0,['AXButton',AXError('batch-field',-25202)])
        with self.assertRaises(AXError):self.b.get_many('ref',['AXRole','AXSubrole'],optional=('AXSubrole',))
    def test_outer_error_and_short_array_fail(self):
        self.result=(-25204,None)
        with self.assertRaises(AXError):self.b.get_many('ref',['AXRole'])
        self.result=(0,[])
        with self.assertRaises(MacAXError):self.b.get_many('ref',['AXRole'])
    def test_input_rejected_before_native_call(self):
        for names in ([],['AXRole','AXRole'],'AXRole'):
            with self.assertRaises(ValueError):self.b.get_many('ref',names)
        self.assertEqual(self.calls,[])
