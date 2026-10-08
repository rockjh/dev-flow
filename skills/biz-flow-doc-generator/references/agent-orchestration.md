# 代理编排与证据协议

## 两阶段角色和写入权

第一阶段的 CLI/协调者维护注册入口清单、模块归属、总览及 Markdown 清单骨架，不需要代理执行器。第二阶段按已确认入口创建只读分析任务，使用有界并发；每个模块绑定唯一写入者，等待所需入口结果并验证合并后才提交最终文档。禁止多个代理共同编辑同一文件。

module 对应一级业务域而不是单个动作或渠道；同域的不同链路通过独立 entry 结果和章节保留，跨域入口只提交主业务结果域的写入者。运行记录保留 `coordinator -> module -> entry` 所有权关系，但不要求每个角色都启动独立模型进程；真实并行发生于只读 entry 子代理。批次可以按并发上限分批调度，不得把一个大模块一次启动无限子进程，也不能串行运行后宣称 parallel=true。模块任务提交、等待及写入事件必须可核查。协调者不代替失败入口代理编写业务行为；入口代理不修改源码、Markdown、映射或版本文件。渲染与文件替换由模块写入能力持有者完成。

## 入口结果

每个入口任务只收到该入口身份、确认归属、fingerprint、注册证据及可达行为证据/待复核项，不把全仓库问题复制给全部任务。JSON 字段必须完整：

```json
{
  "entry_id": "...",
  "source_fingerprint": "...",
  "business_name": "查询车辆套餐用量",
  "trigger_summary": "GET /v0/public/vehicle/usage",
  "scope_status": "business",
  "exclusion_reason": null,
  "source_evidence": [{"file": "src/UsageController.java", "line": 42, "reason": "业务路由注册"}],
  "review": {"id": "...", "trigger": "...", "purpose": "...", "input": "...", "outcome": "...", "failure": "...", "status": "confirmed", "confirmed_by": "agent:codex", "steps": [{"kind": "action", "text": "...", "source": "src/UsageController.java:42", "participant": "流量服务", "branch_ids": [], "persistence_ids": [], "sender": "", "response": false}]},
  "resolutions": [],
  "participants": [],
  "calls": [],
  "branches": [],
  "persistence_actions": [],
  "async_actions": [],
  "external_calls": [],
  "outcomes": [],
  "unresolved": []
}
```

以上为协议示例，不是实际项目证据。每个事实必须来自本次扫描源码，空数组只在确实无该类动作时使用。`source_evidence` 和 `participants` 必须逐项原样复制静态清单，包括理由文字和数组顺序；新增取证位置写入 `resolutions` 或 `review.steps.source`，实际交互参与方写入步骤的 `participant`/`sender`，不得反向改写注册证据或参与方清单。业务名称不得补写不存在的规则；业务入口缺少名称、注册证据或归属属于关键未决。已证据充分排除的候选不再创建行为任务。

## 时序与控制结构

`review.steps` 按真实执行顺序表达业务消息和控制结构，不按源文件行号、方法声明顺序或分支清单排序。`kind` 使用 action、alt、else、opt、loop、end；控制块必须正确嵌套及闭合，else 只能属于对应 alt。业务条件与结果放在各自路径内，调用及返回保持真实先后，不能把所有条件平铺后统一追加动作或无条件成功返回。

每个 B ID 在其精确源码位置绑定到步骤的 `branch_ids`；多结果判断绑定 alt/opt/loop，单结果抛出或返回绑定 action。每个 P ID 用 `persistence_ids` 绑定真实操作位置的 action，参与方对应真实资源。IDs 只进入绑定元数据、Mermaid 注释及矩阵，可见图文使用业务词汇。`participant` 为消息目的方，`sender` 为来源方；真实入口成功/失败响应使用 `response=true` 并指向调用方，不能仅凭 outcome 概述虚构统一返回。参与方及返回箭头均须有源码依据。

review 的 trigger、purpose、input、outcome、failure 为每项不超过 50 字的中文业务短句，不能写源码路径、行号或实现类名；长条件与细节放在步骤、分支及证据字段。凭据被脱敏且不影响已证明的控制流时，不因缺少凭据内容列为关键未决。普通内存字典不是外部持久化，读写仍表达为业务动作，不能伪造外部持久化 P IDs。

## 静态证据与代理补证

第二阶段证据层用静态注册的语言/框架适配器，为确认入口可达分支和持久化分配稳定 `B-*`、`P-*` ID；Skill 不绑定具体语言或 ORM。入口任务实际收到相关 `discovery_findings`。代理可读注册、调用方/被调用方和适配器以补齐证据，不把代码事实转交用户。

`resolutions` 包含 finding、resolution、evidence、path、controls、unknowns。位置必须存在于本次扫描文件；关键问题只有 path/controls 充分且 unknowns 为空时可解除。缺少中文标签可凭源码/配置补齐，不能改写真实对象、条件、操作或行号。可能影响结果但业务相关性/可达性未知时保留 `CRITICAL_UNRESOLVED_BRANCH`；真实持久化对象或有依据的中文标签缺失保留 `PERSISTENCE_OBJECT_UNRESOLVED`。不支持的适配器不能用一句“已解决”绕过。

每个要求覆盖的 ID 同时出现在结构化结果、Mermaid `%% devflow:branch id="..."` 或 `%% devflow:persistence id="..."` 注释、对应矩阵及 manifest。无数据库动作不要求数据库参与方。复杂入口可拆多图，覆盖合并计算。内部辅助实现疑点不影响业务表达时保留非关键记录，不把无关源码解析当成入口失败。

## 宿主交接、失败和局部完成

`prepare` 只导出脱敏任务包，不探测品牌 CLI、不读取 `DEVFLOW_AGENT_EXECUTOR`。宿主会话判断是否有原生子代理能力；无法委派时必须让用户在串行分析和停止之间明确选择。原生结果保存真实工具引用、child_agent_id、task_id、开始/结束及回收状态；串行结果保存用户选择引用和授权范围，子代理数为 0。

`collect` 重新校验运行身份、源码和映射指纹、逐入口覆盖、结果 schema、证据完整性及执行记录。任何失败都保留入口目录并将运行置为 failed，不自动降级。成功生成模式复用同一业务分析校验、Mermaid 渲染和模块唯一写入；`audit` 只保存审核结果，不写最终文档。

`check` 和每次 `verify` 都基于当前运行；只有相同结果和文档哈希连续通过两次 verify，`accept` 才能推进源码基线。旧 review、generate、update、外部执行器和 allow-degraded 路径均不属于 3.0 协议。
