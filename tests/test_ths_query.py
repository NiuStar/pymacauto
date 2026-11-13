import unittest
from pymacauto.ths_query import recognize_query_view

class THSQueryTests(unittest.TestCase):
    def test_orders_schema_not_disabled_button_recognizes_view(self):
        tables = [{'headers': ['委托日期','委托时间','委托数量','合同编号','证券代码']}]
        self.assertEqual(recognize_query_view(tables), '委托')
    def test_positions_schema_requires_sellable_and_total(self):
        headers = ['证券代码','股票余额','可用余额','成本价']
        self.assertEqual(recognize_query_view([{'headers': headers}]), '持仓')
        self.assertIsNone(recognize_query_view([{'headers': headers[:-1]}]))
    def test_unknown_or_multiple_tables_fail_closed(self):
        self.assertIsNone(recognize_query_view([{'headers': ['日期','金额']}]))
        self.assertIsNone(recognize_query_view([{'headers': ['委托日期','委托时间','委托数量','合同编号']},
                                               {'headers': ['证券代码','股票余额','可用余额','成本价']}]))
    def test_ths535_deals_uses_average_price_not_order_execution_price(self):
        self.assertEqual(recognize_query_view([{'headers':['成交日期','成交时间','证券代码','成交数量','成交均价','成交金额','合同编号','成交编号']}]), '成交')
        self.assertIsNone(recognize_query_view([{'headers':['成交时间','证券代码','成交数量','成交价格']}]))

    def test_fund_detail_schema_not_deals(self):
        self.assertEqual(recognize_query_view([{'headers':['发生金额','本次金额','摘要','货币单位','交易市场','成交均价']}]), '资金明细')
        self.assertIsNone(recognize_query_view([{'headers':['发生金额','本次金额']}]))

    def test_deals_is_distinct_from_orders(self):
        self.assertEqual(recognize_query_view([{'headers':['成交日期','成交时间','证券代码','成交数量','成交均价','成交金额','合同编号','成交编号']}]), '成交')
