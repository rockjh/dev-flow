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

## 执行器与 JSONL

选择顺序固定：`DEVFLOW_AGENT_EXECUTOR`，再静态内置 Codex/Claude 适配器。探测只读版本、帮助和能力，不写 shell 配置或环境变量、不发业务请求、不创建业务数据。适配器隔离各 CLI 参数并转换同一 JSONL 协议。每入口启动受限临时只读子进程，按上限并行；只有真实启动并返回才记录 `real_child_agents`，禁止伪造能力或生命周期。

显式执行器输入一行 JSON：`run_id`、`batch_id`、`parent_task_id`、完整 `tasks`；输出一行包含 `parallel`、`capabilities`、`events`、`results` 的 JSON。能力要求 `real_child_agents`、`read_only_source`、`brokered_module_writes` 为 true，正常委派 parallel=true。每结果包含 task_id、status（success/failed）及 result/error。events 包含真实 started、完成（入口 success、模块 ready）和 join_batch；运行时补记 dispatch_batch 并编号。单入口时如实记录任务数量，不能把零代理或串行降级伪称并行。

非空 `writes` 被拒绝：执行器不能直接写项目，运行时模块单写者负责提交。manifest 记录执行器、探测、并发/批次、能力、parallel、degraded、逐入口状态、归属和写入事件。

## 可选审核、失败和局部完成

`review` 是第二阶段可选只读源审核，使用同一已确认入口范围，保存审核结果/manifest；不写最终模块流程、不确认归属、不推进版本。第一阶段及分类确认不得依赖它。

没有可用执行器时第二阶段返回 `DELEGATION_UNAVAILABLE`，保留第一阶段目录。仅用户显式允许 `--allow-degraded` 才串行，记录 degraded=true、parallel=false，仍满足全部证据与覆盖门禁。失败入口不标完成；其模块保留待处理状态。其他已完整验证模块可保留，但任一要求入口缺失、关键未决、fingerprint 不符、父子关系错误或写入者不唯一时整体失败，不能推进接受基线。
