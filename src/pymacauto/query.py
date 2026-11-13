"""Fresh bounded structural queries with explicit subtree boundaries."""
from collections import deque
from .core import Element, _get, _matches, _selector, _required_get
from .errors import AmbiguousMatch,ElementNotFound,SearchLimitExceeded


class QueryScope:
    """No persistent element index/cache. leaf_roles defines search scope only.

    Matching nodes at a leaf boundary are included; their descendants are not.
    Use a separate non-pruned scope when searching inside tables/lists.
    """
    def __init__(self,app,root,*,leaf_roles=()):
        self.app,self.root=app,root
        leaf_roles=tuple(leaf_roles)
        self.leaf_roles=frozenset(leaf_roles)
        if any(not isinstance(role,str) or not role.startswith('AX') for role in leaf_roles):
            raise ValueError('leaf_roles requires raw AX role names')

    def walk(self):
        b=self.app.backend
        from .query_context import active_context
        evidence=active_context(b)
        queue=deque([(self.root,0)]);seen=set()
        while queue:
            ref,depth=queue.popleft();key=b.key(ref)
            if key in seen:continue
            seen.add(key)
            if len(seen)>self.app.max_nodes:raise SearchLimitExceeded('Structural query node budget')
            if evidence is not None and evidence.guard:evidence.prefetch(ref,('AXRole','AXSheets','AXModal'))
            role=_get(b,ref,'AXRole')
            yield ref,role
            if role in self.leaf_roles:continue
            children=_get(b,ref,'AXChildren') or []
            if depth>=self.app.max_depth:
                if any(b.key(c) not in seen for c in children):
                    raise SearchLimitExceeded('Structural query depth budget')
            else:queue.extend((c,depth+1) for c in children)

    def find_all(self,**criteria):
        criteria=_selector(criteria)
        found=[]
        for ref,role in self.walk():
            # Reuse this query's freshly read role, never cross-query cache.
            if 'role' in criteria and role!=criteria['role']:continue
            remaining={k:v for k,v in criteria.items() if k!='role'}
            if not remaining or _matches(self.app.backend,ref,remaining):found.append(Element(self.app,ref))
        return found

    def find(self,**criteria):
        found=self.find_all(**criteria)
        if not found:raise ElementNotFound(f'No structural match: {criteria!r}')
        if len(found)!=1:raise AmbiguousMatch(f'{len(found)} structural matches: {criteria!r}')
        return found[0]


def window_scope(app,*,leaf_roles=(),**criteria):
    """Resolve unique top-level window through AXWindows, not entire app tree."""
    criteria=_selector({'role':'AXWindow',**criteria})
    windows=_required_get(app.backend,app._root,'AXWindows')
    if not isinstance(windows,(list,tuple)):raise ElementNotFound('AXWindows unavailable')
    found=[w for w in windows if _matches(app.backend,w,criteria)]
    if not found:raise ElementNotFound('Window not found')
    if len(found)!=1:raise AmbiguousMatch('Window selector is ambiguous')
    return QueryScope(app,found[0],leaf_roles=leaf_roles)
