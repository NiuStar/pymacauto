# Changelog

## 0.7.0

- PageSession切页共用OperationSession锁、日志、防重、模态、停止与独立页面指纹。
- AppProfile支持窗口内层级路径和声明的动作/可写属性能力检查，明确action_tested=false。
- inspect-children/explain-locator/export-locator只读SDK/CLI，不包含AXValue，不授权输入。
- 剩余总预算传入内部等待，回执区分错误阶段/类别并保留原生码。
- 持续运行工具将模块/夹具SHA、资源采样、只读同花顺当前页与回收结果持久化；两小时3416次自建字段操作、118次同花顺只读及完整原生控件/切页验收通过。

## 0.6.0

- child()/locator_path()按类型、父子层级、零基index、候选数和目标指纹定位；CLI支持path。
- 日志意图后重新检查目标/窗口/条件/模态与协作停止，不自动使用替换引用。
- 日志保留FD身份、路径/辅助文件校验、并发初始化协作锁和只读审计。
- journal-inspect、journal-observe、profile-check、profile-diff。
- 同进程循环、RSS/线程/FD采样及停止验收；查询局部复用不跨操作缓存。

## 0.5.0

- SQLite私有意图日志、请求HMAC、同ID冲突拒绝、损坏schema拒绝与只读恢复。
- session.apply统一填写/控件保护，多步输入前重查窗口和模态状态。
- 原生进程身份、AppProfile版本结构资格与脱敏差异报告。
- 显式有界collect_pages，严格拒绝重叠、变化和预算越界。
- 阶段耗时、AXMetrics与可配置原生重复运行工具。
- SIGKILL三处真实子进程故障测试，保留不确定性而不重放。

## 0.4.0

- 单次操作回执、显式前后置条件、未知模态窗口保护和verified-action CLI。
- 可复用协作串行session、进程间锁、会话内1024项指定ID防重派发。
- 角色校验控件：勾选、单选、数值、popup、页签和可写行选择。
- AXObserver线程归属注册/关闭、真实通知与有界轮询降级。
- 严格表格支持AXCell内唯一AXStaticText，保留双读及双轴校验。
- 原生夹具覆盖控件、通知、弹窗、会话与CLI。无实盘交易测试。

## 0.3.0

首次公开的 `pymacauto` SDK 与 JSON CLI，源于内部 `macax` 实验版本；导入和命令名改用 `pymacauto`。

- 统一应用/窗口发现、链式定位、等待、原始值、严格表格与标签字段接口。
- JSON页面配置、指纹确认及一次派发后的只读等待。
- CLI新增windows、inspect、get-value、read-table、fill、page；变更需显式execute。
- 独占0600输出、安全字段文本读取保护、窗口重建重新定位及配置边界校验。
- 提供中文使用指南、能力边界、可运行示例与macOS回归工作流。

此版本不是自动交易系统；未发布到PyPI。源代码可从GitHub按提交安装。
