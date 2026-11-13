# 层级定位、安全检查与诊断（0.6.0）

## 类型、直接子层级与index

AX控件类型使用`role`（如AXButton、AXTextField、AXGroup），细分类型用`subrole`。属性可与title/identifier/help等组合，不必依赖显示名称。

```python
from pymacauto import Application
app = Application.connect(bundle_id="com.example.demo")
window = app.window(identifier="example.window")
container = window.child(role="AXGroup", index=0, expected_count=2)
button = container.child(role="AXButton", index=1, expected_count=3,
                         verify={"identifier":"example.apply"})
print(button.info())
```

- `child()`只查当前父容器的直接AXChildren；每次操作重新解析整条路径。
- index从0开始，在**当前父容器按selector过滤后的结果**中计数，不是全局树序号，也不是原生AXIndex属性。
- `expected_count`检查过滤后的候选数；数量不符、index越界、目标verify不符即失败。`verify`是在选定index后检查，不参与排序或候选计数。
- 不传index仍要求唯一匹配。负数、布尔、浮点index拒绝。
- `child_window()`保持旧语义：递归搜索后代。它不能替代直接child层级。
- Element.child仍绑定当次父引用；要跨重建重定位，优先从Application开始。

受保护session执行带index的路径必须提供每一步的expected_count。数量相同也可能换序，建议加verify或稳定identifier。对于完全无标识的同类型控件，index只能表达结构位置，**不能保证布局改变后仍是同一语义按钮**。版本/profile、前后置条件仍必需，不可把裸index当永久句柄。

## JSON层级路径

```python
path = [
  {"relation":"window", "selector":{"identifier":"example.window"}},
  {"relation":"child", "selector":{"role":"AXGroup"},
   "index":0, "expected_count":2},
  {"relation":"child", "selector":{"role":"AXButton"},
   "index":1, "expected_count":3,
   "verify":{"identifier":"example.apply"}}
]
button = app.locator_path(path)
```

relation支持：`window`（仅应用根AXWindows）、`child`（直接AXChildren）、`descendant`（有界递归）。每层必须唯一或显式指定index，禁止未知配置字段；节点/深度限制不会静默截断。路径保存选择规则，不缓存原生引用。

```bash
pymacauto find --bundle-id com.example.demo --path '[{"relation":"window","selector":{"identifier":"example.window"}},{"relation":"child","selector":{"role":"AXButton"},"index":1,"expected_count":3,"verify":{"identifier":"example.apply"}}]'
```

`--path`可用于find/get-value/read-table/wait/click/set-value/action；不能与扁平选择器或window-identifier混用。写入仍需execute。verified-action的target/expect也可同时传完整path数组，日志指纹包含层级、index、候选数与verify。

控件层级不等于业务先后顺序：先展开菜单/切页，再等待对应状态，之后重新定位下一级。不要预先解析尚未出现的按钮并缓存引用。菜单的后置条件、流程授权由调用方提供。本版仍不隐式使用屏幕坐标点击或全局键盘。

## 最后派发检查与停止

保护入口在日志意图提交后、真正派发前，再检查进程/窗口、模态状态、目标引用、前后置条件。替换控件不能自动作为原控件继续执行。多步控件每次输入前也重查，失败不重复整组操作。

```python
import threading
stop = threading.Event()
with app.session(identifier="example.window", stop=stop) as session:
    # stop.set()之后拒绝新输入；也可传Path作为存在即停止的文件标志
    ...
```

停止也进入事件/轮询观察；已经进入的同步AX调用不能硬取消。检查与原生调用不是原子操作，其他软件仍可直接改变界面。日志意图已落盘但最终检查拒绝时，保留不确定/恢复要求，不换ID盲重试。

## 日志文件保护

日志保留父目录链、数据库及锁文件描述符，SQLite打开前后和每次边界检查身份；拒绝符号链接祖先、辅助文件符号链接、目录/文件替换、不安全权限。初始化由稳定协作锁串行；锁等待有界。macOS的/var是符号链接，请使用明确真实路径（例如调用者自己创建的临时目录可resolve），框架不会默默追随路径别名。

SQLite仍按路径执行部分系统调用。相同用户的恶意进程在检查间隙替换再还原并不能由此完全防御；这是错误/竞态检测，不是抵抗同用户攻击的沙箱。只读审计只接受干净rollback数据库；WAL/hot journal须由操作者处理，不自动恢复写盘。

## 便捷诊断

```bash
pymacauto journal-inspect --journal /private/path/operations.sqlite
pymacauto profile-check --bundle-id com.example.demo --config profile.json
pymacauto profile-diff --before before.json --after after.json
pymacauto journal-observe --bundle-id com.example.demo \
  --window '{"identifier":"example.window"}' \
  --target '{"identifier":"example.apply"}' \
  --expect '{"identifier":"example.result"}' --expect-value 完成 \
  --journal /private/path/operations.sqlite --operation-id request-1 --timeout 2
```

journal-inspect和journal-observe不创建日志/目录/辅助文件，不派发输入；audit只输出opaque ID、请求指纹和阶段状态。observe必须与原始请求描述一致，观察到结果也不提升为因果确认。profile-check不匹配退出1，不自动修复配置；diff输出命名控件差异。私有输出可用--output独占0600文件。

## 同进程持续运行与性能

```bash
PYMACAUTO_SOAK_CYCLES=100 PYMACAUTO_SOAK_SECONDS=60 \
PYMACAUTO_SOAK_INTERVAL=0.1 python scripts/native_check.py --installed
```

同一进程/应用连接/session持续循环填写，每轮重新解析层级并创建关闭观察器，采样RSS、线程和FD数，最终验证停止拒绝、前台和夹具回收。工具每轮使用autorelease pool并周期GC；真实长期宿主应自行管理运行循环和内存，不把短测当永久无泄漏保证。seconds最长86400；外层执行工具须提供足够总超时。日志为自建夹具值，不操作同花顺交易。默认短测不代替全天稳定性。

查询优化仅复用一次保护检查内部的角色/成员证据，后续操作和派发前检查仍重新获取；没有跨页缓存、取消唯一性或取消读回。本版额外最后检查增加保护成本，不承诺所有流程更快。
