# 0.7.0 候选：受保护切页、能力资格与定位诊断

此页描述候选接口，不代表新版本已发布。完整原生验收、持续运行和发布状态见[验证说明](validation.md)。

## 受保护切页

```python
from pathlib import Path
from pymacauto import Application, PageSession
app = Application.connect(bundle_id="com.example.demo")
config = {...}  # 格式见 examples/pages.json；必须替换示例选择器
with app.session(**config["window"],
                 journal=Path.home()/".pymacauto-private/pages.sqlite",
                 stop=Path.home()/".pymacauto-private/STOP") as owner:
    pages = PageSession.from_config(app, config, operations=owner)
    result = pages.switch("details", operation_id="show-details-1", timeout=10)
    print(result["receipt"]["status"])
```

`PageSession.switch()`通过 `OperationSession` 单次派发；检查批准窗口、模态、控件唯一性和最后引用身份，再独立检测目标表格/表头。前置条件要求当前页属于配置中可识别的页面集合，并非锁定调用瞬间的某个源页面。默认不抢焦点、不用坐标、不重复点击。传入 `operations` 才能复用会话防重、日志、profile及停止源；不传则每次创建临时保护会话，不提供跨调用防重历史。

已在目标页且不指定 ID 时返回 `ALREADY_OBSERVED`；指定 ID 时保留 `NOT_DISPATCHED / observed=true / verified=false` 回执并绑定请求，表示无需输入，不声称本次派发导致该状态。历史不确定回执不得因当前页面相同而升级为成功。同一持久化 ID 改配置/目标会拒绝；请保留原日志并人工协调不确定结果。

```bash
pymacauto page --bundle-id com.example.demo --config pages.json --to details \
  --journal "$HOME/.pymacauto-private/pages.sqlite" --operation-id show-details-1 \
  --stop-file "$HOME/.pymacauto-private/STOP" --timeout 10 --execute
```

日志目录和父路径要求沿用[持久化工作流](durable-workflows.md)。观察式恢复不等于交易业务确认。

## 层级路径和能力资格

旧的扁平控件选择器继续可用。扩展控件项采用 `path/actions/settable`：

```python
from pymacauto import AppProfile
profile = AppProfile({
  "bundle_id":"com.example.demo", "version":"1.0", "build":"1",
  "window":{"identifier":"example.main"},
  "controls":{
    "apply":{
      "path":[{"relation":"descendant", "selector":{"role":"AXButton"},
               "index":0, "expected_count":2, "verify":{"identifier":"example.apply"}}],
      "actions":["AXPress"], "settable":[]
    }
  }
})
report = profile.require(app)
```

路径根限定在 profile 窗口，每次重新解析。`structure_match`区分结构匹配，`ability_qualified`表示满足**已声明**的能力要求；未声明要求不证明任何动作可用。`action_tested`固定为 false：查询 AXPress 是否存在，不会实际点击；可写属性也不证明业务接受。配置在构造时复制并校验，不能通过修改配置字典默默改变已有 hash。

## 只读定位助手

```python
locator = app.window(identifier="example.main").child(role="AXButton", index=0, expected_count=2)
print(locator.inspect_children())
print(locator.explain())
candidate = locator.export()
# 仍须独立验证身份、版本、唯一性及操作资格，才可用于输入
fresh = app.locator_path(candidate["path"])
```

```bash
pymacauto inspect-children --bundle-id com.example.demo --role AXWindow
pymacauto explain-locator --bundle-id com.example.demo --path "$(< locator.json)"
pymacauto export-locator --bundle-id com.example.demo --path "$(< locator.json)"
```

`--path`是内联 JSON 路径数组；文件可通过 shell 的 `--path "$(< locator.json)"` 传入。`inspect-children`仅列直接子控件的结构信息；`explain-locator`逐层列候选数、index/count/verify结果，预算不足、歧义、变化不算完整唯一结果；`export-locator`只导出候选，不派发、不授权、也不替代 qualification。诊断不读取 AXValue，拒绝含值条件的路径。导出的显式 title/identifier 仍可能敏感，不能随意公开。捕获原生引用根不能导出为持久化应用根路径。

## 总预算和错误

保护操作将剩余预算传入内部核验及外层观察，过期后停止后续输入，不为每阶段重新提供完整 timeout。回执给出 `error_stage`、`error_category`，原生错误另保留 `native_error.operation/code`。停止和结构变化分别为 `STOPPED`、`LAYOUT_CHANGED`。

`timeout=0`保留不等待语义，允许一次即时派发/检查；不是零成本或硬取消。同步原生 AX RPC、文件系统提交、锁等待不能被 Python 预算立即中断。已派发后超时是结果不确定，禁止自动重试。

## 持续验收

```bash
.venv-check/bin/python scripts/native_endurance.py --seconds 7200 --interval 2 \
  --allow-ths-read --ths-interval 60 --output private-new-endurance
```

该命令启动自建窗口，只修改它自己的字段并循环创建/关闭观察器。显式 `--allow-ths-read` 才低频读取同花顺**当前页**；不会激活、切页、提交或撤单。每次表读取仍执行严格双读与关联校验。记录原始行摘要而非账户内容，采样 RSS/FD/线程，资源门或前台变化时失败停止；新输出目录必须不存在。实际运行时长、循环数、同花顺读数及夹具回收以持久化终态为准，短测不能证明数小时稳定。
