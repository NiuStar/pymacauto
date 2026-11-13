"""Caller-configured page matching/navigation; no application/business schema."""
import time
import copy
from .core import _positive, _matches, _selector, Locator, Element
from .operations import Condition,OperationSession
from .query import window_scope, QueryScope
from .tables import optional
from .errors import AXError,ElementNotFound,AmbiguousMatch,WaitTimeout,MacAXError


def table_headers(backend,table):
    columns=backend.get(table,'AXColumns')
    if not isinstance(columns,(list,tuple)):raise MacAXError('AXColumns unavailable')
    headers=[]
    for col in columns:
        header=backend.get(col,'AXHeader')
        if header is None:raise MacAXError('Table header unavailable')
        title=backend.get(header,'AXTitle')
        if not isinstance(title,str):raise MacAXError('Table header title unavailable')
        headers.append(title)
    return headers


class PageCondition(Condition):
    """Independent observed page fingerprint; descriptor binds full config."""
    def __init__(self,session,page):
        super().__init__(session.app.child_window(role='AXTable'))
        self.session,self.page=session,page
        self._configuration=session.configuration()
    def describe(self):
        return {'kind':'page','page':self.page,'configuration':copy.deepcopy(self._configuration)}
    def check(self):
        if self.session.configuration()!=self._configuration:
            from .errors import UnsafeOperation
            raise UnsafeOperation('Page configuration changed during operation')
        try:
            observed=self.session.detect()['page']
            return self.page is None or observed==self.page
        except ElementNotFound:return False
        except AXError as exc:
            if exc.code not in (-25201,-25202,-25204):raise
            self.session.read_errors.append({'operation':exc.operation,'code':exc.code})
            return False


class PageTrigger(Locator):
    def __init__(self,session,page):
        super().__init__(session.app,(session.pages[page]['trigger'],))
        self.session,self.page=session,page
        self.descriptor={'kind':'page_trigger','page':page,'configuration':session.configuration()}
    def resolve(self):
        if self.session.configuration()!=self.descriptor['configuration']:
            from .errors import UnsafeOperation
            raise UnsafeOperation('Page trigger configuration changed during operation')
        result=self.session.detect(trigger=self.page)
        if 'trigger' not in result:raise ElementNotFound('No page change required')
        return Element(self.app,result['trigger'])


class PageSession:
    """Fresh window scope each query; explicit pruning does not cover data nodes.

    Caller supplies page selectors and header fingerprints. No references are
    persisted across switches; only read-only discovery is retried on rebuild.
    """
    def __init__(self,app,*,window,pages,leaf_roles=('AXTable','AXList','AXOutline'),
                 content_path=None,trigger_children_only=False,operations=None):
        if not isinstance(window,dict):raise ValueError('window must be a selector object')
        window=_selector(window)
        if not isinstance(pages,dict) or not pages:raise ValueError('pages must be a nonempty object')
        validated={}
        for name,page in pages.items():
            if not isinstance(name,str) or not name or not isinstance(page,dict):
                raise ValueError('Each page must have a nonempty name and object configuration')
            if set(page)!={'trigger','table','headers'}:raise ValueError('Page requires only trigger, table, headers')
            if not isinstance(page['trigger'],dict) or not isinstance(page['table'],dict):
                raise ValueError('Page trigger and table must be selector objects')
            headers=page['headers']
            if not isinstance(headers,(list,tuple)) or not headers or not all(isinstance(h,str) and h for h in headers):
                raise ValueError('Each page needs nonempty string header fingerprints')
            if len(set(headers))!=len(headers):raise ValueError('Page headers must be distinct')
            validated[name]={'trigger':_selector(page['trigger']),'table':_selector(page['table']),'headers':tuple(headers)}
        if not isinstance(leaf_roles,(list,tuple)) or not all(isinstance(r,str) and r for r in leaf_roles):
            raise ValueError('leaf_roles must be a list of nonempty role strings')
        self.app,self.window,self.pages=app,window,validated
        self.leaf_roles=tuple(leaf_roles);self.read_errors=[]
        if content_path is not None and not isinstance(content_path,(list,tuple)):
            raise ValueError('content_path must be a selector sequence')
        if content_path is not None and len(content_path)>app.max_depth:
            from .errors import SearchLimitExceeded
            raise SearchLimitExceeded('Content path depth budget')
        if content_path is not None and any(not isinstance(c,dict) for c in content_path):
            raise ValueError('content_path entries must be selector objects')
        if any(not r.startswith('AX') for r in leaf_roles):raise ValueError('leaf_roles requires AX role names')
        if 'role' in window and window['role']!='AXWindow':raise ValueError('window requires AXWindow role')
        self.content_path=None if content_path is None else [_selector(c) for c in content_path]
        if type(trigger_children_only) is not bool:raise ValueError('trigger_children_only must be bool')
        self.trigger_children_only=trigger_children_only
        if operations is not None and (operations.app is not app or operations.window!=window):
            raise ValueError('Page operations must use the same app/window')
        self.operations=operations
        self.last_receipt=None

    @classmethod
    def from_config(cls,app,config,*,operations=None):
        if not isinstance(config,dict):raise ValueError('Page configuration must be an object')
        allowed={'window','pages','content_path','trigger_children_only','leaf_roles'}
        if set(config)-allowed:raise ValueError('Unknown page configuration fields')
        if 'window' not in config or 'pages' not in config:raise ValueError('window and pages required')
        if not isinstance(config['window'],dict) or not isinstance(config['pages'],dict) or not config['pages']:
            raise ValueError('window and nonempty pages must be objects')
        return cls(app,**config,operations=operations)

    def configuration(self):
        return copy.deepcopy({'window':self.window,'pages':self.pages,'leaf_roles':self.leaf_roles,
                              'content_path':self.content_path,'trigger_children_only':self.trigger_children_only})

    def scope(self):return window_scope(self.app,leaf_roles=self.leaf_roles,**self.window)

    def direct_matches(self,root,selector):
        children=self.app.backend.get(root,'AXChildren')
        if not isinstance(children,(list,tuple)):raise ElementNotFound('Direct children unavailable')
        if len(children)>self.app.max_nodes:
            from .errors import SearchLimitExceeded
            raise SearchLimitExceeded('Direct child query node budget')
        seen=set();found=[]
        for ref in children:
            key=self.app.backend.key(ref)
            if key in seen:continue
            seen.add(key)
            if _matches(self.app.backend,ref,selector):found.append(ref)
        return found

    def detect(self,*,trigger=None):
        if trigger is not None and trigger not in self.pages:raise ValueError('Unknown trigger page')
        scope=self.scope();matches=[];triggers=[]
        window_root=scope.root
        if self.content_path is not None:
            root=window_root
            for selector in self.content_path:
                found=self.direct_matches(root,selector)
                if len(found)>1:raise AmbiguousMatch('Content path is ambiguous')
                if not found:raise ElementNotFound('Content path unavailable')
                root=found[0]
            scope=QueryScope(self.app,root,leaf_roles=self.leaf_roles)
        if trigger is not None and self.trigger_children_only:
            triggers=self.direct_matches(window_root,self.pages[trigger]['trigger'])
        for ref,role in scope.walk():
            trigger_selector=self.pages[trigger]['trigger'] if trigger is not None else None
            if not self.trigger_children_only and trigger_selector is not None and ('role' not in trigger_selector or role==trigger_selector['role']) and _matches(
                    self.app.backend,ref,{k:v for k,v in trigger_selector.items() if k!='role'}):
                triggers.append(ref)
            if role!='AXTable':continue
            identifier=optional(self.app.backend,ref,'AXIdentifier')
            candidates=[(name,p) for name,p in self.pages.items()
                        if ('identifier' not in p['table'] or p['table']['identifier']==identifier)
                        and _matches(self.app.backend,ref,p['table'])]
            if not candidates:continue
            headers=table_headers(self.app.backend,ref)
            for name,p in candidates:
                if set(p['headers'])<=set(headers):matches.append((name,ref,headers))
        if len(matches)>1:raise AmbiguousMatch('Multiple page fingerprints matched')
        if not matches:raise ElementNotFound('No configured page fingerprint matched')
        name,ref,headers=matches[0]
        result={'page':name,'table':ref,'headers':headers}
        if trigger is not None and name!=trigger:
            if len(triggers)>1:raise AmbiguousMatch('Multiple page triggers matched')
            if not triggers:raise ElementNotFound('Page trigger unavailable')
            result['trigger']=triggers[0]
        return result

    def wait(self,page=None,*,timeout=5,interval=.01,trigger=None):
        _positive(timeout,'timeout',zero=True);_positive(interval,'interval')
        if page is not None and page not in self.pages:raise ValueError('Unknown page')
        if trigger is not None and trigger not in self.pages:raise ValueError('Unknown trigger page')
        deadline=time.monotonic()+timeout
        while True:
            try:
                result=self.detect(trigger=trigger)
                if page is None or result['page']==page:return result
            except ElementNotFound:pass
            except AXError as exc:
                if exc.code not in (-25201,-25202,-25204):raise
                self.read_errors.append({'operation':exc.operation,'code':exc.code})
            remaining=deadline-time.monotonic()
            if remaining<=0:raise WaitTimeout('Page target not observed')
            time.sleep(min(interval,remaining))

    def switch(self,page,*,timeout=5,operation_id=None):
        if page not in self.pages:raise ValueError('Unknown page')
        _positive(timeout,'timeout',zero=True)
        started=time.monotonic()
        current=self.wait(timeout=timeout,trigger=page)
        if self.operations is not None:self.operations._check_stop()
        if current['page']==page:
            if self.operations is not None and operation_id is not None:
                previous=self.operations.remember_observation(PageTrigger(self,page),postcondition=PageCondition(self,page),
                    precondition=PageCondition(self,None),operation_id=operation_id)
                if previous is not None:
                    self.last_receipt=previous
                    if not previous.get('verified') and not (previous.get('observed') and previous.get('status')=='NOT_DISPATCHED'):
                        from .errors import UnsafeOperation
                        raise UnsafeOperation('Earlier page operation uncertain; observe/reconcile without replay')
                    return {**current,'receipt':previous}
            self.last_receipt={'status':'ALREADY_OBSERVED','verified':True,'dispatch_attempted':False}
            return {**current,'receipt':self.last_receipt}
        if timeout>0 and time.monotonic()-started>=timeout:raise WaitTimeout('Page total budget exhausted before dispatch')
        owner=self.operations or OperationSession(self.app,window=self.window)
        try:
            receipt=owner.execute(PageTrigger(self,page),
                precondition=PageCondition(self,None),postcondition=PageCondition(self,page),
                operation_id=operation_id,timeout=max(0,timeout-(time.monotonic()-started)))
            self.last_receipt=receipt
        finally:
            if self.operations is None:owner.close()
        if not receipt['verified']:
            native=receipt.get('native_error')
            if native:raise AXError(native['operation'],native['code'])
            if receipt['status']=='NOT_DISPATCHED':
                from .errors import UnsafeOperation
                raise UnsafeOperation('Protected page switch not dispatched: '+str(receipt.get('error')))
            raise WaitTimeout('Protected page target unconfirmed; do not repeat input')
        result=self.detect()
        if result['page']!=page:raise WaitTimeout('Page changed after confirmation')
        return {**result,'receipt':receipt}
