"""Exercise the real table algorithm on both scalar and batch paths."""
import unittest
from pymacauto.tables import read_table
from pymacauto import AXError,MacAXError
from test_tables import TableAX

class BatchedTableTests(unittest.TestCase):
    def batch(self,b):
        b.batch_calls=0
        def many(ref,names,optional=()):
            b.batch_calls+=1
            return {name:b.get(ref,name) for name in names}
        b.get_many=many
        return b
    def test_batch_and_scalar_preserve_exact_result(self):
        scalar=read_table(TableAX(),'table')
        b=self.batch(TableAX());batched=read_table(b,'table')
        self.assertGreater(b.batch_calls,0)
        for key in ('headers','rows','row_count','sha256','stable_double_read','row_column_crosscheck'):
            self.assertEqual(scalar[key],batched[key])
    def test_secure_field_never_requests_value(self):
        b=self.batch(TableAX());b.nodes['v0_0']['AXSubrole']='AXSecureTextField'
        get=b.get
        def guarded(ref,attr):
            if ref=='v0_0' and attr=='AXValue':self.fail('Secure value read')
            return get(ref,attr)
        b.get=guarded
        with self.assertRaises(MacAXError):read_table(b,'table')
    def test_batch_stale_propagates(self):
        b=self.batch(TableAX())
        def failed(*a,**kw):raise AXError('batch',-25202)
        b.get_many=failed
        with self.assertRaises(AXError):read_table(b,'table')
    def test_batch_does_not_mask_double_read_change(self):
        b=self.batch(TableAX());get=b.get;count=0
        def changing(ref,attr):
            nonlocal count
            if ref=='v0_0' and attr=='AXValue':
                count+=1;return 'first' if count==1 else 'second'
            return get(ref,attr)
        b.get=changing
        with self.assertRaises(MacAXError):read_table(b,'table')
    def test_empty_batch_table_is_success(self):
        result=read_table(self.batch(TableAX(rows=[])),'table')
        self.assertEqual(result['status'],'READ_OK')
        self.assertEqual(result['row_count'],0)
