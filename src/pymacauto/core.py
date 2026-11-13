"""Lazy, unambiguous AX locators. No focus, event injection or pixel fallback."""
from collections import deque
import copy
import math
import re
import time

from .errors import (AmbiguousMatch, AttributeUnsupported, ElementNotFound,
                     PermissionDenied, SearchLimitExceeded, UnsafeOperation,
                     VerificationFailed, WaitTimeout,LayoutChanged)

FIELDS = {'role': 'AXRole', 'subrole': 'AXSubrole', 'title': 'AXTitle',
          'value': 'AXValue', 'identifier': 'AXIdentifier',
          'description': 'AXDescription', 'help': 'AXHelp', 'enabled': 'AXEnabled'}


from .validation import validate_pid


def _positive(value, name, integer=False, zero=False):
    try:
        finite = isinstance(value, int) if integer else math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not finite or value < 0 or (not zero and value == 0)
            or (integer and not isinstance(value, int))):
        raise ValueError(f'{name} must be a finite {"integer" if integer else "number"} '
                         f'{">=" if zero else ">"} 0')
    return value


def _get(backend, ref, name):
    if name == 'AXValue':
        try:
            secure = backend.get(ref, 'AXSubrole') == 'AXSecureTextField'
        except AttributeUnsupported:
            secure = False
        if secure:
            raise UnsafeOperation('Secure field values are not exposed')
    try:
        return backend.get(ref, name)
    except AttributeUnsupported:
        return None


def _selector(criteria):
    if not criteria:
        raise ValueError('At least one selector is required')
    for key, value in criteria.items():
        field = key.removesuffix('_re')
        if field not in FIELDS or (key.endswith('_re') and field == 'enabled'):
            raise ValueError(f'Unknown selector: {key}')
        if key.endswith('_re'):
            re.compile(value)
        elif field == 'enabled':
            if not isinstance(value, bool):
                raise ValueError('enabled must be boolean')
        elif field == 'value':
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError('value selector must be scalar')
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('value must be finite')
        elif not isinstance(value, str):
            raise ValueError(f'{key} must be a string')
    return dict(criteria)


def _path_step(selector,*,relation='child',index=None,expected_count=None,verify=None):
    if relation not in ('child','descendant','window'):raise ValueError('Unknown path relation')
    if not isinstance(selector,dict) or (verify is not None and not isinstance(verify,dict)):raise ValueError('Selector and verify must be objects')
    if index is not None:_positive(index,'index',integer=True,zero=True)
    if expected_count is not None:_positive(expected_count,'expected_count',integer=True,zero=True)
    if index is not None and expected_count is not None and index>=expected_count:
        raise ValueError('index must be less than expected_count')
    return {'$path':True,'relation':relation,'selector':_selector(selector),'index':index,
            'expected_count':expected_count,'verify':_selector(verify) if verify is not None else None}


def _json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else '<non-finite>'
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return '<AX reference>'


def _value_equal(actual, expected):
    # AX numbers can bridge as int or float, but booleans are not numbers.
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    return actual == expected


def _matches(backend, ref, criteria):
    for key, expected in criteria.items():
        actual = _get(backend, ref, FIELDS[key.removesuffix('_re')])
        if key.endswith('_re'):
            if not isinstance(actual, str) or re.search(expected, actual) is None:
                return False
        elif not _value_equal(actual, expected):
            return False
    return True


class Application:
    def __init__(self, backend, info, max_nodes=5000, max_depth=40):
        self.backend, self.info = backend, dict(info)
        self.max_nodes = _positive(max_nodes, 'max_nodes', integer=True)
        self.max_depth = _positive(max_depth, 'max_depth', integer=True, zero=True)
        self.pid = self.info['pid']
        self._root = backend.root(self.pid)

    @classmethod
    def connect(cls, *, pid=None, bundle_id=None, name=None, backend=None,
                max_nodes=5000, max_depth=40):
        if sum(x is not None for x in (pid, bundle_id, name)) != 1:
            raise ValueError('Provide exactly one of pid, bundle_id, name')
        if pid is not None:
            validate_pid(pid)
        for value in (bundle_id, name):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError('App selector must be a nonempty string')
        if backend is None:
            from .native import NativeBackend
            backend = NativeBackend()
        if not backend.trusted():
            raise PermissionDenied('Grant Accessibility access to this Python/terminal in System Settings; no permission dialog was opened')
        key, value = ('pid', pid) if pid is not None else (('bundle_id', bundle_id) if bundle_id is not None else ('name', name))
        found = [a for a in backend.apps() if a.get(key) == value]
        if not found and pid is not None:
            # Directly launched AppKit/accessory apps can expose AX without
            # appearing in NSWorkspace. Native root() validates the live PID.
            found = [{'pid': pid, 'name': None, 'bundle_id': None}]
        if not found:
            raise ElementNotFound(f'No running application matching {key}={value!r}')
        if len(found) != 1:
            raise AmbiguousMatch(f'{len(found)} applications match {key}={value!r}; use pid')
        return cls(backend, found[0], max_nodes, max_depth)

    @staticmethod
    def list_apps():
        from .native import NativeBackend
        return NativeBackend().apps()

    @staticmethod
    def is_trusted(*, prompt=False):
        from .native import NativeBackend
        return NativeBackend().trusted(prompt=prompt)

    def windows(self):
        refs=self.backend.get(self._root,'AXWindows')
        if not isinstance(refs,(list,tuple)):
            raise ElementNotFound('AXWindows unavailable')
        return [Element(self,ref) for ref in refs]

    def session(self,*,journal=None,profile=None,stop=None,readonly=False,**window):
        from .operations import OperationSession
        return OperationSession(self,window=window,journal=journal,profile=profile,stop=stop,readonly=readonly)

    def inspect(self,**limits):
        from .inspector import inspect_application
        return inspect_application(self,**limits)

    def _walk(self, root, include_root=False):
        queue = deque([(root, 0)])
        seen = set()
        count = 0
        while queue:
            ref, depth = queue.popleft()
            key = self.backend.key(ref)
            if key in seen:
                continue
            seen.add(key)
            count += 1
            if count > self.max_nodes:
                raise SearchLimitExceeded(f'AX tree exceeds {self.max_nodes} nodes; narrow the search')
            if include_root or depth:
                yield ref, depth
            children = _get(self.backend, ref, 'AXChildren') or []
            if depth >= self.max_depth:
                if any(self.backend.key(child) not in seen for child in children):
                    raise SearchLimitExceeded(f'AX tree exceeds depth {self.max_depth}; narrow the search')
            else:
                queue.extend((child, depth + 1) for child in children)

    def child_window(self, **criteria):
        return Locator(self, (_selector(criteria),))

    def window(self, **criteria):
        if 'role' in criteria and criteria['role'] != 'AXWindow':
            raise ValueError('window() requires AXWindow')
        return self.child_window(**{**criteria, 'role': 'AXWindow'})

    def locator_path(self,steps):
        if not isinstance(steps,(list,tuple)) or not steps:raise ValueError('Nonempty path required')
        if len(steps)>self.max_depth:raise SearchLimitExceeded('Locator path depth budget')
        chain=[]
        for step in steps:
            if not isinstance(step,dict) or not {'relation','selector'}<=set(step) or set(step)-{'relation','selector','index','expected_count','verify'}:
                raise ValueError('Path step requires relation/selector and known optional fields')
            if not isinstance(step['selector'],dict):raise ValueError('Path selector must be an object')
            chain.append(_path_step(**step))
        return Locator(self,tuple(chain))

    def child(self,*,index=None,expected_count=None,verify=None,**criteria):
        return Locator(self,(_path_step(criteria,index=index,expected_count=expected_count,verify=verify),))

    def descendants(self, **criteria):
        if criteria:
            criteria = _selector(criteria)
        return [Element(self, ref) for ref, _ in self._walk(self._root)
                if not criteria or _matches(self.backend, ref, criteria)]

    def dump_tree(self):
        # Materialize before returning: never silently publish a truncated search.
        return [dict(depth=depth, **Element(self, ref).info())
                for ref, depth in self._walk(self._root, include_root=True)]


class Locator:
    def __init__(self, app, chain, root=None):
        self.app, self.chain, self.root = app, copy.deepcopy(chain), root

    def child_window(self, **criteria):
        return Locator(self.app, self.chain + (_selector(criteria),), self.root)

    def child(self,*,index=None,expected_count=None,verify=None,**criteria):
        return Locator(self.app,self.chain+(_path_step(criteria,index=index,expected_count=expected_count,verify=verify),),self.root)

    def resolve(self):
        root = self.app._root if self.root is None else (self.root() if callable(self.root) else self.root)
        for criteria in self.chain:
            step=criteria if criteria.get('$path') is True else None
            selector=step['selector'] if step else criteria
            if step and step['relation'] in ('child','window'):
                if step['relation']=='window' and self.app.backend.key(root)!=self.app.backend.key(self.app._root):
                    raise ValueError('window relation only allowed at application root')
                refs=self.app.backend.get(root,'AXWindows' if step['relation']=='window' else 'AXChildren')
                if not isinstance(refs,(list,tuple)):raise ElementNotFound('Path relation unavailable')
                if len(refs)>self.app.max_nodes:raise SearchLimitExceeded('Path children node budget')
                seen=set();candidates=[]
                for ref in refs:
                    key=self.app.backend.key(ref)
                    if key not in seen:seen.add(key);candidates.append(ref)
            else:candidates=[ref for ref,_ in self.app._walk(root)]
            matches=[ref for ref in candidates if _matches(self.app.backend,ref,selector)]
            if step:
                count=step['expected_count']
                if count is not None and len(matches)!=count:raise LayoutChanged('Path sibling count changed')
                index=step['index']
                if index is not None:
                    if index>=len(matches):raise ElementNotFound('Path index out of range')
                    matches=[matches[index]]
                if len(matches)==1 and step['verify'] is not None and not _matches(self.app.backend,matches[0],step['verify']):
                    raise LayoutChanged('Indexed target fingerprint mismatch')
            if not matches:
                raise ElementNotFound(f'No AX element matches {criteria!r}')
            if len(matches) != 1:
                raise AmbiguousMatch(f'{len(matches)} AX elements match {criteria!r}; narrow the selector')
            root = matches[0]
        return Element(self.app, root)

    def exists(self):
        try:
            self.resolve()
            return True
        except ElementNotFound:
            return False

    def wait(self, *, timeout=5.0, interval=0.1, state='exists', **criteria):
        _positive(timeout, 'timeout', zero=True)
        _positive(interval, 'interval')
        if state not in ('exists', 'gone') or (state == 'gone' and criteria):
            raise ValueError('state must be exists or gone; gone accepts no criteria')
        if criteria:
            criteria = _selector(criteria)
        deadline = time.monotonic() + timeout
        while True:
            try:
                element = self.resolve()
            except ElementNotFound:
                element = None
            if state == 'gone' and element is None:
                return None
            if state == 'exists' and element is not None:
                if not criteria or _matches(self.app.backend, element.ref, criteria):
                    return element
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeout(f'AX wait timed out after {timeout}s ({state})')
            time.sleep(min(interval, remaining))

    def inspect_children(self):
        from .locator_diagnostics import inspect_children
        return inspect_children(self)
    def explain(self):
        from .locator_diagnostics import explain_locator
        return explain_locator(self)
    def export(self):
        from .locator_diagnostics import export_locator
        return export_locator(self)

    def control(self):
        from .controls import Control
        return Control(self)

    def get_value(self): return self.resolve().get_value()
    def read_table(self,**limits): return self.resolve().read_table(**limits)
    def labelled_field(self,label,**layout): return self.resolve().labelled_field(label,**layout)
    def children(self,**criteria): return self.resolve().children(**criteria)
    def descendants(self,**criteria): return self.resolve().descendants(**criteria)
    def info(self): return self.resolve().info()
    def click(self): return self.resolve().click()
    def set_edit_text(self, text): return self.resolve().set_edit_text(text)
    def set_value(self, value, verify_timeout=2.0):
        return self.resolve().set_value(value, verify_timeout)
    def perform(self, action): return self.resolve().perform(action)


class Element:
    """A native reference, not an ordinal tree index. Re-resolve after UI changes."""
    def __init__(self, app, ref):
        self.app, self.ref, self.backend = app, ref, app.backend

    def child_window(self,**criteria):
        return Locator(self.app,(_selector(criteria),),self.ref)

    def child(self,*,index=None,expected_count=None,verify=None,**criteria):
        return Locator(self.app,(_path_step(criteria,index=index,expected_count=expected_count,verify=verify),),self.ref)

    def children(self,**criteria):
        if criteria: criteria=_selector(criteria)
        refs=_get(self.backend,self.ref,'AXChildren') or []
        if len(refs)>self.app.max_nodes:raise SearchLimitExceeded('Child query node budget')
        return [Element(self.app,r) for r in refs if not criteria or _matches(self.backend,r,criteria)]

    def descendants(self,**criteria):
        if criteria:criteria=_selector(criteria)
        return [Element(self.app,r) for r,_ in self.app._walk(self.ref)
                if not criteria or _matches(self.backend,r,criteria)]

    def labelled_field(self,label,**layout):
        from .fields import labelled_field
        return labelled_field(self.app,self.ref,label,**layout)

    def read_table(self,**limits):
        from .tables import read_table
        return read_table(self.backend,self.ref,**limits)

    def get_value(self):return self.get('AXValue')

    def get(self, attribute):
        if not isinstance(attribute, str) or not attribute.startswith('AX'):
            raise ValueError('Use a raw AX attribute name')
        if _get(self.backend, self.ref, 'AXSubrole') == 'AXSecureTextField':
            safe={'AXRole','AXSubrole','AXIdentifier','AXEnabled','AXPosition','AXSize'}
            if attribute not in safe:
                raise UnsafeOperation('Secure field content attributes are not exposed')
        return self.backend.get(self.ref, attribute)

    def info(self):
        secure = _get(self.backend, self.ref, 'AXSubrole') == 'AXSecureTextField'
        result = {key: (_get(self.backend, self.ref, attr) if not (secure and key == 'value') else '<redacted>')
                  for key, attr in FIELDS.items()}
        # Some AXValue properties are element references, not JSON values.
        result = {key: _json_value(value) for key, value in result.items()}
        result['actions'] = list(self.backend.actions(self.ref))
        return result

    def _writable(self):
        if _get(self.backend, self.ref, 'AXSubrole') == 'AXSecureTextField':
            raise UnsafeOperation('Refusing to automate secure text fields')
        if _get(self.backend, self.ref, 'AXEnabled') is False:
            raise UnsafeOperation('Element is disabled')

    def perform(self, action):
        self._writable()
        if not isinstance(action, str) or action not in self.backend.actions(self.ref):
            raise UnsafeOperation(f'Element does not expose action {action!r}')
        self.backend.perform(self.ref, action)
        # AX success acknowledges dispatch, not the application-specific outcome.
        return {'action': action, 'effect': 'unverifiable', 'verified': False}

    def click(self):
        return self.perform('AXPress')

    def set_edit_text(self, text):
        if not isinstance(text, str):
            raise ValueError('text must be a string')
        return self.set_value(text)

    def set_value(self, value, verify_timeout=2.0):
        if not isinstance(value, (str, bool, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError('AXValue must be a finite JSON scalar')
        _positive(verify_timeout, 'verify_timeout', zero=True)
        self._writable()
        self.backend.set(self.ref, 'AXValue', value)
        deadline = time.monotonic() + verify_timeout
        while True:
            if _value_equal(self.backend.get(self.ref, 'AXValue'), value):
                return {'action': 'AXSetValue', 'effect': 'confirmed', 'verified': True}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationFailed('AXSetValue dispatched but AX read-back differs; do not blindly retry')
            time.sleep(min(0.05, remaining))
