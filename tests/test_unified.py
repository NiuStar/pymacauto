import unittest
from pymacauto import Application,Condition
from pymacauto.operations import OperationSession
from test_core import MemoryAX

class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.nodes['app']['AXWindows']=['window']
        self.b.nodes['window']['AXIdentifier']='win'
        self.b.nodes['a'].update(AXRole='AXTextField',AXValue='before')
        self.a=Application.connect(pid=42,backend=self.b)
        self.target=self.a.child_window(identifier='apply')
        self.s=OperationSession(self.a,window={'identifier':'win'})
    def test_fill_uses_shared_guard_and_value_confirmation(self):
        receipt=self.s.apply(self.target,'fill',value='after',timeout=0)
        self.assertEqual(receipt['status'],'CONFIRMED')
        self.assertEqual(self.b.nodes['a']['AXValue'],'after')
    def test_modal_blocks_fill_before_backend_write(self):
        self.b.nodes['window']['AXSheets']=['sheet']
        receipt=self.s.apply(self.target,'fill',value='after',timeout=0)
        self.assertEqual(receipt['status'],'NOT_DISPATCHED')
        self.assertEqual(self.b.nodes['a']['AXValue'],'before')
    def test_popup_new_sheet_blocks_second_step(self):
        self.b.nodes['a'].update(AXRole='AXPopUpButton',AXValue='before')
        self.b.nodes['item']={'AXRole':'AXMenuItem','AXTitle':'after','AXEnabled':True}
        def perform(ref,action):
            self.b.calls.append((ref,action))
            if ref=='a':
                self.b.nodes['a']['AXChildren']=['item'];self.b.nodes['window']['AXSheets']=['sheet']
        self.b.perform=perform
        result=self.s.apply(self.target,'choose',value='after',postcondition=Condition(self.target,value='after'),timeout=0)
        self.assertEqual(result['status'],'DISPATCHED_UNCONFIRMED')
        self.assertEqual(self.b.calls,[('a','AXPress')])
    def test_checked_shared_guard(self):
        self.b.nodes['a'].update(AXRole='AXCheckBox',AXValue=0)
        def perform(ref,action):self.b.calls.append((ref,action));self.b.nodes[ref]['AXValue']=1
        self.b.perform=perform
        self.assertEqual(self.s.apply(self.target,'check',value=True,timeout=0)['status'],'CONFIRMED')
