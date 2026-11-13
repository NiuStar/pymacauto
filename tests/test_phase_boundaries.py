import unittest
from pymacauto import Application,Condition
from pymacauto.query_context import QueryContext
from test_core import MemoryAX

class PhaseBoundaries(unittest.TestCase):
    def test_final_phase_observes_new_disabled_state(self):
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        b.nodes['b'].update(AXIdentifier='result',AXValue='before')
        app=Application.connect(pid=42,backend=b)
        target=app.child_window(identifier='apply')
        with app.session(identifier='win') as session:
            original=session._guard_same
            def reject(target,element):
                b.nodes['a']['AXEnabled']=False
                return original(target,element)
            session._guard_same=reject
            result=session.execute(target,postcondition=Condition(app.child_window(identifier='result'),value='after'),timeout=0)
        self.assertEqual(result['status'],'NOT_DISPATCHED');self.assertEqual(b.calls,[])
    def test_context_clear_on_exception(self):
        b=MemoryAX();a=Application.connect(pid=42,backend=b)
        try:
            with QueryContext(a) as q:
                q.get('a','AXRole');raise RuntimeError()
        except RuntimeError:pass
        self.assertEqual(q._cache,{})
        self.assertEqual(a.child_window(identifier='apply').resolve().ref,'a')
