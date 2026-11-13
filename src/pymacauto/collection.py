"""Explicit caller-driven bounded page collection; never asserts global completeness."""
import time
from .core import _positive
from .errors import MacAXError


def collect_pages(read_page,advance,*,key_columns,max_pages=10,max_rows=10000,timeout=30):
    """advance(snapshot)->bool is caller-authorized and may change UI.

    Collection requires stable snapshots and unique explicit row keys. It
    rejects overlap instead of guessing scroll offsets or silently deduping.
    The caller owns navigation, end-condition authority and page restoration.
    """
    _positive(max_pages,'max_pages',integer=True);_positive(max_rows,'max_rows',integer=True);_positive(timeout,'timeout')
    if not callable(read_page) or not callable(advance):raise ValueError('Explicit callbacks required')
    if not isinstance(key_columns,(list,tuple)) or not key_columns or len(set(key_columns))!=len(key_columns):
        raise ValueError('Distinct nonempty key columns required')
    start=time.monotonic();pages=[];rows=[];seen=set();schema=None
    def check():
        if time.monotonic()-start>=timeout:raise MacAXError('COLLECTION_TIMEOUT')
    while len(pages)<max_pages:
        check();snapshot=read_page();check()
        if snapshot.get('status')!='READ_OK' or snapshot.get('stable_double_read') is not True or snapshot.get('row_column_crosscheck') is not True:
            raise MacAXError('UNVERIFIED_COLLECTION_PAGE')
        headers=snapshot['headers']
        if schema is None:schema=list(headers)
        if schema!=headers or not set(key_columns)<=set(headers):raise MacAXError('COLLECTION_SCHEMA_CHANGED')
        current=snapshot['rows']
        if snapshot['row_count']!=len(current):raise MacAXError('COLLECTION_SHAPE_MISMATCH')
        if len(rows)+len(current)>max_rows:raise MacAXError('COLLECTION_ROW_BUDGET')
        for row in current:
            key=tuple(row[k] for k in key_columns)
            if not all(isinstance(v,str) and v for v in key):raise MacAXError('COLLECTION_KEY_UNAVAILABLE')
            if key in seen:raise MacAXError('COLLECTION_DUPLICATE_OR_OVERLAP')
            seen.add(key);rows.append(dict(row))
        pages.append({'sha256':snapshot['sha256'],'row_count':len(current)})
        # Verify the same exposed page once more before allowing navigation.
        again=read_page();check()
        if any(again.get(k)!=snapshot.get(k) for k in ('headers','rows','sha256','row_count','stable_double_read','row_column_crosscheck')):
            raise MacAXError('COLLECTION_PAGE_CHANGED')
        if len(pages)>=max_pages:
            reason='PAGE_BUDGET';break
        more=advance(snapshot);check()
        if type(more) is not bool:raise MacAXError('COLLECTION_ADVANCE_MUST_RETURN_BOOL')
        if not more:reason='CALLER_END_OBSERVED';break
    return {'status':'READ_OK','headers':schema,'rows':rows,'row_count':len(rows),'pages':pages,
            'page_count':len(pages),'stop_reason':reason,'completeness_scope':'EXPLICITLY_VISITED_PAGES_ONLY',
            'global_complete':False,'elapsed_seconds':time.monotonic()-start}
