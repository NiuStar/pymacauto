"""Orchestrator failure boundaries; run on Mac, replace only external effects."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack, redirect_stdout
import pymacauto.ths_reader as reader


class ReaderTests(unittest.TestCase):
    def run_case(self, broken_read=False, broken_restore=False):
        original=Mock();original.processIdentifier.return_value=123
        target=Mock();target.processIdentifier.return_value=456
        target.bundleURL.return_value.path.return_value='/Applications/同花顺.app'
        workspace=Mock();workspace.frontmostApplication.return_value=original
        front={'pid':123}
        original.activateWithOptions_.side_effect=lambda *args:front.update(pid=123)
        target.activateWithOptions_.side_effect=lambda *args:front.update(pid=456)
        current={'view':'持仓'};clicks=[]
        app=Mock()
        def child_window(**criteria):
            locator=Mock()
            def click():
                title=criteria['title'];clicks.append(title)
                if broken_restore and title=='持仓':raise RuntimeError('restore fixture')
                current['view']=title
            locator.click.side_effect=click
            return locator
        app.child_window.side_effect=child_window
        def state(_):return {'view':current['view'],'tables':[current['view']]}
        def read_view(_, title, table=None):
            if broken_read and title=='委托':raise reader.MacAXError('read fixture')
            return {'rows':[{'account':'private-fixture'}],'status':'READ_OK','row_count':1,'view':title}
        class Session:
            read_errors=[]
            def __init__(self,*args,**kw):pass
            def wait(self,*args,**kw):return {'page':current['view'],'table':'table','headers':['field']}
            def switch(self,title):
                if current['view']!=title:child_window(title=title).click()
                return self.wait()
        def wait_for(fn,seconds):return fn()
        with tempfile.TemporaryDirectory(prefix='pymacauto-reader-test-') as folder, ExitStack() as stack:
            stack.enter_context(patch.object(reader,'NSWorkspace',Mock(sharedWorkspace=Mock(return_value=workspace))))
            stack.enter_context(patch.object(reader,'NSRunningApplication',Mock(runningApplicationsWithBundleIdentifier_=Mock(return_value=[target]))))
            bundle=Mock();bundle.infoDictionary.return_value={'CFBundleShortVersionString':'5.3.5','CFBundleVersion':'7.0.62'}
            stack.enter_context(patch.object(reader,'NSBundle',Mock(bundleWithPath_=Mock(return_value=bundle))))
            stack.enter_context(patch.object(reader.Application,'connect',return_value=app))
            stack.enter_context(patch.object(reader,'current_front',side_effect=lambda _:front['pid']))
            stack.enter_context(patch.object(reader,'PageSession',Session))
            stack.enter_context(patch.object(reader,'wait_for',side_effect=wait_for))
            stack.enter_context(patch.object(reader,'read_view',side_effect=read_view))
            stack.enter_context(patch.object(reader.Path,'home',return_value=Path(folder)))
            output=io.StringIO()
            with redirect_stdout(output):code=reader.main(['--allow-foreground'])
            summary=json.loads(output.getvalue())
            stored=json.loads(Path(summary['private_data_path']).read_text())
            mode=Path(summary['private_data_path']).stat().st_mode & 0o777
        return code,summary,stored,clicks,mode,original

    def test_success_persists_private_values_but_summary_omits_them(self):
        code,summary,stored,clicks,mode,original=self.run_case()
        self.assertEqual(code,0)
        self.assertEqual(clicks,['委托','成交','持仓'])
        self.assertNotIn('private-fixture',json.dumps(summary))
        self.assertEqual(stored['tables']['持仓']['rows'][0]['account'],'private-fixture')
        self.assertEqual(mode,0o600)
        original.activateWithOptions_.assert_called_once()

    def test_read_failure_stops_next_view_and_restores(self):
        code,summary,stored,clicks,_,original=self.run_case(broken_read=True)
        self.assertEqual(code,1)
        self.assertEqual(clicks,['委托','持仓'])
        self.assertTrue(summary['query_restored'])
        self.assertEqual(summary['status'],'FAIL')
        original.activateWithOptions_.assert_called_once()

    def test_restore_failure_cannot_return_success(self):
        code,summary,_,_,_,original=self.run_case(broken_restore=True)
        self.assertEqual(code,1)
        self.assertEqual(summary['status'],'FAIL')
        self.assertIn('restore_error',summary)
        original.activateWithOptions_.assert_called_once()
