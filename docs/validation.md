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
uv pip install --python .venv-check/bin/python dist/pymacauto-0.5.0-py3-none-any.whl
.venv-check/bin/python -m unittest discover -s tests -v
.venv-check/bin/python tests/native/smoke.py --backend-checks
.venv-check/bin/python scripts/native_check.py --installed
.venv-check/bin/python scripts/native_performance.py --installed
.venv-check/bin/pymacauto doctor
```

`--installed` 禁止源码路径注入，基础夹具还核查 SDK 与 CLI 都从独立环境导入。原生运行完整原始记录保留在操作者私有目录，不作为公开发行物。

## 0.5.0 安装版验收

- Mac独立环境Python3.12/PyObjC13：171项逻辑及10项桥接契约测试通过。
- 三轮真实AppKit闭环均PASS，包含持久化重开、统一保护填写/勾选/数值、事件、模态阻止、跨进程锁；全部夹具回收、前台保持。此为短测，不是全天持续运行。
- 真实子进程SIGKILL覆盖PREPARED/派发意图后/动作后；UI为明确标记的合成后端，不把它称为真实交易崩溃实验。
- 原生100×5表格严格读取/行选择及显式双页200行采集通过；三组交错查询全部数据摘要相同。
- 同花顺当前持仓9行×15列与前身原始值精确相同，零UI动作；版本profile资格检查通过。未提交/撤销订单。
- 已有库缺操作表、阶段/回执矛盾、日志写入失败、请求ID冲突、进程身份变化、菜单中途sheet均含拒绝回归。
- 保护填写原生诊断样本preflight约11ms、派发约1.5ms、结果观察约4ms；包含294次get与1次set，说明保护成本可观测，不作为任意应用时延承诺。

## 0.4.0 候选扩展

原生基础夹具新增复选/单选/滑块/popup/页签、真实AXObserver通知、三组交错事件/轮询值相等、未知sheet禁止输入、可复用会话重复ID和跨进程锁排他、verified-action命令。原生100×5表格新增严格read_table与行选择验证。最终安装版通过148项逻辑回归、10项桥接契约测试，以上原生门均PASS；前台保持、夹具进程回收。真实NSTableView单元格角色为AXCell，行选择实际读回通过。

事件样本尚无稳定延迟优势；会话复用与新CLI进程启动按相同值读回测量，不混同切页耗时。最终三轮复用读值为2.75/2.88/2.92ms，新进程为251/246/266ms；仅为自建小窗口的读值成本。0.4.0同花顺当前持仓只读对照9行×15列，与前身全部值精确相同、零UI动作。未做全天持续运行或实盘提交测试。

## 已执行范围

0.3.0 最终执行代码在 Mac Studio ARM64、Python3.12、PyObjC13通过123项逻辑及10项桥接契约回归、安装包原生基础闭环和100×5双页测试。SDK与CLI均从独立虚拟环境导入。安全字段原始文本读取拒绝、窗口重建范围等待、配置输入拒绝及输出文件保护均含回归；未以跳过校验换取通过。

安装版0.3.0与前身0.2.0a6在同花顺5.3.5/build7.0.62的同一当前持仓页只读对照：8行×15列，表头与全部单元格精确相等、摘要相同，零UI动作且前台保持。该对照不代表整个同花顺或任意版本已支持。

前身另有当前卖出表单的三个字段AXValue写入/延迟读回/恢复验收；它不是0.3.0重新执行真实交易输入的证据。没有执行订单提交、撤单或认证测试。历史性能数据不是当前版延迟承诺，宿主负载与目标应用行为都会影响结果。
