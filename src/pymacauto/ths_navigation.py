"""Optional THS query-view metadata compatibility helper; no UI actions."""
from .pages import PageSession
from .ths_profile import PROFILE
from .focus import current_front,wait_for
from .tables import optional

TABS={name:page['trigger']['identifier'] for name,page in PROFILE['pages'].items()}


def state(app):
    session=PageSession(app,window=PROFILE['window'],pages=PROFILE['pages'],
                        content_path=PROFILE.get('content_path'),
                        trigger_children_only=PROFILE.get('trigger_children_only',False))
    result=session.wait()
    return {'view':result['page'],'tables':[{'identifier':optional(app.backend,result['table'],'AXIdentifier'),
                                           'headers':result['headers']}]}
