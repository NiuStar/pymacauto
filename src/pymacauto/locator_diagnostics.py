"""Read-only locator evidence. Captured counts never authorize a UI action."""
from collections import Counter
import copy
import json

from .core import Element, Locator, _get, _matches, _path_step, _selector
from .errors import (AmbiguousMatch, ElementNotFound, MacAXError,
                     SearchLimitExceeded, UnsafeOperation)


_METADATA = {'role': 'AXRole', 'subrole': 'AXSubrole',
             'identifier': 'AXIdentifier', 'enabled': 'AXEnabled'}


def _safe_selector(criteria):
    if any(key in criteria for key in ('value', 'value_re')):
        raise UnsafeOperation('Value selectors are not supported by locator diagnostics')
    return _selector(criteria)


def _direct_refs(app, root, relation='child'):
    refs = app.backend.get(root, 'AXWindows' if relation == 'window' else 'AXChildren')
    if not isinstance(refs, (list, tuple)):
        raise ElementNotFound('Path relation unavailable')
    if len(refs) > app.max_nodes:
        raise SearchLimitExceeded('Path children node budget')
    seen, result = set(), []
    for ref in refs:
        key = app.backend.key(ref)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def inspect_children(locator, **criteria):
    """List distinct direct children of an Element or resolved Locator.

    Only role/subrole/identifier/enabled metadata is read by default. ``index``
    and ``expected_count`` apply to the supplied filter, ``role_index`` and
    ``role_count`` to a role-only filter. All indices are zero based; ``ordinal``
    is the unfiltered distinct-child position. No descendant flattening occurs.
    Errors and budget exhaustion raise rather than publishing partial counts.
    """
    target = locator
    if not isinstance(target, (Element, Locator)):
        raise TypeError('Expected an Element or Locator')
    if criteria:
        criteria = _safe_selector(criteria)
    if isinstance(target, Locator):
        _validate_chain(target)
        target = target.resolve()
    refs = _direct_refs(target.app, target.ref)
    rows = []
    for ordinal, ref in enumerate(refs):
        fields = {}
        for name, attribute in _METADATA.items():
            value = _get(target.backend, ref, attribute)
            # Never serialize a surprising native object returned as metadata.
            fields[name] = value if (isinstance(value, bool) if name == 'enabled'
                                    else isinstance(value, str)) else None
        rows.append((ref, dict(ordinal=ordinal, **fields)))
    role_counts = Counter(row['role'] for _, row in rows)
    role_indices, children = Counter(), []
    for ref, row in rows:
        role = row['role']
        row.update(role_index=role_indices[role], role_count=role_counts[role])
        role_indices[role] += 1
        if not criteria or _matches(target.backend, ref, criteria):
            row['index'] = len(children)
            children.append(row)
    for row in children:
        row['expected_count'] = len(children)
    return {'schema': 'pymacauto.children.v1', 'read_only': True,
            'values_included': False, 'authorizes_mutation': False,
            'complete': True, 'count': len(children), 'total_count': len(rows),
            'children': children}


def _validate_chain(locator):
    if not isinstance(locator, Locator):
        raise TypeError('Expected a Locator')
    # Validate every prefix before any reads, including otherwise unreachable ones.
    for entry in locator.chain:
        if entry.get('$path') is True:
            _safe_selector(entry['selector'])
            if entry['verify'] is not None:
                _safe_selector(entry['verify'])
            _path_step(entry['selector'], relation=entry['relation'],
                       index=entry['index'], expected_count=entry['expected_count'],
                       verify=entry['verify'])
        else:
            _safe_selector(entry)


def _app_rooted(locator):
    _validate_chain(locator)
    if locator.root is not None:
        raise UnsafeOperation('Diagnostics require an application-rooted locator')


def _step(entry):
    if entry.get('$path') is True:
        return {key: entry[key] for key in
                ('relation', 'selector', 'index', 'expected_count', 'verify')}
    return _path_step(entry, relation='descendant')


def _failure_status(exc):
    if isinstance(exc, SearchLimitExceeded):
        return 'budget_exceeded'
    if isinstance(exc, AmbiguousMatch):
        return 'ambiguous'
    if isinstance(exc, ElementNotFound):
        return 'missing'
    if isinstance(exc, UnsafeOperation):
        return 'unsafe'
    return 'error'


def explain_locator(locator):
    """Explain each level without returning selectors, messages or native refs.

    Full candidate enumeration uses the same bounded relations as core. Each
    prefix is then independently resolved by core, including count/index/verify
    checks. A failed level blocks every following level. ``complete`` means the
    whole chain resolved consistently, not that this evidence authorizes action.
    Counts are null if enumeration did not finish. This is live evidence, not an
    atomic snapshot; conflicting observations fail closed as ``changed``.
    Captured/callable roots and value/value_re selectors are refused.
    """
    _app_rooted(locator)
    app, levels, blocked = locator.app, [], False
    root = app._root
    status = 'resolved'
    for offset, entry in enumerate(locator.chain):
        step = _step(entry)
        level = {'level': offset, 'relation': step['relation'],
                 'index': step['index'], 'expected_count': step['expected_count'],
                 'verify_requested': step['verify'] is not None,
                 'candidate_count': None, 'match_count': None, 'selected_count': 0,
                 'search_complete': False, 'status': 'blocked', 'failure': None}
        levels.append(level)
        if blocked:
            continue
        observation_error, selected, observed_status = None, None, None
        try:
            if step['relation'] in ('child', 'window'):
                if (step['relation'] == 'window'
                        and app.backend.key(root) != app.backend.key(app._root)):
                    raise ValueError('window relation only allowed at application root')
                candidates = _direct_refs(app, root, step['relation'])
            else:
                candidates = [ref for ref, _ in app._walk(root)]
            matches = [ref for ref in candidates
                       if _matches(app.backend, ref, step['selector'])]
            level.update(candidate_count=len(candidates), match_count=len(matches),
                         search_complete=True)
            if step['expected_count'] is not None and len(matches) != step['expected_count']:
                observed_status = 'count_mismatch'
            elif step['index'] is not None and step['index'] >= len(matches):
                observed_status = 'index_out_of_range'
            else:
                chosen = matches if step['index'] is None else [matches[step['index']]]
                if not chosen:
                    observed_status = 'missing'
                elif len(chosen) != 1:
                    observed_status = 'ambiguous'
                elif step['verify'] is not None and not _matches(app.backend, chosen[0], step['verify']):
                    observed_status = 'verify_mismatch'
                else:
                    selected = chosen[0]
        except (MacAXError, ValueError) as exc:
            observation_error = exc
        # Prefix resolution is authoritative: never infer successful resolution
        # solely from an independent count or bypass the existing core guards.
        try:
            resolved = Locator(app, locator.chain[:offset + 1]).resolve()
        except (MacAXError, ValueError) as exc:
            level['failure'] = type(exc).__name__
            level['status'] = _failure_status(exc)
            expected_failure = {'count_mismatch': UnsafeOperation,
                                'verify_mismatch': UnsafeOperation,
                                'index_out_of_range': ElementNotFound}
            if observed_status in expected_failure and isinstance(exc, expected_failure[observed_status]):
                level['status'] = observed_status
        else:
            if observation_error is not None:
                level.update(status=_failure_status(observation_error),
                             failure=type(observation_error).__name__)
            elif observed_status is not None or app.backend.key(selected) != app.backend.key(resolved.ref):
                level.update(status='changed', failure='InconsistentObservation')
            else:
                level.update(status='resolved', selected_count=1)
                root = resolved.ref
        if level['status'] != 'resolved':
            status, blocked = level['status'], True
    return {'schema': 'pymacauto.locator_explanation.v1', 'read_only': True,
            'values_included': False, 'authorizes_mutation': False,
            'complete': not blocked, 'status': status, 'levels': levels}


def export_locator(locator):
    """Return a detached, JSON-serializable candidate for ``app.locator_path``.

    Export does not resolve, validate uniqueness, read AX attributes, or grant
    action authority. Flat legacy steps become descendant steps. All path fields
    are retained, but internal ``$path`` markers are not public path syntax.
    Values (including verify value selectors) and captured roots are refused.
    Explicit non-value selector content is preserved; do not publish exports
    containing private title/identifier criteria to untrusted destinations.
    """
    _app_rooted(locator)
    if not locator.chain:
        raise ValueError('Nonempty candidate path required')
    path = []
    for entry in locator.chain:
        step = _step(entry)
        path.append({key: copy.deepcopy(step[key]) for key in
                     ('relation', 'selector', 'index', 'expected_count', 'verify')})
    try:
        json.dumps(path, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('Candidate path must contain only JSON data') from None
    return {'schema': 'pymacauto.locator_candidate.v1', 'status': 'candidate',
            'read_only': True, 'values_included': False, 'validated': False,
            'authorizes_mutation': False, 'path': path}
