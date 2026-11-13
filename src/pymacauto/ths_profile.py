"""Optional THS 5.3.5 UI selectors/fingerprints; no field interpretation."""
from .ths_query import SCHEMAS

PROFILE={
    'bundle_id':'cn.com.10jqka.macstockPro','version':'5.3.5','build':'7.0.62',
    'window':{'identifier':'主窗口'},
    'content_path':[{'role':'AXScrollArea','identifier_re':r'^_NS:(210|224|79|176)$'}],
    'trigger_children_only':True,
    'pages':{
        name:{'trigger':{'role':'AXButton','title':name,'identifier':trigger},
              'table':{'role':'AXTable','identifier':table},'headers':tuple(SCHEMAS[name])}
        for name,trigger,table in (
            ('持仓','_NS:42','1537'),('委托','_NS:38','1539'),
            ('成交','_NS:34','1538'),('资金明细','_NS:22','1544'))},
    'read_pages':('持仓','委托','成交')}
