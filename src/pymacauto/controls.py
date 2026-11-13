"""Small role-checked control helpers; no keyboard or coordinate fallback."""
import math
import time
from .core import _get,_positive,_value_equal
from .errors import UnsafeOperation,VerificationFailed


class Control:
    """Wrap a fresh Locator (recommended), or an explicitly held Element."""
    def __init__(self,target,*,before_input=None):self.target=target;self.before_input=before_input
    def _input(self,element,callback):
        if self.before_input is not None:self.before_input()
        return callback()
    def element(self):return self.target.resolve() if hasattr(self.target,'resolve') else self.target
    def _role(self,roles,*,require_enabled=True):
        e=self.element();e._writable()
        if _get(e.backend,e.ref,'AXRole') not in roles:raise UnsafeOperation('Unsupported control role')
        if require_enabled and _get(e.backend,e.ref,'AXEnabled') is not True:raise UnsafeOperation('Control not explicitly enabled')
        return e
    def _verify(self,attribute,value,timeout,*,check_state=False):
        _positive(timeout,'timeout',zero=True);deadline=time.monotonic()+timeout
        while True:
            actual=self.element().get(attribute)
            equal=(type(actual) in (int,bool) and actual in (0,1) and bool(actual)==bool(value)) if check_state else _value_equal(actual,value)
            if equal:
                return {'verified':True,'attribute':attribute}
            remaining=deadline-time.monotonic()
            if remaining<=0:raise VerificationFailed('Control input dispatched but state unconfirmed; do not retry blindly')
            time.sleep(min(.03,remaining))
    def set_checked(self,checked,*,timeout=2):
        if type(checked) is not bool:raise ValueError('checked must be bool')
        _positive(timeout,'timeout',zero=True)
        e=self._role(('AXCheckBox','AXRadioButton'))
        value=e.get_value()
        if type(value) not in (int,bool) or value not in (0,1):raise UnsafeOperation('Unknown/mixed check state')
        if _get(e.backend,e.ref,'AXRole')=='AXRadioButton' and not checked:
            raise UnsafeOperation('Select another radio; do not toggle selected radio off')
        if bool(value)!=checked:self._input(e,e.click)
        return self._verify('AXValue',int(checked),timeout,check_state=True)
    def select(self,*,timeout=2):
        _positive(timeout,'timeout',zero=True)
        e=self._role(('AXRadioButton','AXRow','AXCell'),require_enabled=False)
        if _get(e.backend,e.ref,'AXRole')=='AXRadioButton':return self.set_checked(True,timeout=timeout)
        if not e.backend.is_settable(e.ref,'AXSelected'):raise UnsafeOperation('Selection not writable')
        self._input(e,lambda:e.backend.set(e.ref,'AXSelected',True))
        return self._verify('AXSelected',True,timeout)
    def set_numeric(self,value,*,timeout=2):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Finite numeric value required')
        _positive(timeout,'timeout',zero=True)
        e=self._role(('AXSlider','AXIncrementor'))
        low=e.get('AXMinValue');high=e.get('AXMaxValue')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (low,high)):
            raise UnsafeOperation('Numeric limits unavailable')
        if low>high or not low<=value<=high:raise ValueError('Value outside declared limits')
        if not e.backend.is_settable(e.ref,'AXValue'):raise UnsafeOperation('Value not writable')
        self._input(e,lambda:e.backend.set(e.ref,'AXValue',value))
        return self._verify('AXValue',value,timeout)
    def select_tab(self,title,*,timeout=2):
        if not isinstance(title,str) or not title:raise ValueError('Exact tab title required')
        _positive(timeout,'timeout',zero=True)
        e=self.element()
        if _get(e.backend,e.ref,'AXRole')!='AXTabGroup':raise UnsafeOperation('AXTabGroup required')
        tabs=e.get('AXTabs')
        if not isinstance(tabs,(list,tuple)):raise UnsafeOperation('Tab relation unavailable')
        matches=[r for r in tabs if _get(e.backend,r,'AXTitle')==title]
        if len(matches)!=1:raise UnsafeOperation('Tab title absent or ambiguous')
        from .core import Element
        return Control(Element(e.app,matches[0]),before_input=self.before_input).set_checked(True,timeout=timeout)

    def choose(self,title,*,timeout=2):
        if not isinstance(title,str) or not title:raise ValueError('Exact nonempty option title required')
        _positive(timeout,'timeout',zero=True)
        from .deadlines import Deadline
        budget=Deadline(timeout)
        e=self._role(('AXPopUpButton',))
        if e.get_value()==title:return {'verified':True,'attribute':'AXValue'}
        self._input(e,e.click)
        # Only the menu exposed under this control. Never search the app's
        # unrelated menus, pick the first duplicate, or retry opening it.
        item=e.child_window(role='AXMenuItem',title=title).wait(timeout=budget.remaining())
        if timeout>0:budget.require('menu_selection')
        self._input(item,item.click)
        return self._verify('AXValue',title,budget.remaining())
