# 0.8.0a1 性能与便捷接口候选（未发布）

本候选在0.7.0之上尝试减少同一结构检查阶段的重复原生读取。不降低日志同步、唯一性、模态检查、最后派发检查或表格双读要求；正式main仍保持已验收版本。

## 变更方向

- 选择器编译成不可变计划，保留条件顺序、正则和bool/数字区分；计划不包含原生引用或查询结果。
- 内部QueryContext只在同步结构读取阶段保存角色、标识、子关系等证据；退出即清空。输入、意图落盘前后和每轮观察使用分开的阶段。
- AXValue及任意内容不缓存；安全输入框在值读取前重新查子角色，拒绝敏感内容。表格读取器不复用上下文完成第二次采样。
- 在保护遍历里批量读取同一节点的角色/模态信息，降低AX往返；不意味着整棵树只用一次RPC。
- 原有SDK和序列化选择链保持兼容，新增薄命名封装，修改仍通过OperationSession。

QueryContext是内部机制，不是调用方的长期缓存API。不要跨UI修改、等待、进程或线程复用。同步AX查询本身不提供原子界面快照；一阶段取证仍有应用并发变化的限制，最终派发前仍重新取证。

## 命名接口

```python
from pymacauto import Application, AppProfile
app = Application.connect(bundle_id="com.example.demo")
profile = AppProfile({
  "bundle_id":"com.example.demo", "version":"1.0", "build":"1",
  "window":{"identifier":"example.window"},
  "controls":{
    "input":{"identifier":"example.input"},
    "apply":{"identifier":"example.apply"},
    "result":{"identifier":"example.result"}
  }
})
with app.automation(profile, journal=private_journal) as ui:
    receipt = ui.control("input").fill("hello", operation_id="fill-1")
    # 收到非CONFIRMED回执必须由调用方停止/协调，不自动重试或盲目继续
    if receipt["status"] != "CONFIRMED":
        raise RuntimeError("input not confirmed")
    result = ui.control("apply").click(
        expect=ui.condition("result", value="applied:hello"), operation_id="apply-1"
    )
```

`private_journal`由调用方提供，沿用日志路径及权限约束。命名来自Profile，不按词义猜控件；`.read()`原样读值，`.read_table()`使用严格读取，`.check(True)`走保护入口。配置页面时可传`pages=页面配置`，调用`ui.page(name).ensure()`。关闭后旧包装对象也拒绝继续访问。命名层不添加坐标、键盘、隐式焦点或重试。

该封装减少重复连接代码，不是原子多步事务。每步回执仍必须检查，Profile资格不等于动作已测试，值相等不等于业务接受。

## 已观察到的性能证据

初轮批读调用下降但保护填写变慢（约60.9→64.9ms），该结果保留。继续减少身份键创建和同阶段重复遍历后的第三轮，三组交错保护填写中位约69.6→60.5ms，读取计数730次get→280次get+69次get_many；输入调用仍为一次。此为安全审查修复前候选，不能当作最终候选结果。是小型自建窗口的同一公共session.apply负载，不适用于任意应用。

同花顺当前表读取的三组数据表头/所有单元格精确相同，但第三轮约142.5/143.2ms，未测得性能改善。其单独read_table仍完整双采样。早期双页矩阵有失败记录，不能抹除；修复后完整三组已通过，结果见下。

## 审查修复后冻结实测

- 修复两条回归：AXSubrole不缓存，安全字段在每次直接内容访问前仍新读取；AXWindows/直接AXChildren等必需关系读取保留AttributeUnsupported，不从可选缺失推断gone。
- Mac独立安装版305项逻辑、10项桥接契约回归通过；完整原生控件/事件/模态/日志及命名层填写点击通过，前台保持、夹具回收。
- 三组交错填写中位83.521→70.869ms；get730→298，另69次get_many。原始值一致，动作不重试。
- 同花顺只读三组约150.590/149.681ms，所有表头/单元格精确相同；波动范围内，不宣称读表提速。
- 原生双页三组共六轮，严格读取值/摘要完全一致，前台保持、夹具回收；两次受保护切页中位373.077/377.867ms，未提速。读取包含两张表的完整双读与引用校验，get5342→4660，get_many4420→4494。
- 本次优化只对已测小窗口保护填写有时延改善证据，不承诺全应用/所有页面更快。新增代码是薄API及内部复用机制，不宣称总代码行数下降；用户常用操作连接代码减少。
- 最新安装模块29个已逐字节核对，120.49秒持续复验完成202次自建字段操作与4次同花顺严格只读，前台保持、停止保护和夹具回收PASS。短测不证明两小时/全天稳定；历史0.7.0的两小时PASS不能直接当作此版本长测。
- 本候选尚未正式发布；正式main保持0.7.0，独立审查的最终反馈与候选分支CI单独验收。
