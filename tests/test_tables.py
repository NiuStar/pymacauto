import unittest
from pymacauto import MacAXError
from pymacauto.tables import read_table


class TableAX:
    """Labelled in-memory AppKit table; no native acceptance claim."""
    def __init__(self, rows=None, headers=None):
        headers = headers or ['证券代码', '股票余额', '可用余额', '成本价']
        rows = [['600000','200','100','10.50']] if rows is None else rows
        self.nodes = {'table': {'AXRole':'AXTable','AXRows':[], 'AXColumns':[]}}
        for j, title in enumerate(headers):
            col, head = f'c{j}', f'h{j}'
            self.nodes['table']['AXColumns'].append(col)
            self.nodes[col] = {'AXIndex':j,'AXHeader':head,'AXRows':[]}
            self.nodes[head] = {'AXTitle':title}
        for i, values in enumerate(rows):
            row=f'r{i}'; self.nodes['table']['AXRows'].append(row)
            self.nodes[row]={'AXIndex':i,'AXChildren':[]}
            for j, value in enumerate(values):
                cell=f'v{i}_{j}'
                self.nodes[row]['AXChildren'].append(cell)
                self.nodes[cell]={'AXRole':'AXStaticText','AXValue':value}
                if f'c{j}' in self.nodes: self.nodes[f'c{j}']['AXRows'].append(cell)
    def get(self, ref, attr): return self.nodes[ref].get(attr)
    def key(self, ref): return ref


class TableTests(unittest.TestCase):
    def test_exact_strings_and_both_axes_are_verified(self):
        b=TableAX(); result=read_table(b,'table')
        self.assertEqual(result['rows'][0]['证券代码'],'600000')
        self.assertEqual(result['rows'][0]['成本价'],'10.50')
        self.assertTrue(result['row_column_crosscheck'])
        self.assertTrue(result['stable_double_read'])
        self.assertEqual(result['row_count'],1)
        self.assertEqual(result['completeness_scope'],'AX_EXPOSED_ROWS_ONLY')
    def test_duplicate_headers_rejected(self):
        with self.assertRaises(MacAXError): read_table(TableAX(headers=['重复','重复'],rows=[['1','2']]),'table')
    def test_partial_row_rejected(self):
        with self.assertRaises(MacAXError): read_table(TableAX(rows=[['600000','100']]),'table')
    def test_duplicate_or_noncontiguous_indexes_rejected(self):
        b=TableAX(rows=[['600000','200','100','10'],['000001','100','0','8']]);b.nodes['r1']['AXIndex']=0
        with self.assertRaises(MacAXError): read_table(b,'table')
    def test_wrong_axis_reference_rejected(self):
        b=TableAX(); b.nodes['c1']['AXRows']=['v0_0']
        with self.assertRaises(MacAXError): read_table(b,'table')
    def test_double_read_change_rejected(self):
        b=TableAX(); original=b.get; reads=0
        def get(ref,attr):
            nonlocal reads
            if ref=='v0_0' and attr=='AXValue':
                reads+=1
                return '600000' if reads==1 else '000001'
            return original(ref,attr)
        b.get=get
        with self.assertRaises(MacAXError): read_table(b,'table')
    def test_empty_is_not_proof_of_empty_account_or_history(self):
        result=read_table(TableAX(rows=[]),'table')
        self.assertEqual(result['status'],'READ_OK')
        self.assertEqual(result['row_count'],0)
        self.assertNotIn('account_or_history_complete',result)
    def test_native_exception_propagates_not_empty(self):
        from pymacauto import AXError
        b=TableAX()
        def get(*args): raise AXError('read',-25202)
        b.get=get
        with self.assertRaises(AXError): read_table(b,'table')
    def test_missing_or_secure_value_rejected(self):
        for value, subrole in ((None,None),('hidden','AXSecureTextField')):
            b=TableAX(); b.nodes['v0_0'].update(AXValue=value,AXSubrole=subrole)
            with self.assertRaises(MacAXError): read_table(b,'table')
    def test_order_and_deal_nonempty_field_mapping(self):
        cases=[(['委托日期','委托时间','证券代码','委托数量','撤销数量','委托价格','合同编号'],
                ['20261113','09:31:00','000001','100','0','10.50','0000123']),
               (['成交日期','成交时间','证券代码','成交数量','成交均价','成交金额','成交编号'],
                ['20261113','09:31:01','000001','100','10.50','1050.00','0000042'])]
        for headers, values in cases:
            with self.subTest(headers=headers):
                result=read_table(TableAX(rows=[values],headers=headers),'table')
                self.assertEqual(result['rows'],[dict(zip(headers,values))])
    def test_boolean_indexes_rejected(self):
        for node in ('r0','c0'):
            b=TableAX();b.nodes[node]['AXIndex']=False
            with self.assertRaises(MacAXError):read_table(b,'table')

    def test_declared_count_and_budget_mismatch_rejected(self):
        b=TableAX(); b.nodes['table']['AXRowCount']=2
        with self.assertRaises(MacAXError): read_table(b,'table')
        with self.assertRaises(MacAXError): read_table(TableAX(),'table',max_cells=2)
