"""Publication review regressions; no real user UI actions."""
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest
from pymacauto import Application,UnsafeOperation
from pymacauto.cli import main
from pymacauto.pages import PageSession
from test_core import MemoryAX

class ReleaseBoundaries(unittest.TestCase):
    def test_secure_raw_text_attributes_refused(self):
        b=MemoryAX();b.nodes['a']['AXSubrole']='AXSecureTextField'
        b.nodes['a']['AXSelectedText']='secret'
        app=Application.connect(pid=42,backend=b)
        e=app.child_window(identifier='apply').resolve()
        for name in ('AXValue','AXSelectedText','AXAttributedString','AXTitle'):
            with self.subTest(attribute=name):
                with self.assertRaises(UnsafeOperation):e.get(name)
        self.assertEqual(e.get('AXSubrole'),'AXSecureTextField')

    def test_scoped_wait_reacquires_rebuilt_window(self):
        for state in ('exists','gone'):
            b=MemoryAX();b.nodes['app']['AXWindows']=['window']
            b.nodes['window']['AXIdentifier']='win'
            original=b.get;reads=0
            def get(ref,attribute):
                nonlocal reads
                if ref=='app' and attribute=='AXWindows':
                    reads+=1
                    if reads==2:
                        b.nodes['rebuilt']=dict(b.nodes['window'])
                        b.nodes['window']['AXChildren']=[]
                        b.nodes['app']['AXWindows']=['rebuilt']
                return original(ref,attribute)
            b.get=get;out=io.StringIO()
            with patch('pymacauto.native.NativeBackend',return_value=b),redirect_stdout(out):
                code=main(['wait','--pid','42','--window-identifier','win','--identifier','apply',
                           '--state',state,'--timeout','0'])
            data=json.loads(out.getvalue())
            self.assertEqual(code,0 if state=='exists' else 2)
            if state=='gone':self.assertEqual(data['error'],'WaitTimeout')

    def test_malformed_page_paths_are_value_errors_before_actions(self):
        b=MemoryAX();app=Application.connect(pid=42,backend=b)
        pages={'A':{'trigger':{'identifier':'page'},'table':{'role':'AXTable'},'headers':['Name']}}
        for options in ({'content_path':[1]}, {'leaf_roles':['not-a-role']},
                        {'window':{'role':'AXButton'}}, {'trigger_children_only':'true'}):
            config={'window':{'identifier':'win'},'pages':pages,**options}
            with self.subTest(config=config):
                with self.assertRaises(ValueError):PageSession.from_config(app,config)
        self.assertEqual(b.calls,[])
