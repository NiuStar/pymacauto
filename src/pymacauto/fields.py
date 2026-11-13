"""Explicit label-relative AX field lookup, no pixel input or child ordinals."""
import math
from .core import Element, _get, _positive
from .errors import ElementNotFound, AmbiguousMatch, UnsafeOperation,SearchLimitExceeded


def labelled_field(app,root,label,*,alignment_tolerance=8,max_gap=220):
    """Caller-selected direct-child container; same-row right-of-label policy.

    This is a geometry-assisted AX locator, not a semantic association supplied
    by the app. Fail on absent/ambiguous labels or fields; re-resolve each write.
    """
    if not isinstance(label,str) or not label:raise ValueError('Nonempty label required')
    _positive(alignment_tolerance,'alignment_tolerance',zero=True)
    _positive(max_gap,'max_gap')
    b=app.backend
    children=b.get(root,'AXChildren')
    if not isinstance(children,(list,tuple)):raise ElementNotFound('No child array')
    if len(children)>app.max_nodes:raise SearchLimitExceeded('Field search budget')
    labels=[];fields=[];seen=set()
    for ref in children:
        key=b.key(ref)
        if key in seen:continue
        seen.add(key)
        role=_get(b,ref,'AXRole')
        if role=='AXStaticText':
            if _get(b,ref,'AXValue')==label or _get(b,ref,'AXTitle')==label:labels.append(ref)
        elif role=='AXTextField':fields.append(ref)
    if not labels:raise ElementNotFound('Label missing')
    if len(labels)!=1:raise AmbiguousMatch('Label is ambiguous')
    def bounds(ref):
        pos=_get(b,ref,'AXPosition');size=_get(b,ref,'AXSize')
        if not isinstance(pos,dict) or not isinstance(size,dict):raise ElementNotFound('Field geometry unavailable')
        values=(pos.get('x'),pos.get('y'),size.get('width'),size.get('height'))
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ElementNotFound('Invalid field geometry')
        if values[2]<=0 or values[3]<=0:raise ElementNotFound('Invalid field dimensions')
        return values
    x,y,w,h=bounds(labels[0]);matches=[]
    for ref in fields:
        fx,fy,fw,fh=bounds(ref)
        gap=fx-(x+w)
        if 0<=gap<=max_gap and abs((fy+fh/2)-(y+h/2))<=alignment_tolerance:
            matches.append(ref)
    if not matches:raise ElementNotFound('No aligned field')
    if len(matches)!=1:raise AmbiguousMatch('Multiple aligned fields')
    ref=matches[0]
    if _get(b,ref,'AXSubrole')=='AXSecureTextField':raise UnsafeOperation('Secure field blocked')
    if _get(b,ref,'AXEnabled') is not True:raise UnsafeOperation('Field not explicitly enabled')
    if not b.is_settable(ref,'AXValue'):raise UnsafeOperation('Field value not writable')
    return Element(app,ref)
