# pymacauto

用 Python 通过 macOS 公开的 Accessibility（AX）API 定位控件、读取数据、设置普通输入框，以及验证页面切换。

面向需要**可解释的定位、原样数据和明确失败状态**的本机自动化脚本。无需截图识别，不注入全局鼠标或键盘事件，也不绕过系统权限。

> **当前不是自主交易系统。** 本项目不提供交易策略、下单风控、账户业务判断或无人值守交易保证。可选的同花顺适配仅是特定版本的查询示例，不代表整个应用已获支持。

## 0.7.0：统一保护与配置诊断

受保护切页、Profile层级路径/动作及可写属性资格、只读定位助手和总预算已通过Mac安装版验收：263项回归、10项桥接契约、完整原生控件/切页及两小时持续运行通过。长测完成3416次自建窗口操作与118次同花顺只读采集，不涉及订单提交或撤销。详见[接口用法](docs/qualified-workflows.md)和[验证范围](docs/validation.md)。

## 0.6.0 层级定位与最后派发检查

新增按AX类型、直接子层级和index定位，支持expected_count/verify及JSON路径；新增意图提交后的最后检查、协作停止、日志身份保护和只读诊断。详见[层级定位指南](docs/hierarchical-locators.md)。

## 0.5.0 持久化与有界工作流

新增私有SQLite意图日志、重启只读恢复、统一保护apply、版本结构profile、有界页面采集和阶段指标。详见[持久化工作流](docs/durable-workflows.md)。

## 0.4.0 可靠操作扩展

新增单次派发＋独立条件核验、未知模态窗口保护、协作串行会话、重复ID防重派发、常用控件和AXObserver事件辅助等待。Mac独立安装版148项逻辑回归、10项桥接契约及原生闭环通过。详见[可靠操作指南](docs/reliable-operations.md)。原始SDK方法保持兼容；保护入口是显式选择，不能防止其他程序操作同一应用。

## 能做什么

- 按应用身份、窗口和 AX 属性定位控件；支持链式查询、正则、等待与歧义拒绝。
- 查看当前暴露的控件结构、可用动作和属性写入能力。
- 对符合严格结构要求的 `AXTable` 原样读取表头与单元格，校验行列关联和两次完整读取的一致性。
- 设置普通输入框并精确回读 `AXValue`；通过调用方配置的表格与表头指纹确认页面切换。
- 使用一次性 JSON CLI；修改命令必须显式传入 `--execute`。

AX 不暴露的数据无法由此库补全。控件虚拟化、画布、自绘表格、后台动作无效等情况仍可能无法处理；详见[能力边界](docs/limitations.md)。

## 安装

运行环境：**macOS、Python 3.10+、PyObjC**。目标应用须已运行，并提供可用的 AX 接口。Linux 和 Windows 不是原生运行平台。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'git+https://github.com/NiuStar/pymacauto.git'
pymacauto --version
pymacauto doctor
```

Git 安装需要本机已安装 Git。发布或部署时，建议把 Git URL 固定到已验收的提交，而不是跟随分支最新版本。

### 辅助功能权限

在 **系统设置 → 隐私与安全性 → 辅助功能** 中，手动授权实际运行脚本的终端、Python 或宿主程序；具体归属以 macOS 显示为准，必要时重启该宿主。

`doctor` 与 `Application.is_trusted()` 默认不弹权限提示。只有显式调用 `pymacauto doctor --prompt` 或 `Application.is_trusted(prompt=True)` 才请求系统提示；提示本身不等于授权成功。本项目不修改 TCC 数据库、不要求关闭 SIP，也不提供权限绕过。

## Python：从只读开始

下列 `com.example.demo` 和控件标识都是**待替换的示例值**，不是系统内置应用或通用选择器。先用 `apps`、`windows`、`inspect` 发现自己的目标。

```python
from pymacauto import Application

print(Application.is_trusted())
print(Application.list_apps())

app = Application.connect(bundle_id="com.example.demo")
for window in app.windows():
    print(window.get("AXTitle"), window.get("AXIdentifier"))

window = app.window(identifier="example.main-window")
table = window.child_window(role="AXTable", identifier="example.items")
snapshot = table.read_table(timeout=15, max_cells=100_000)
print(snapshot["headers"])
print(snapshot["rows"])
print(snapshot["completeness_scope"])  # AX_EXPOSED_ROWS_ONLY
```

读取结果保留原始字符串，不将金额、日期或空字符串自动转换。`READ_OK` 且 `row_count == 0` 只表示当前 AX 表格暴露零行，**不表示没有业务记录**。

### 明确区分“已派发”和“已生效”

```python
# 仅在你已确认目标、允许修改该普通输入框时执行。
field = window.child_window(role="AXTextField", identifier="example.search")
field.set_edit_text("示例")  # 写入后自动精确回读 AXValue

# AXPress 成功只确认动作派发；另等一个可观察的结果。
window.child_window(role="AXButton", identifier="example.refresh").click()
window.child_window(identifier="example.status").wait(value="已更新", timeout=5)
```

Python SDK 的修改方法调用即执行，没有 CLI 的 `--execute` 开关。不要把 `click()` 返回成功或输入框回读一致，当成业务提交成功。

## CLI：先发现，再操作

```bash
pymacauto apps
pymacauto windows --bundle-id com.example.demo
pymacauto inspect --bundle-id com.example.demo --output inspection.json
pymacauto find --bundle-id com.example.demo --role AXButton --identifier example.refresh
pymacauto read-table --bundle-id com.example.demo \
  --window-identifier example.main-window --role AXTable \
  --identifier example.items --output items.json
```

`--output` 为结果创建新的 `0600` JSON 文件，已有路径会被拒绝，适合避免把原始数据写入终端日志；它不保证预先存在的父目录是私有目录。诊断结果也可能包含窗口标题等敏感元数据，请勿直接公开上传。

需要改变 UI 时，先检查目标，再显式授权：

```bash
pymacauto click --bundle-id com.example.demo \
  --identifier example.refresh --execute
```

更多命令、按标签填写、页面配置和错误处理见[使用指南](docs/usage.md)。

## 示例与验证

| 入口 | 用途 |
| --- | --- |
| [examples/quickstart.py](examples/quickstart.py) | 默认列应用；按参数只读列窗口、读取指定表格 |
| [examples/pages.json](examples/pages.json) | 不绑定真实应用的双页面配置模板 |
| [examples/pages.py](examples/pages.py) | 默认识别当前页；切换须同时提供 `--to` 和 `--execute` |
| [docs/validation.md](docs/validation.md) | 单元测试、macOS 原生夹具、安装包验收与历史证据边界 |

0.3.0 执行代码已在 Mac Studio 的独立安装环境通过123项逻辑回归、10项桥接契约测试及真实AppKit填写/切页闭环；同花顺当前持仓页与前身只读对照精确一致。原生验证需要辅助功能授权，不代表任意应用或所有macOS版本通过；详见[验证说明](docs/validation.md)。

## 许可

[MIT](LICENSE)。
