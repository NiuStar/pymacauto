# 可靠操作、控件与事件等待（0.4.0）

本版新增的是通用原语，不是交易流程。示例身份和选择器均需替换，先发现控件、确认权限和目标窗口，再明确授权修改。

## 单次操作与独立核验

```python
from pymacauto import Application, Condition

app = Application.connect(bundle_id="com.example.demo")
window = app.window(identifier="example.window")
button = window.child_window(identifier="example.apply")
ready = Condition(window.child_window(identifier="example.result"), value="完成")
with app.session(identifier="example.window") as session:
    receipt = session.execute(button, postcondition=ready,
                              operation_id="my-request-1", timeout=5)
    print(receipt)
```

- `NOT_DISPATCHED`：本次未进入派发调用，例如未知模态窗口、未明确启用、歧义、前置条件不满足或锁冲突。
- `DISPATCHED_UNCONFIRMED`：已尝试派发，但未确认后置条件。即使抛出原生错误也不能认定动作没发生。
- `CONFIRMED`：本次单次派发后观察到调用方指定的条件；不代表框架理解业务，更不证明该状态必然由本次动作造成。

`precondition=Condition(...)` 可设置前置状态；`action` 默认AXPress。输入只派发一次，后续只观察；超时不自动再次点击、不回滚、不抢焦点。未知sheet/模态窗口阻止派发，但应用仍可能在检查之后自行变化，AX并非原子事务。如果后置条件在派发前已经满足，保护入口拒绝派发，避免旧状态伪确认；调用方仍应使用足以区分本次请求的结果，例如版本号或请求编号，而不只是“完成”。

CLI：

```bash
pymacauto verified-action --bundle-id com.example.demo \
  --window '{"identifier":"example.window"}' \
  --target '{"identifier":"example.apply"}' \
  --expect '{"identifier":"example.result"}' --expect-value 完成 --execute
```

未确认时该命令退出码为1，明确错误为2；读取`result.status`，不要将外层JSON成功编码当业务完成。

## 会话的保证范围

会话复用已有Application/解释器，不启动守护进程、不改变生产服务。一个session中的操作串行；其他线程、session或进程通过此受保护入口操作同一PID时，应用锁冲突会拒绝而不是排队误执行。底层`click`、`Control`和其他程序并不受该协作锁强制控制，macOS也不提供独占UI所有权。

同一session内重复`operation_id`返回原回执、不重复派发；不要把同一ID用于不同意图。最多保留1024个指定ID，达到容量后拒绝新执行，不淘汰旧ID后悄悄重放。0.4.0仅为内存防重；0.5.0可选journal提供跨会话意图保留，见[持久化工作流](durable-workflows.md)，仍不承诺业务恰好一次。`close()`不退出应用；已关闭会话拒绝新操作。操作记录不保存输入值或异常原文，只有类型、时长和阶段。

文件锁位于当前用户`~/Library/Caches/pymacauto/locks`，要求私有目录与安全普通文件。遇到权限/目录校验失败应检查原因，不自动放宽权限。

## 常用控件

```python
check = window.child_window(identifier="example.check").control()
check.set_checked(True)                 # 已勾选不重复切换
window.child_window(identifier="example.radio").control().select()
window.child_window(identifier="example.slider").control().set_numeric(7)
window.child_window(identifier="example.popup").control().choose("选项二")
window.child_window(identifier="example.tabs").control().select_tab("详情")
window.child_window(identifier="example.row").control().select()
```

每个方法核查角色和明确能力，修改后读回；可点击控件要求明确启用，行/单元格选择允许缺失AXEnabled但拒绝明确禁用，且要求AXSelected明确可写；混合/未知勾选状态、重复菜单或页签标题、缺失数值上下限均拒绝。滑块不隐式四舍五入，不能接受目标值则失败。菜单仅在目标popup暴露的子树内查找，不从应用其他菜单捡同名项；列表选择只支持公开可写AXSelected。菜单已展开但后续失败时不会盲目发送Escape。控件便利方法仍是低层修改入口，不自动加入session弹窗保护和协作锁。

## AXObserver与有界降级

```python
from pymacauto import Condition, wait_condition
observation = wait_condition(ready, timeout=5, fallback_interval=0.25)
# 或session.execute(..., events=True)
```

观察器注册公开AX通知，通知只唤醒状态检查、不作为成功凭证。不支持的通知记录到`unsupported`；仍进行有界低频轮询。返回`mode`、`events`、`checks`与耗时。原生权限/无效引用等错误不当作“不支持通知”吞掉。

低层`AXEvents`只能在创建它的线程上进入、等待和关闭；使用with保证移除runloop source及通知。窗口重建可能导致旧通知目标失效，条件Locator仍重新查询，回退轮询补足未收到通知的情况。未收到通知不证明应用没有变化。时间预算是观察预算，不是同步AX调用的硬中止。

## 表格扩展

在原有直接AXStaticText之外，严格读取支持`AXCell -> 唯一AXStaticText`。不拼接多个文本节点，不猜测其他嵌套层次；双读、索引和行列轴引用校验保留。仍只声明`AX_EXPOSED_ROWS_ONLY`，本版不自动滚动、翻页或读取AXOutline。

## 已验证与未承诺

原生夹具验证勾选、单选、滑块、popup、页签、单次操作、未知sheet阻止输入、真实通知及跨进程锁冲突。100×5原生表格验证严格读取；同花顺仅进行授权的只读回归。

三组交错通知/轮询样本最终值完全一致，但小窗口检查耗时占比较高，未得到稳定提速结论；不要将事件支持说成同花顺切页速度提升。没有24小时连续运行、实盘提交、滚动全量覆盖或后台服务验收。
