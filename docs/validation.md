# 验证说明

## 验证层次

1. `tests/test_*.py`：替身后端逻辑回归，不冒充真实 AX。
2. `tests/native/smoke.py --backend-checks`：原生桥接契约及异常边界隔离测试，不操作用户应用。
3. `scripts/native_check.py --installed`：自建 AppKit 窗口真实 AX 操作；检查安装路径、SDK/CLI 写入读回、按钮后置条件、标签字段、私有输出、前台保持和子进程回收。
4. `scripts/native_performance.py --installed`：自建100行×5列双页，交错三组通用遍历/限定查询，逐单元格校验；另检查 JSON 配置、CLI 切页和独立页面检测。该脚本的值采样不等于严格 read_table 的任意结构适配测试。

原生脚本会启动自己拥有的 AppKit 测试窗口，不会操作交易应用。需要 Swift 编译器及已授权的 Python 宿主。GitHub hosted CI 只执行可隔离回归，不拥有用户应用或辅助功能授权。

## 复跑

在 macOS 仓库根目录：

```bash
uv build
uv venv --python 3.12 .venv-check
uv pip install --python .venv-check/bin/python dist/pymacauto-0.3.0-py3-none-any.whl
.venv-check/bin/python -m unittest discover -s tests -v
.venv-check/bin/python tests/native/smoke.py --backend-checks
.venv-check/bin/python scripts/native_check.py --installed
.venv-check/bin/python scripts/native_performance.py --installed
.venv-check/bin/pymacauto doctor
```

`--installed` 禁止源码路径注入，基础夹具还核查 SDK 与 CLI 都从独立环境导入。原生运行完整原始记录保留在操作者私有目录，不作为公开发行物。

## 已执行范围

0.3.0 最终执行代码在 Mac Studio ARM64、Python3.12、PyObjC13通过123项逻辑及10项桥接契约回归、安装包原生基础闭环和100×5双页测试。SDK与CLI均从独立虚拟环境导入。安全字段原始文本读取拒绝、窗口重建范围等待、配置输入拒绝及输出文件保护均含回归；未以跳过校验换取通过。

安装版0.3.0与前身0.2.0a6在同花顺5.3.5/build7.0.62的同一当前持仓页只读对照：8行×15列，表头与全部单元格精确相等、摘要相同，零UI动作且前台保持。该对照不代表整个同花顺或任意版本已支持。

前身另有当前卖出表单的三个字段AXValue写入/延迟读回/恢复验收；它不是0.3.0重新执行真实交易输入的证据。没有执行订单提交、撤单或认证测试。历史性能数据不是当前版延迟承诺，宿主负载与目标应用行为都会影响结果。
