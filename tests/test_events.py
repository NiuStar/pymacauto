import threading
import unittest
from unittest.mock import patch
from pymacauto import Application,Condition,UnsafeOperation,WaitTimeout
from pymacauto.events import AXEvents,wait_condition
from test_core import MemoryAX

class FakeEvents:
    def __init__(self,*args,**kwargs):self.received=0;self.unsupported=['AXValueChanged'];self.mode='poll'
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def pause(self,seconds):self.received+=1

class EventTests(unittest.TestCase):
    def setUp(self):
        self.b=MemoryAX();self.app=Application.connect(pid=42,backend=self.b)
    def test_fallback_requires_readback(self):
        self.b.nodes['a']['AXValue']='ready'
        with patch('pymacauto.events.AXEvents',FakeEvents):
            result=wait_condition(Condition(self.app.child_window(identifier='apply'),value='ready'),timeout=0)
        self.assertTrue(result['verified']);self.assertEqual(result['mode'],'poll')
    def test_missing_or_false_condition_times_out_not_success(self):
        with patch('pymacauto.events.AXEvents',FakeEvents):
            with self.assertRaises(WaitTimeout):wait_condition(Condition(self.app.child_window(identifier='absent')),timeout=0)
    def test_cleanup_attempts_every_notification_after_failure(self):
        from unittest.mock import Mock
        from pymacauto import MacAXError
        events=AXEvents(self.app)
        events._closed=False;events._loop='loop';events._source='source';events._observer='observer'
        events._callback=lambda *args:None
        events._registered=[('a','AXValueChanged'),('a','AXCreated')]
        events._cf=Mock();events._ax=Mock()
        events._ax.AXObserverRemoveNotification.side_effect=[RuntimeError(),0]
        self.app.backend._check=lambda *args:None
        with self.assertRaises(MacAXError):events.close()
        self.assertEqual(events._ax.AXObserverRemoveNotification.call_count,2)
        self.assertIsNone(events._observer);self.assertEqual(events._registered,[])
        events.close()
    def test_observer_refuses_wrong_thread(self):
        events=AXEvents(self.app);errors=[]
        def call():
            try:events.pause(0)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=call);thread.start();thread.join()
        self.assertIsInstance(errors[0],UnsafeOperation)
