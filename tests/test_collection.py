import unittest
from pymacauto.collection import collect_pages
from pymacauto import MacAXError

class CollectionTests(unittest.TestCase):
    def snapshot(self,key):return {'status':'READ_OK','headers':['id'],'rows':[{'id':key}],
        'row_count':1,'sha256':key,'stable_double_read':True,'row_column_crosscheck':True}
    def test_explicit_end_is_not_global_completeness(self):
        state=['a']
        def advance(s):
            if state[0]=='b':return False
            state[0]='b';return True
        result=collect_pages(lambda:self.snapshot(state[0]),advance,key_columns=['id'])
        self.assertEqual(result['row_count'],2);self.assertFalse(result['global_complete'])
    def test_overlap_rejected_not_silently_deduplicated(self):
        with self.assertRaises(MacAXError):collect_pages(lambda:self.snapshot('a'),lambda s:True,key_columns=['id'])
    def test_budget_does_not_dispatch_extra_navigation(self):
        calls=[]
        result=collect_pages(lambda:self.snapshot('a'),lambda s:calls.append(1),key_columns=['id'],max_pages=1)
        self.assertEqual(result['stop_reason'],'PAGE_BUDGET');self.assertEqual(calls,[])
    def test_changed_page_refuses(self):
        calls=[0]
        def read():calls[0]+=1;return self.snapshot(str(calls[0]))
        with self.assertRaises(MacAXError):collect_pages(read,lambda s:False,key_columns=['id'])
