"""Exact native AX table extraction. No clicking, focus or value coercion."""
from datetime import datetime, timezone
import hashlib
import json
import time
from .core import _positive
from .errors import AttributeUnsupported, MacAXError


def optional(b, ref, attr):
    try: return b.get(ref, attr)
    except AttributeUnsupported: return None


def read_table(backend, table, *, max_cells=100000, timeout=15):
    _positive(max_cells,'max_cells',integer=True)
    _positive(timeout,'timeout')
    start=time.monotonic()
    def check():
        if time.monotonic()-start >= timeout: raise MacAXError('TABLE_READ_TIMEOUT')
    def get(ref,attr):
        check()
        return optional(backend,ref,attr)
    def many(ref,names):
        check()
        method=getattr(backend,'get_many',None)
        if callable(method):return method(ref,names,optional=names)
        return {name:get(ref,name) for name in names}
    def sequence(ref,attr):
        value=get(ref,attr)
        if not isinstance(value,(list,tuple)): raise MacAXError('TABLE_ARRAY_UNAVAILABLE:'+attr)
        return list(value)
    def sample():
        if get(table,'AXRole')!='AXTable': raise MacAXError('NOT_AX_TABLE')
        columns=sequence(table,'AXColumns'); rows=sequence(table,'AXRows')
        if not columns or len(rows)*len(columns)>max_cells: raise MacAXError('TABLE_EMPTY_SCHEMA_OR_CELL_BUDGET')
        if len({backend.key(r) for r in rows})!=len(rows): raise MacAXError('DUPLICATE_AX_ROW')
        headers=[]
        for j,col in enumerate(columns):
            fields=many(col,['AXIndex','AXHeader'])
            index=fields['AXIndex']
            if type(index) is not int or index!=j: raise MacAXError('COLUMN_INDEX_MISMATCH')
            header=fields['AXHeader']
            title=get(header,'AXTitle') if header is not None else None
            if not isinstance(title,str) or not title.strip(): raise MacAXError('MISSING_COLUMN_TITLE')
            headers.append(title)
        if len(set(headers))!=len(headers): raise MacAXError('DUPLICATE_COLUMN_TITLE')
        declared=get(table,'AXRowCount')
        if declared is not None and (type(declared) is not int or declared!=len(rows)):
            raise MacAXError('DECLARED_ROW_COUNT_MISMATCH')
        declared_cols=get(table,'AXColumnCount')
        if declared_cols is not None and (type(declared_cols) is not int or declared_cols!=len(columns)):
            raise MacAXError('DECLARED_COLUMN_COUNT_MISMATCH')
        axes=[sequence(c,'AXRows') for c in columns]
        if any(len(axis)!=len(rows) for axis in axes): raise MacAXError('COLUMN_ROW_COUNT_MISMATCH')
        data=[]
        for i,row in enumerate(rows):
            fields=many(row,['AXIndex','AXChildren'])
            index=fields['AXIndex']
            if type(index) is not int or index!=i: raise MacAXError('ROW_INDEX_MISMATCH')
            cells=fields['AXChildren']
            if not isinstance(cells,(list,tuple)):raise MacAXError('TABLE_ARRAY_UNAVAILABLE:AXChildren')
            if len(cells)!=len(columns): raise MacAXError('ROW_COLUMN_WIDTH_MISMATCH')
            values=[]
            for j,cell in enumerate(cells):
                if backend.key(cell)!=backend.key(axes[j][i]): raise MacAXError('ROW_COLUMN_REFERENCE_MISMATCH')
                fields=many(cell,['AXSubrole','AXRole'])
                if fields['AXSubrole']=='AXSecureTextField': raise MacAXError('SECURE_TABLE_CELL')
                if fields['AXRole']=='AXCell':
                    nested=sequence(cell,'AXChildren')
                    if len(nested)!=1:raise MacAXError('AMBIGUOUS_NESTED_TABLE_CELL')
                    text=nested[0]
                    nested_fields=many(text,['AXSubrole','AXRole'])
                    if nested_fields['AXSubrole']=='AXSecureTextField':raise MacAXError('SECURE_TABLE_CELL')
                    if nested_fields['AXRole']!='AXStaticText':raise MacAXError('UNSUPPORTED_NESTED_CELL_ROLE')
                    value=get(text,'AXValue')
                elif fields['AXRole']=='AXStaticText':value=get(cell,'AXValue')
                else:raise MacAXError('UNSUPPORTED_TABLE_CELL_ROLE')
                if not isinstance(value,str): raise MacAXError('TABLE_CELL_VALUE_UNAVAILABLE')
                values.append(value)
            data.append(values)
        # Report native exposed shape only; no application/business interpretation.
        end_rows=sequence(table,'AXRows')
        if [backend.key(r) for r in end_rows]!=[backend.key(r) for r in rows]:
            raise MacAXError('ROW_SET_CHANGED_DURING_READ')
        return headers,data
    first=sample(); second=sample()
    if first!=second: raise MacAXError('TABLE_CHANGED_BETWEEN_READS')
    check()
    headers,matrix=first
    canonical=json.dumps({'headers':headers,'matrix':matrix},ensure_ascii=False,separators=(',',':')).encode()
    return {'status':'READ_OK',
            'captured_at':datetime.now(timezone.utc).isoformat(), 'headers':headers,
            'rows':[dict(zip(headers,row)) for row in matrix], 'row_count':len(matrix),
            'column_count':len(headers),'row_column_crosscheck':True,'stable_double_read':True,
            'completeness_scope':'AX_EXPOSED_ROWS_ONLY',
            'sha256':hashlib.sha256(canonical).hexdigest(),'elapsed_seconds':time.monotonic()-start}
