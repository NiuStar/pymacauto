import unittest
from pymacauto import AXMetrics,UnsafeOperation
from test_core import MemoryAX

class MetricsTests(unittest.TestCase):
    def test_counts_and_restores_on_exception(self):
        b=MemoryAX();original=b.get
        with self.assertRaises(ValueError):
            with AXMetrics(b) as m:
                self.assertEqual(b.get('a','AXTitle'),'Apply')
                raise ValueError()
        self.assertEqual(m.summary()['calls']['get'],1)
        self.assertEqual(b.get,original)
    def test_nested_metrics_refuses(self):
        b=MemoryAX()
        with AXMetrics(b):
            with self.assertRaises(UnsafeOperation):
                with AXMetrics(b):pass
