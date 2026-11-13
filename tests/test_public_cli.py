import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from pymacauto.cli import main,parser
from pymacauto import Application
from test_core import MemoryAX

class PublicCLITests(unittest.TestCase):
    def invoke(self,args,backend=None):
        out=io.StringIO()
        with patch('pymacauto.native.NativeBackend',return_value=backend or MemoryAX()),redirect_stdout(out):
            code=main(args)
        return code,json.loads(out.getvalue())
    def test_get_value(self):
        b=MemoryAX();b.nodes['a']['AXValue']='000001'
        code,result=self.invoke(['get-value','--pid','42','--identifier','apply'],b)
        self.assertEqual(code,0);self.assertEqual(result['result'],'000001')
    def test_existing_output_refuses_before_backend_and_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.json';path.write_text('preserve')
            with patch('pymacauto.cli.run') as run:
                code,result=self.invoke(['set-value','--pid','42','--identifier','apply','--value','x','--execute','--output',str(path)])
            run.assert_not_called();self.assertEqual(code,2);self.assertEqual(path.read_text(),'preserve')
    def test_private_output_before_and_after_subcommand(self):
        with tempfile.TemporaryDirectory() as folder:
            for index in range(2):
                path=Path(folder)/f'{index}.json'
                args=['apps','--output',str(path)] if index else ['--output',str(path),'apps']
                code,result=self.invoke(args)
                self.assertEqual(code,0);self.assertEqual(result['output'],str(path))
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                self.assertEqual(json.loads(path.read_text())['result'][0]['pid'],42)
    def test_page_and_fill_require_execute(self):
        for args in (['page','--pid','42','--config','unused.json','--to','x'],
                     ['fill','--pid','42','--window-identifier','win','--label','label','--value','x']):
            code,result=self.invoke(args)
            self.assertEqual(code,2);self.assertEqual(result['error'],'UnsafeOperation')
    def test_inspection_is_explicitly_partial_not_false_success(self):
        code,result=self.invoke(['inspect','--pid','42','--max-nodes','1'])
        self.assertEqual(code,0)
        self.assertFalse(result['result']['complete'])
        self.assertTrue(result['result']['limits_hit'])
    def test_scoped_read_table_dispatches_strict_reader(self):
        b=MemoryAX();b.nodes['app']['AXWindows']=['window']
        b.nodes['window']['AXIdentifier']='win'
        b.nodes['a']['AXRole']='AXTable'
        expected={'status':'READ_OK','rows':[],'row_count':0}
        with patch('pymacauto.tables.read_table',return_value=expected) as read:
            code,result=self.invoke(['read-table','--pid','42','--window-identifier','win','--role','AXTable','--identifier','apply'],b)
        self.assertEqual(code,0);self.assertEqual(result['result'],expected)
        self.assertEqual(read.call_args.args,(b,'a'))
    def test_secure_value_read_is_blocked(self):
        b=MemoryAX();b.nodes['a']['AXSubrole']='AXSecureTextField';b.nodes['a']['AXValue']='not-public'
        code,result=self.invoke(['get-value','--pid','42','--identifier','apply'],b)
        self.assertEqual(code,2);self.assertNotIn('not-public',json.dumps(result))
    def test_verified_action_requires_explicit_execute_and_nonzero_unconfirmed(self):
        base=['verified-action','--pid','42','--window','{"identifier":"win"}',
              '--target','{"identifier":"apply"}','--expect','{"identifier":"other"}',
              '--expect-value','ready','--timeout','0']
        code,result=self.invoke(base)
        self.assertEqual(code,2);self.assertEqual(result['error'],'UnsafeOperation')
        b=MemoryAX();b.nodes['app']['AXWindows']=['window'];b.nodes['window']['AXIdentifier']='win'
        code,result=self.invoke(base+['--execute'],b)
        self.assertEqual(code,1);self.assertEqual(result['result']['status'],'DISPATCHED_UNCONFIRMED')
        self.assertEqual(len(b.calls),1)
    def test_hierarchical_json_cli(self):
        path=[{'relation':'descendant','selector':{'role':'AXWindow','title':'Demo'}},
              {'relation':'child','selector':{'role':'AXButton'},'index':1,'expected_count':2}]
        b=MemoryAX();b.nodes['b']['AXValue']='second'
        code,result=self.invoke(['get-value','--pid','42','--path',json.dumps(path)],b)
        self.assertEqual(code,0);self.assertEqual(result['result'],'second')
    def test_journal_inspect_missing_does_not_create(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'absent'/'ops.db'
            code,result=self.invoke(['journal-inspect','--journal',str(path)])
            self.assertEqual(code,2);self.assertFalse(path.parent.exists())
    def test_corrupt_journal_is_json_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'broken.db'
            path.write_bytes(b'not sqlite');path.chmod(0o600)
            code,result=self.invoke(['journal-inspect','--journal',str(path)])
            self.assertEqual(code,2);self.assertFalse(result['ok'])
    def test_sdk_discovery_helpers(self):
        b=MemoryAX()
        with patch('pymacauto.native.NativeBackend',return_value=b):
            self.assertTrue(Application.is_trusted())
            self.assertEqual(Application.list_apps()[0]['pid'],42)
