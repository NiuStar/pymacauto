# 使用指南

## 1. 先检查环境与应用身份

```bash
pymacauto --version
pymacauto doctor
pymacauto apps
```

`doctor` 默认只检查，不弹权限框。需要请求系统提示时显式使用 `doctor --prompt`，并在系统设置中完成授权。目标应用需要已经运行；本库不负责启动、登录或解锁应用。

Python 中的对应入口：

```python
from pymacauto import Application

trusted = Application.is_trusted(prompt=False)
apps = Application.list_apps()
app = Application.connect(bundle_id="com.example.demo")
# 也可改用 name="Example" 或 pid=调用方已确认的进程号；三选一。
```

示例中的应用身份、窗口标识、控件标识和表头都必须按实际目标替换。`name` 是精确匹配，不保证唯一；多实例时使用已确认的 `pid`。PID 需为正的有符号 32 位整数，不能是布尔值。连接仅确认当前应用身份与 AX 访问条件，不代表每个窗口或功能都可自动化。

## 2. 发现窗口与控件

```python
for window in app.windows():
    print(window.get("AXTitle"), window.get("AXIdentifier"))

inspection = app.inspect(max_nodes=5000, max_depth=40, timeout=45)
print(inspection["complete"], inspection["limits_hit"])
```

`inspect()` 读取结构、元数据、动作和可写能力，不主动读取 `AXValue` 或选中文本，也不展开 Apple 系统菜单。标题、帮助等元数据仍可能敏感。`complete=True` 只指本次有界关系图未遇到错误/限制，**不是遍历了应用所有页面**。诊断节点序号和路径不是持久控件 ID，`candidate_selector` 也不是写操作授权。

```bash
pymacauto windows --bundle-id com.example.demo
pymacauto inspect --bundle-id com.example.demo --output inspection.json
pymacauto tree --bundle-id com.example.demo --output tree.json
```

`tree`、`find`、`Element.info()` 可能读取普通控件的值；排查结构时优先用 `inspect`。不要公开上传未经脱敏的诊断文件。

## 3. Locator、Element 与查询范围

### 链式定位

```python
window = app.window(identifier="example.main-window")
refresh = window.child_window(role="AXButton", identifier="example.refresh")
refresh.wait(timeout=5, enabled=True)
print(refresh.info())
```

- `Locator` 保存选择条件，在 `resolve()`、读取或操作时重新查询；不是持久缓存。
- `resolve()` 返回 `Element`，即本次查询的原生引用。页面重建后应重新定位，不要跨页面长期保存它。
- `child_window()` 是历史兼容命名：查找范围中的**递归后代**，不限于窗口，也不是只查直接子节点。
- 单目标查询必须恰好匹配一个；零个报缺失，多个报歧义，不会默认取第一个。
- 严格查询超出节点/深度预算报错，不用截断结果证明唯一。

可用选择字段：`role`、`subrole`、`title`、`identifier`、`description`、`help`、`value`、`enabled`。除 `enabled` 外可使用对应的 `*_re` 正则字段；正则使用搜索匹配，若需全匹配请自行加 `^` 和 `$`。多个条件为 AND。`enabled` 必须是布尔值；字符串与数值不相互转换，布尔值不视为数字。

```python
buttons = window.resolve().descendants(role="AXButton")
direct_groups = window.resolve().children(role="AXGroup")
match = window.child_window(role="AXTextField", identifier_re=r"^example\.filter\.")
```

`Element.children()` 仅检查直接子节点；`Element.descendants()` 递归搜索当前引用的后代。已有 `Element` 的 `child_window()` 仍在这个引用下发起新查询；它不能把失效的父引用自动恢复成新窗口。

### 结构查询与表格数据分开

大表格可能使全应用递归定位成本很高。可以显式从顶层 `AXWindows` 中选定唯一窗口，再把数据控件设为结构搜索边界：

```python
from pymacauto import window_scope

scope = window_scope(
    app, identifier="example.main-window",
    leaf_roles=("AXTable", "AXList", "AXOutline"),
)
table = scope.find(role="AXTable", identifier="example.items")
snapshot = table.read_table()
```

`QueryScope(app, root, leaf_roles=...)` 也可直接指定原生根引用。边界节点本身参与匹配，其后代不搜索；这只是在声明范围，不能声称已搜索边界内部。需要寻找表格内部控件时，使用另一个未裁剪的范围。每次查询重新遍历，不维护跨页面索引。

### 等待与缺失

```python
status = window.child_window(identifier="example.status")
status.wait(timeout=5, interval=0.1, value="已更新")
window.child_window(identifier="example.loading").wait(state="gone", timeout=5)
```

`exists()` 仅把 `ElementNotFound` 转为 `False`；歧义、权限和原生错误仍抛出。`wait(state="gone")` 不接受额外状态条件。等待超时是轮询预算，不是取消一个已进入的同步原生调用的硬期限。

## 4. 严格读取 AXTable

```python
snapshot = window.child_window(
    role="AXTable", identifier="example.items"
).read_table(max_cells=100_000, timeout=15)
```

也可直接调用 `read_table(app.backend, table_ref, **limits)`。结果包括：

| 字段 | 含义 |
| --- | --- |
| `status` | 成功时为 `READ_OK` |
| `headers` | 原始顺序、非空且不重复的表头字符串 |
| `rows` | 按表头关联的原始单元格字符串字典列表 |
| `row_count` / `column_count` | 当前 AX 暴露的形状 |
| `stable_double_read` | 两次完整读取的表头和数据完全相同 |
| `row_column_crosscheck` | 行轴、列轴单元格原生引用关联通过校验 |
| `completeness_scope` | 固定为 `AX_EXPOSED_ROWS_ONLY` |
| `sha256` | 有序表头与原始矩阵的规范 JSON 摘要，不是整个返回对象的文件摘要 |
| `captured_at` / `elapsed_seconds` | 采集时间与本次读取耗时 |

当前严格读取器要求 `AXTable`、有序的列/行索引、可用的双轴数据与 `AXStaticText` 字符串单元格。原生引用身份使用包含 `CFEqual` 比较的键，不以哈希相同代替身份相同。结构不符、重复表头、单元格错位或两次数据不一致均失败，不返回部分表格冒充成功。

**零行有效，零列无效。** `READ_OK` 的空表仍须通过表头与结构校验；它不证明业务上没有记录。没有自动滚动、翻页或解除筛选，也不保证 AX 未声明的隐藏/虚拟行已全部读取。多张表之间没有原子快照保证。

## 5. 设置普通输入框与调用动作

```python
field = window.child_window(role="AXTextField", identifier="example.search")
receipt = field.set_edit_text("示例")
assert receipt["verified"]
```

`set_edit_text()` 只接受字符串，写后精确回读 `AXValue`；`set_value()` 还可设置有限 JSON 数值或布尔值。数值的 `int`/`float` 等值可相等，布尔值不与数字等同。禁止安全密码框自动化，禁用控件拒绝写入。不是所有控件都支持 `AXValue` 写入。

回读不一致抛 `VerificationFailed`。这意味着写入可能已派发，**不要盲目重试**。回读一致只确认 AX 属性，不确认输入事件、校验回调、搜索执行或业务提交。

```python
button = window.child_window(role="AXButton", identifier="example.refresh")
receipt = button.click()  # AXPress
# receipt 为 effect="unverifiable", verified=False：不是页面成功凭证。
window.child_window(identifier="example.status").wait(value="已更新", timeout=5)
```

`perform("AXIncrement")` 等动作必须由目标明确暴露。没有隐式坐标点击、回车、Tab、剪贴板粘贴或全局按键回退。

### 按标签关联输入框

有些应用不给输入框标识，但把静态标签与输入框放在同一个父容器中：

```python
form = window.child_window(role="AXGroup", identifier="example.form")
# 每次写入前重新查询容器、标签与字段；不要复用上次返回的 Element。
field = form.labelled_field("搜索词", alignment_tolerance=8, max_gap=220)
field.set_edit_text("示例")
```

这是**基于 AX 几何的辅助关联**，不是应用提供的语义标签关系。只检查指定容器的直接子节点：唯一 `AXStaticText` 标签，右侧同一行唯一 `AXTextField`；位置与尺寸必须有效，垂直中心差及水平间距必须满足显式限制。`alignment_tolerance`、`max_gap` 使用 AX 几何坐标单位。缺失、歧义、只读、未明确启用或安全字段均拒绝。

兼容入口 `labelled_field(app, root, label, **layout_options)` 和 `Element.labelled_field(...)` 仍可用。返回的是当次 `Element`；调用方必须在每次写入前重新关联。不要将这一启发式扩展为提交表单授权。

## 6. 配置页面识别与验证切换

[examples/pages.json](../examples/pages.json) 是通用模板，需替换为目标应用的窗口、按钮、表格标识和表头。最小结构：

```json
{
  "window": {"identifier": "example.main-window"},
  "pages": {
    "details": {
      "trigger": {"role": "AXButton", "identifier": "example.page.details"},
      "table": {"role": "AXTable", "identifier": "example.details"},
      "headers": ["编号", "名称", "状态"]
    }
  }
}
```

如果要从另一页切入，另一页也须有配置：`switch()` 先确认一个已知当前页与目标触发器，不会在未知页面盲点。表头指纹按**集合包含**匹配：配置表头须全部存在于实际表头，允许额外列；若需严格顺序和完整 schema，请再自行比较返回的 `headers`。指纹应能区分页面，多页同时匹配会拒绝。

```python
import json
from pathlib import Path
from pymacauto import Element, PageSession

config = json.loads(Path("examples/pages.json").read_text(encoding="utf-8"))
session = PageSession.from_config(app, config)
current = session.detect()            # 只读识别；不存在已知页时抛错
observed = session.switch("details")  # 必要时派发一次 AXPress，再等目标指纹
snapshot = Element(app, observed["table"]).read_table()
```

`detect()`、`wait(page=None, timeout=..., interval=...)`、`switch(name, timeout=...)` 返回至少含 `page`、`table`、`headers` 的字典。`table` 是刚确认的原生引用，可立即读取，不应直接 JSON 序列化或跨切页缓存。已在目标页时不重复点击；切换后的等待仅重试只读观察，不重复派发输入动作。确认失败不自动回滚页面。

可选配置：

- `leaf_roles`：默认 `AXTable`、`AXList`、`AXOutline`，只限制结构搜索展开范围。
- `content_path`：从窗口开始的选择器数组，每一级只在当前节点的直接子节点中唯一匹配，用于限定页面内容容器。省略表示在窗口范围内查找。
- `trigger_children_only`：默认 `false`；设为 `true` 时，触发器必须是窗口直接子节点，不在 `content_path` 的终点下寻找。

也可用 `PageSession(app, window=..., pages=..., leaf_roles=..., content_path=..., trigger_children_only=...)` 直接构建。通用页面 API 不主动激活应用，但目标应用可能因 AX 动作自行改变前台；后台动作无效时不会自动升级为前台或全局输入。

## 7. CLI 速查

每条目标命令用 `--pid`、`--bundle-id`、`--name` 三选一。普通控件选择器使用 `--role`、`--subrole`、`--title`、`--identifier`、`--description`、`--ax-help` 及对应 `-re` 选项；`--ax-help` 避免与 CLI 帮助混淆。具体参数以 `pymacauto <命令> --help` 为准。

| 命令 | 行为 |
| --- | --- |
| `doctor` / `apps` | 环境与权限检查 / 列已运行应用 |
| `windows` / `tree` / `inspect` | 列窗口 / 普通树 / 不读取值的结构诊断 |
| `find` / `get-value` | 唯一定位并输出信息 / 读取目标的 AXValue |
| `wait` | 等存在、消失或字符串值 |
| `read-table` | 严格读取指定 AXTable |
| `click` / `action` / `set-value` | 派发动作或设置值；必须 `--execute` |
| `fill` | 指定窗口和标签，关联普通字段并写入回读；必须 `--execute` |
| `page` | 加载页面配置并切换；必须 `--execute` |

```bash
pymacauto get-value --bundle-id com.example.demo \
  --window-identifier example.main-window --identifier example.search
pymacauto wait --bundle-id com.example.demo \
  --identifier example.status --value 已更新 --timeout 5
pymacauto set-value --bundle-id com.example.demo \
  --identifier example.search --value 示例 --execute
pymacauto action --bundle-id com.example.demo \
  --identifier example.stepper --action AXIncrement --execute
pymacauto fill --bundle-id com.example.demo \
  --window-identifier example.main-window --label 搜索词 --value 示例 \
  --alignment-tolerance 8 --max-gap 220 --execute
pymacauto page --bundle-id com.example.demo \
  --config examples/pages.json --to details --execute
```

`fill` 的 `--window-identifier` 和 `--label` 必填，标签与字段必须满足同父容器等约束；如表单嵌套在独立容器中，用 Python 指定容器。`get-value`、`read-table` 可用 `--window-identifier` 限定顶层窗口。`set-value --json-value` 可传 JSON 标量，例如 `--json-value false`；不是字符串自动解析。

常规成功输出为 `{"ok": true, "result": ...}`，常规失败为 `{"ok": false, "error": "异常类型", "message": "..."}`。常规成功退出码为 `0`，`doctor` 未就绪为 `1`，已处理的操作错误为 `2`；参数错误由 argparse 处理，不保证 JSON。成功的 `click` 输出仍可包含 `verified=false`，外层 `ok` 不代表业务效果确认。

`--output 文件名` 可用于保存 JSON，示例使用子命令后置形式。它独占创建新文件并设 `0600` 权限，拒绝已有路径，不为已有父目录提供隐私保证。使用自己控制的私有目录；终端、重定向、备份和版本库也要纳入数据保密范围。

## 8. 运行示例

以下命令须在克隆的仓库根目录运行，先安装库并替换模板标识：

```bash
python examples/quickstart.py
python examples/quickstart.py --bundle-id com.example.demo
python examples/quickstart.py --bundle-id com.example.demo \
  --window-identifier example.main-window --table-identifier example.items
python examples/pages.py --bundle-id com.example.demo --config examples/pages.json
python examples/pages.py --bundle-id com.example.demo --config examples/pages.json \
  --to details --execute --read-table
```

两个示例默认只读。`pages.py` 仅在 `--to` 与 `--execute` 同时出现时允许切换。`--read-table` 会把原始行输出到标准输出；含敏感数据时优先用支持私有文件输出的 CLI，且不要把输出提交到仓库。

## 9. 失败处理

| 异常 | 处理方向 |
| --- | --- |
| `PlatformError` | 改在 macOS 与受支持 Python/PyObjC 环境运行 |
| `PermissionDenied` | 手动检查运行宿主的辅助功能授权 |
| `ElementNotFound` | 检查当前窗口、页面、筛选与选择器 |
| `AmbiguousMatch` | 缩小范围、增加稳定属性；不要取第一项 |
| `SearchLimitExceeded` | 缩小窗口/容器范围，明确数据边界；必要时再调整预算 |
| `AttributeUnsupported` | 目标未提供该属性，不把它当空数据 |
| `AXError` | 保留 `operation` 和 `code`；页面重建后重新做只读定位 |
| `WaitTimeout` | 未观察到条件；排查当前状态，不直接重放动作 |
| `UnsafeOperation` | 检查安全字段、禁用/只读状态、动作能力与 CLI 授权 |
| `VerificationFailed` | 写入可能已发生；先只读确认，不盲目重试 |
| `MacAXError` 表格错误 | 保留结构/一致性错误，不输出部分结果冒充完整读取 |

对动作建立调用方自己的前置条件、后置条件与人工授权。权限失败、歧义、读取失败或超时，都不是扩大操作范围、抢焦点或绕过安全检查的理由。
