# 0.5.0：持久化与有界工作流

## 持久化防重

```python
from pathlib import Path
from pymacauto import Application, Condition
app = Application.connect(bundle_id="com.example.demo")
field = app.window(identifier="example.window").child_window(identifier="example.input")
with app.session(identifier="example.window",
                 journal=Path.home()/".pymacauto-private/operations.sqlite") as session:
    receipt = session.apply(field, "fill", value="hello", operation_id="request-1")
```

日志父目录须当前用户所有、权限0700，数据库须0600且非符号链接/多硬链接。使用SQLite DELETE journal与synchronous=EXTRA，事务提交后才派发。日志保存带私有随机盐的请求HMAC及阶段/回执，不保存选择器和输入值原文。数据库本身仍是私有审计数据。

同一ID不同目标、动作、参数、条件、窗口或进程身份会拒绝；重新打开日志遇到PREPARED/派发意图都不会自动重放。必须保留并备份日志，删除/替换数据库会丢失防重历史。它不是跨UI与SQLite的原子事务，也不是业务“恰好一次”。磁盘或数据库错误必须停止，不可换新日志重试。

持久化要求从Application开始的lazy Locator，拒绝捕获Element根或匿名函数根，避免重启后无法稳定表达目标。进程重启按新身份处理，同一请求ID与旧身份冲突时拒绝。普通应用使用NSRunningApplication启动时间；未注册的accessory进程使用ps秒级启动时间与可执行路径，无法保证极端同秒PID复用，不能冒充高精度身份。

`recover(id, target, postcondition=..., action=..., timeout=...)`只观察，返回RECOVERY_OBSERVED不等于原动作成功或本次确认，不再派发。CLI `verified-action --journal 私有路径 --operation-id 请求ID` 可使用同一日志防重。恢复apply时action必须使用原始`{"kind":"fill","value":"hello"}`等描述及原条件。已关闭session不执行新输入。

## 统一保护入口

`session.apply(target, kind, value=..., postcondition=..., operation_id=...)`支持fill/check/numeric/select/tab/choose，和execute共用窗口范围、协作锁、弹窗与可选profile/日志。fill/check/numeric缺省条件仅确认字段/控件值，不确认业务联动；select/tab/choose要求调用方明确独立条件。多步菜单操作在每步前重查保护，不保证原子回滚；中途失败保留不确定性，不重复整组输入。

原始Element/Control接口继续存在，不自动获得session保护；其他程序也可直接操作UI，协作锁不是系统独占锁。

## Profile

```python
from pymacauto import AppProfile
profile = AppProfile({
  "bundle_id":"com.example.demo", "version":"1.0", "build":"1",
  "window":{"identifier":"example.window"},
  "controls":{"input":{"identifier":"example.input","role":"AXTextField"}}
})
report = profile.require(app)
# 或app.session(..., profile=profile)，每次操作前校验
```

identity不匹配拒绝结构查询，命名控件须唯一。报告只含命名项、角色、错误类型和摘要；不输出值。`AppProfile.diff(before,after)`指出失配项，不自动修复选择器或放宽唯一性。仅资格检查，不等于动作验证。profile/hash绑定已配置结构，而非所有隐藏页面。

## 有界表格采集

`collect_pages(read_page, advance, key_columns=[...], max_pages=..., max_rows=..., timeout=...)`要求显式回调。read_page使用严格read_table；advance只在当前页面重读稳定后调用，返回严格bool。表头漂移、重复/重叠键、数据变化、预算/超时拒绝；达到页数预算不额外导航。原始行保留，返回EXPLICITLY_VISITED_PAGES_ONLY及global_complete=false。

advance可能改变UI，授权及恢复由调用方承担；本库不猜测滚动坐标/分页按钮，不证明未暴露行完整性，也不支持重叠滚动自动拼接。

## 测量与故障验收

操作回执含preflight/intent/dispatch/observation分阶段耗时。`with AXMetrics(app.backend) as metrics:`显式统计原生方法调用数/累计时间；不记录参数值，仅用于独占诊断，不与其他线程共享该backend。统计get_many及内部get不可简单相加为真实RPC数。

`python scripts/native_soak.py --installed --rounds 3 --output private-new.jsonl`重复自建AppKit验收，逐轮fsync并检查夹具回收。运行轮数可配置；最终安装版已完成三轮，每轮全部PASS且回收夹具；三轮短测不等于全天连续稳定。SIGKILL测试在真实子进程、合成AX后端上覆盖PREPARED/意图后/动作后，不冒充真实交易故障测试。

所有自动修改验收均使用自建AppKit夹具。同花顺只做profile资格及表格只读比较，不提交/撤销订单。
