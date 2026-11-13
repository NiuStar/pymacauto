"""THS read-only query-schema recognition; never parses account values."""

SCHEMAS = {
    '持仓': frozenset(('证券代码', '股票余额', '可用余额', '成本价')),
    '委托': frozenset(('委托日期', '委托时间', '委托数量', '合同编号')),
    '资金明细': frozenset(('发生金额', '本次金额', '摘要', '货币单位', '交易市场')),
    '成交': frozenset(('成交日期', '成交时间', '证券代码', '成交数量', '成交均价', '成交金额', '成交编号')),
}


def recognize_query_view(tables):
    matches = []
    for title, required in SCHEMAS.items():
        for table in tables:
            if required <= set(table['headers']):
                matches.append(title)
    return matches[0] if len(matches) == 1 else None
