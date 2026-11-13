import unittest
from pymacauto import MacAXError
from pymacauto.tables import read_table
from test_tables import TableAX

class NestedCells(unittest.TestCase):
    def test_nested_cell_single_static_text_preserves_values(self):
        b=TableAX()
        # Wrap every existing static cell without changing row/column identity.
        for ref,node in list(b.nodes.items()):
            if node.get('AXRole')=='AXStaticText':
                b.nodes[ref+'.text']=dict(node)
                b.nodes[ref]={'AXRole':'AXCell','AXChildren':[ref+'.text']}
        result=read_table(b,'table')
        self.assertEqual(result['status'],'READ_OK')
        self.assertTrue(result['row_column_crosscheck'])
    def test_multiple_text_children_are_not_concatenated(self):
        b=TableAX()
        ref=next(k for k,n in b.nodes.items() if n.get('AXRole')=='AXStaticText')
        b.nodes[ref]={'AXRole':'AXCell','AXChildren':['left','right']}
        b.nodes['left']={'AXRole':'AXStaticText','AXValue':'a'}
        b.nodes['right']={'AXRole':'AXStaticText','AXValue':'b'}
        with self.assertRaises(MacAXError):read_table(b,'table')
