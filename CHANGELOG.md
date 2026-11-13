# Changelog

## 0.3.0

首次公开的 `pymacauto` SDK 与 JSON CLI，源于内部 `macax` 实验版本；导入和命令名改用 `pymacauto`。

- 统一应用/窗口发现、链式定位、等待、原始值、严格表格与标签字段接口。
- JSON页面配置、指纹确认及一次派发后的只读等待。
- CLI新增windows、inspect、get-value、read-table、fill、page；变更需显式execute。
- 独占0600输出、安全字段文本读取保护、窗口重建重新定位及配置边界校验。
- 提供中文使用指南、能力边界、可运行示例与macOS回归工作流。

此版本不是自动交易系统；未发布到PyPI。源代码可从GitHub按提交安装。
