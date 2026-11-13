"""Immutable selector specifications, without native references or query results."""
from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class SelectorPlan:
    """Compile with :func:`compile_selector`; descriptions retain selector order."""

    _description: tuple
    _predicates: tuple

    def matches(self, reader, ref):
        """Read in selector order, guarding every AXValue before requesting it."""
        from .core import _get, _value_equal

        # Do not batch: later attributes must stay unread after an earlier failure.
        for attr, expected, pattern in self._predicates:
            actual = _get(reader, ref, attr)
            if pattern is not None:
                if not isinstance(actual, str) or pattern.search(actual) is None:
                    return False
            elif not _value_equal(actual, expected):
                return False
        return True

    @property
    def description(self):
        """Return a fresh original selector mapping for durable identity."""
        return dict(self._description)


def compile_selector(criteria):
    """Validate a selector using the existing core policy, then freeze it."""
    from .core import FIELDS, _selector

    description = tuple(_selector(criteria).items())
    for key, expected in description:
        if key.endswith('_re') and not (
                isinstance(expected, str) or
                isinstance(expected, re.Pattern) and isinstance(expected.pattern, str)):
            raise ValueError(f'{key} must be a string or compiled text pattern')
    predicates = tuple(
        (FIELDS[key.removesuffix('_re')], expected,
         re.compile(expected) if key.endswith('_re') else None)
        for key, expected in description
    )
    return SelectorPlan(description, predicates)
