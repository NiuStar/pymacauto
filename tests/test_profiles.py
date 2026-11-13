import unittest
from pymacauto import Application,UnsafeOperation
from pymacauto.profiles import AppProfile
from test_core import MemoryAX

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window'];self.b.nodes['window']['AXIdentifier']='win'
        self.metadata={'bundle_id':'org.pymacauto.demo','version':'1','build':'1'}
        self.b.app_metadata=lambda pid:self.metadata
        self.app=Application.connect(pid=42,backend=self.b)
        self.p=AppProfile({**self.metadata,'window':{'identifier':'win'},'controls':{'apply':{'identifier':'apply'}}})
    def test_unique_then_missing_diff_is_redacted(self):
        before=self.p.require(self.app)
        self.b.nodes['a']['AXIdentifier']='changed';self.b.nodes['a']['AXValue']='private'
        after=self.p.inspect(self.app)
        self.assertFalse(after['qualified']);self.assertNotIn('private',str(after))
        self.assertEqual(self.p.diff(before,after)['changed_controls'],['apply'])
    def test_upgrade_refuses_before_structure_search(self):
        self.metadata['version']='2'
        with self.assertRaises(UnsafeOperation):self.p.require(self.app)
        self.assertEqual(self.p.inspect(self.app)['identity_mismatch'],['version'])
