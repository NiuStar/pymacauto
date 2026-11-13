"""Named, window-relative convenience over protected operations.

No native references, focus changes, inferred controls, or input retries.
"""
import copy

from .errors import UnsafeOperation
from .journal import canonical
from .operations import Condition, OperationSession


class Automation:
    def __init__(self, app, profile, *, journal=None, stop=None, pages=None):
        self.app, self.profile = app, profile
        self._closed = False
        profile.require(app)
        self._config = copy.deepcopy(profile.config)
        self._config_bytes, self._profile_sha256 = canonical(self._config), profile.sha256
        self.operations = OperationSession(app, window=self._config['window'],
                                           profile=profile, journal=journal, stop=stop)
        self._pages = None
        self._pages_config = None
        try:
            if pages is not None:
                from .pages import PageSession
                self._pages = PageSession.from_config(app, copy.deepcopy(pages), operations=self.operations)
                self._pages_config = canonical(self._pages.configuration())
        except BaseException:
            self.close()
            raise

    def _check_open(self):
        if self._closed or self.operations._closed:
            raise UnsafeOperation('Automation closed')
        try:
            unchanged = (canonical(self.profile.config) == self._config_bytes and
                         canonical(self._config) == self._config_bytes and
                         self.profile.sha256 == self._profile_sha256 and
                         self.operations.window == self._config['window'] and
                         self.operations.app is self.app and self.operations.profile is self.profile and
                         (self._pages is None or (
                             self._pages.operations is self.operations and self._pages.app is self.app and
                             canonical(self._pages.configuration()) == self._pages_config)))
        except (TypeError, ValueError, RecursionError):
            unchanged = False
        if not unchanged:
            raise UnsafeOperation('Profile changed after qualification')

    def __enter__(self):
        try:
            self._check_open()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._closed:
            self._closed = True
            self.operations.close()

    def control(self, name):
        self._check_open()
        if name not in self._config['controls']:
            raise ValueError('Unknown control')
        spec = self._config['controls'][name]
        steps = [{'relation': 'window', 'selector': self._config['window']}]
        steps += spec['path'] if 'path' in spec else [{'relation': 'descendant', 'selector': spec}]
        return NamedControl(self, self.app.locator_path(steps))

    def page(self, name):
        self._check_open()
        if self._pages is None or name not in self._pages.pages:
            raise ValueError('Unknown page')
        return NamedPage(self, name)

    def condition(self, name, **criteria):
        return Condition(self.control(name).locator, **criteria)


class NamedPage:
    def __init__(self, automation, name):
        self._automation, self.name = automation, name

    def ensure(self, *, timeout=5, operation_id=None):
        self._automation._check_open()
        return self._automation._pages.switch(self.name, timeout=timeout, operation_id=operation_id)


class NamedControl:
    def __init__(self, automation, locator):
        self._automation, self.locator = automation, locator

    def click(self, *, expect, operation_id=None, timeout=5):
        self._automation._check_open()
        if not isinstance(expect, Condition):
            raise ValueError('Explicit Condition required')
        return self._automation.operations.execute(self.locator, postcondition=expect,
                                                    operation_id=operation_id, timeout=timeout)

    def fill(self, value, *, operation_id=None, timeout=5):
        self._automation._check_open()
        return self._automation.operations.apply(self.locator, 'fill', value=value,
                                                  operation_id=operation_id, timeout=timeout)

    def check(self, checked, *, operation_id=None, timeout=5):
        self._automation._check_open()
        return self._automation.operations.apply(self.locator, 'check', value=checked,
                                                  operation_id=operation_id, timeout=timeout)

    def read_table(self, **limits):
        self._automation._check_open()
        return self.locator.read_table(**limits)

    def read(self):
        self._automation._check_open()
        return self.locator.get_value()
