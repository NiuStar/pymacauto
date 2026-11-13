import unittest
from pymacauto import Application,AmbiguousMatch,ElementNotFound,UnsafeOperation
from pymacauto.fields import labelled_field
from test_core import MemoryAX

class FieldTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.app=Application.connect(pid=42,backend=self.b)
        self.b.nodes['window']['AXChildren']=['label','field']
        self.b.nodes['label']={'AXRole':'AXStaticText','AXValue':'Label','AXPosition':{'x':10,'y':20},'AXSize':{'width':30,'height':20}}
        self.b.nodes['field']={'AXRole':'AXTextField','AXEnabled':True,'AXPosition':{'x':45,'y':21},'AXSize':{'width':100,'height':18},'AXValue':'old'}
        self.b.is_settable=lambda ref,attr:True
    def test_exact_label_alignment_selects_ax_field(self):
        e=labelled_field(self.app,'window','Label')
        self.assertEqual(e.ref,'field')
        self.assertTrue(e.set_edit_text('new')['verified'])
        self.assertEqual(self.b.calls,[])
    def test_duplicate_labels_refuse(self):
        self.b.nodes['other']=dict(self.b.nodes['label']);self.b.nodes['window']['AXChildren'].append('other')
        with self.assertRaises(AmbiguousMatch):labelled_field(self.app,'window','Label')
    def test_duplicate_aligned_fields_refuse(self):
        self.b.nodes['other']=dict(self.b.nodes['field']);self.b.nodes['window']['AXChildren'].append('other')
        with self.assertRaises(AmbiguousMatch):labelled_field(self.app,'window','Label')
    def test_moved_or_missing_field_refuses(self):
        self.b.nodes['field']['AXPosition']['y']=200
        with self.assertRaises(ElementNotFound):labelled_field(self.app,'window','Label')
    def test_secure_disabled_or_readonly_refuse(self):
        for change in ({'AXSubrole':'AXSecureTextField'},{'AXEnabled':False}):
            with self.subTest(change=change):
                self.setUp();self.b.nodes['field'].update(change)
                with self.assertRaises(UnsafeOperation):labelled_field(self.app,'window','Label')
        self.setUp();self.b.is_settable=lambda *a:False
        with self.assertRaises(UnsafeOperation):labelled_field(self.app,'window','Label')
    def test_invalid_geometry_refuses(self):
        for value in (float('nan'),None,True):
            self.setUp();self.b.nodes['field']['AXPosition']['x']=value
            with self.assertRaises(ElementNotFound):labelled_field(self.app,'window','Label')
        self.setUp();self.b.nodes['field']['AXSize']['width']=0
        with self.assertRaises(ElementNotFound):labelled_field(self.app,'window','Label')

    def test_replacement_ref_is_fresh(self):
        labelled_field(self.app,'window','Label')
        self.b.nodes['replacement']=dict(self.b.nodes['field']);self.b.nodes['window']['AXChildren']=['label','replacement']
        self.assertEqual(labelled_field(self.app,'window','Label').ref,'replacement')
