"""Structural query pruning contracts; no app business knowledge."""
import unittest
from pymacauto import Application,AmbiguousMatch,SearchLimitExceeded
from pymacauto.query import QueryScope
from test_core import MemoryAX

class QueryTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.app=Application.connect(pid=42,backend=self.b)
        self.b.nodes['window']['AXChildren']=['a','table']
        self.b.nodes['table']={'AXRole':'AXTable','AXIdentifier':'grid','AXChildren':['row']}
        self.b.nodes['row']={'AXRole':'AXRow','AXChildren':['cell']}
        self.b.nodes['cell']={'AXRole':'AXStaticText','AXValue':'private'}
        self.calls=[];get=self.b.get
        def counted(ref,attr):self.calls.append((ref,attr));return get(ref,attr)
        self.b.get=counted
    def test_explicit_leaf_roles_skip_data_subtrees(self):
        q=QueryScope(self.app,'window',leaf_roles=('AXTable',))
        self.assertEqual(q.find(role='AXTable',identifier='grid').ref,'table')
        self.assertFalse(any(ref in ('row','cell') for ref,attr in self.calls))
    def test_duplicates_never_select_first(self):
        self.b.nodes['window']['AXChildren'].append('b')
        with self.assertRaises(AmbiguousMatch):QueryScope(self.app,'window').find(title='Apply')
    def test_refs_not_cached_between_queries(self):
        q=QueryScope(self.app,'window',leaf_roles=('AXTable',))
        q.find(identifier='grid')
        self.b.nodes['window']['AXChildren']=['replacement']
        self.b.nodes['replacement']={'AXRole':'AXTable','AXIdentifier':'grid'}
        self.assertEqual(q.find(identifier='grid').ref,'replacement')
    def test_budget_still_fails_closed(self):
        self.app.max_nodes=2
        with self.assertRaises(SearchLimitExceeded):QueryScope(self.app,'window').find(identifier='apply')
    def test_leaf_policy_must_be_explicit(self):
        q=QueryScope(self.app,'window')
        q.find(identifier='grid')
        self.assertTrue(any(ref=='cell' for ref,attr in self.calls))
    def test_empty_table_is_success_not_business_claim(self):
        from pymacauto.tables import read_table
        from test_tables import TableAX
        result=read_table(TableAX(rows=[]),'table')
        self.assertEqual(result['status'],'READ_OK')
        self.assertNotIn('account_or_history_complete',result)
