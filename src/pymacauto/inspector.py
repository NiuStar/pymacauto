"""Read-only diagnostic AX graph. Partial evidence never authorizes actions."""
from collections import Counter, deque
from datetime import datetime, timezone
import time

from .core import _json_value, _positive
from .errors import AttributeUnsupported, MacAXError

RELATIONS = ('AXChildren', 'AXWindows', 'AXMenuBar', 'AXRows', 'AXColumns',
             'AXTabs', 'AXContents', 'AXHeader', 'AXColumnHeaderUIElements')
FIELDS = {'role': 'AXRole', 'subrole': 'AXSubrole', 'identifier': 'AXIdentifier',
          'title': 'AXTitle', 'description': 'AXDescription', 'help': 'AXHelp',
          'enabled': 'AXEnabled', 'position': 'AXPosition', 'size': 'AXSize'}


def _candidate_selector(fields, nodes):
    candidates = []
    for key in ('identifier', 'title', 'description', 'help'):
        if fields.get(key):
            selector = {key: fields[key]}
            if key != 'identifier': selector = {'role': fields.get('role'), **selector}
            candidates.append(selector)
    base = {key: fields[key] for key in ('role','identifier','title','description','help') if fields.get(key)}
    if base: candidates.append(base)
    for selector in candidates:
        if sum(all(other['fields'].get(k) == v for k, v in selector.items()) for other in nodes) == 1:
            return selector, True
    return (candidates[-1], False) if candidates else (None, False)


def inspect_application(app, *, max_nodes=None, max_depth=None, timeout=45):
    """Read metadata/capabilities, NOT AXValue or selected text/account values.

    Edges retain the diagnostic relation and ordinal, never a stable action ID.
    complete means this bounded relation graph had no error/limit, not that all
    app screens (including hidden/dynamically populated pages) were visited.
    """
    max_nodes = app.max_nodes if max_nodes is None else _positive(max_nodes, 'max_nodes', integer=True)
    max_depth = app.max_depth if max_depth is None else _positive(max_depth, 'max_depth', integer=True, zero=True)
    _positive(timeout, 'timeout')
    started = time.monotonic()
    nodes, edges, limits = [], [], []
    root_key = app.backend.key(app._root)
    ids = {root_key: 0}
    queue = deque([(app._root, 0, 0, [])])
    incomplete = False

    def read(node, operation, fn):
        nonlocal incomplete
        if time.monotonic() - started >= timeout:
            if 'timeout' not in limits: limits.append('timeout')
            incomplete = True
            return None
        try:
            return fn()
        except AttributeUnsupported:
            node['unsupported'].append(operation)
            return None
        except MacAXError as exc:
            incomplete = True
            node['errors'].append({'operation': operation, 'error': type(exc).__name__,
                                   'code': getattr(exc, 'code', None)})
            return None

    while queue:
        if time.monotonic() - started >= timeout:
            limits.append('timeout') if 'timeout' not in limits else None
            incomplete = True
            break
        ref, node_id, depth, path = queue.popleft()
        node = {'id': node_id, 'depth': depth, 'path': path, 'fields': {},
                'attributes': [], 'actions': None, 'settable': {}, 'errors': [], 'unsupported': []}
        nodes.append(node)
        attrs = read(node, 'attributes', lambda: app.backend.attributes(ref))
        node['attributes'] = attrs if attrs is not None else []
        for field, attribute in FIELDS.items():
            node['fields'][field] = _json_value(read(node, attribute, lambda a=attribute: app.backend.get(ref, a)))
        node['actions'] = read(node, 'actions', lambda: app.backend.actions(ref))
        secure = node['fields'].get('subrole') == 'AXSecureTextField'
        for attribute in ('AXValue', 'AXSelected', 'AXExpanded', 'AXSelectedRows', 'AXSelectedChildren'):
            if attribute not in node['attributes']:
                continue
            if secure:
                node['settable'][attribute] = '<blocked-secure>'
            else:
                node['settable'][attribute] = read(node, 'settable:' + attribute,
                    lambda a=attribute: app.backend.is_settable(ref, a))
        for relation in RELATIONS:
            # Apple's system menu includes recent documents/servers belonging
            # to other apps. Never expand it during target-app discovery.
            if node['fields'].get('role') == 'AXMenuBarItem' and node['fields'].get('title') == 'Apple':
                node['excluded_subtree'] = 'system_apple_menu'
                break
            if attrs is not None and relation not in attrs:
                continue
            value = read(node, relation, lambda a=relation: app.backend.get(ref, a))
            if value is None: continue
            children = value if isinstance(value, (list, tuple)) else [value]
            for index, child in enumerate(children):
                key = app.backend.key(child)
                target = ids.get(key)
                if target is None:
                    if depth >= max_depth or len(ids) >= max_nodes:
                        reason = 'max_depth' if depth >= max_depth else 'max_nodes'
                        if reason not in limits: limits.append(reason)
                        incomplete = True
                        continue
                    target = len(ids)
                    ids[key] = target
                    queue.append((child, target, depth + 1, path + [{'relation': relation, 'index': index}]))
                edges.append({'source': node_id, 'relation': relation, 'index': index, 'target': target})

    # Metadata locators are candidates only. Core resolver must independently
    # revalidate uniqueness on the live AXChildren tree before any mutation.
    for node in nodes:
        selector, unique = _candidate_selector(node['fields'], nodes)
        node['candidate_selector'] = selector
        node['selector_unique_in_capture'] = unique
    counts = Counter(n['fields'].get('role') or '<unknown>' for n in nodes)
    return {'schema': 'pymacauto.inspection.v1', 'captured_at': datetime.now(timezone.utc).isoformat(),
            'application': app.info, 'read_only': True, 'values_included': False,
            'complete': not incomplete, 'all_screens_covered': False,
            'node_count': len(nodes), 'role_counts': dict(counts),
            'limits_hit': limits, 'elapsed_seconds': time.monotonic() - started,
            'nodes': nodes, 'edges': edges}
