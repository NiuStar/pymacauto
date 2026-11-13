import unittest
from pymacauto import Application,UnsafeOperation
from pymacauto.controls import Control
from test_core import MemoryAX

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.b.is_settable=lambda ref,attr:True
        self.app=Application.connect(pid=42,backend=self.b)
        self.b.nodes['a'].update(AXRole='AXCheckBox',AXValue=0)
        self.control=Control(self.app.child_window(identifier='apply'))
    def test_check_is_idempotent_and_reads_after_once(self):
        def perform(ref,action):self.b.calls.append((ref,action));self.b.nodes[ref]['AXValue']=1
        self.b.perform=perform
        self.assertTrue(self.control.set_checked(True)['verified'])
        self.assertTrue(self.control.set_checked(True)['verified'])
        self.assertEqual(len(self.b.calls),1)
    def test_mixed_state_and_wrong_role_refused(self):
        self.b.nodes['a']['AXValue']=2
        with self.assertRaises(UnsafeOperation):self.control.set_checked(True)
        self.b.nodes['a']['AXRole']='AXButton'
        with self.assertRaises(UnsafeOperation):self.control.set_checked(True)
        self.assertEqual(self.b.calls,[])
    def test_radio_select_and_row_selection(self):
        self.b.nodes['a'].update(AXRole='AXRadioButton',AXValue=1)
        self.assertTrue(self.control.select()['verified'])
        with self.assertRaises(UnsafeOperation):self.control.set_checked(False)
        self.b.nodes['a'].update(AXRole='AXRow',AXSelected=False)
        self.b.nodes['a'].pop('AXEnabled')
        self.assertTrue(self.control.select()['verified'])
        self.assertTrue(self.b.nodes['a']['AXSelected'])
    def test_tab_relation_is_unique(self):
        self.b.nodes['a'].update(AXRole='AXTabGroup',AXTabs=['b'])
        self.b.nodes['b'].update(AXRole='AXRadioButton',AXTitle='Tab',AXValue=1)
        self.assertTrue(self.control.select_tab('Tab')['verified'])
        self.b.nodes['copy']=dict(self.b.nodes['b']);self.b.nodes['a']['AXTabs'].append('copy')
        with self.assertRaises(UnsafeOperation):self.control.select_tab('Tab')
    def test_boolean_checkbox_readback_is_valid_without_repress(self):
        self.b.nodes['a']['AXValue']=True
        self.assertTrue(self.control.set_checked(True,timeout=0)['verified'])
        self.assertEqual(self.b.calls,[])
    def test_slider_bounds(self):
        self.b.nodes['a'].update(AXRole='AXSlider',AXMinValue=0,AXMaxValue=10,AXValue=2)
        with self.assertRaises(ValueError):self.control.set_numeric(11)
        self.assertTrue(self.control.set_numeric(3)['verified'])
        self.assertEqual(self.b.nodes['a']['AXValue'],3)
