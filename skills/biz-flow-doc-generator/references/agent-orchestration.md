# 代理编排与证据协议

## 角色边界

`coordinator` 发现入口并确认模块；`module` 只拥有一个模块 Markdown 文件；`entry` 只读一个入口。
模块代理通过 `dispatch_entry_batch()` 一次提交本模块所有入口并等待 `join()`；任何逐个提交、主代理
直接执行入口、入口写 Markdown 或模块未等待就写文件，都属于门禁失败。渲染器只返回内容，实际文件替换必须经由绑定到模块任务的单写者能力完成；协调器没有通用 Markdown 写入能力。

入口代理返回 JSON，机器字段必须完整：

```json
{
  "entry_id": "...",
  "business_name": "查询 AC 信息",
  "trigger_summary": "GET /v0/admin/esim/ac-infos",
  "scope_status": "business",
  "exclusion_reason": null,
  "source_evidence": [{"file": "src/AcInfoController.java", "line": 42, "reason": "路由和处理器注册证据"}],
  "source_fingerprint": "...",
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

`business_name` 只能描述入口行为，不得补写源码未出现的业务规则。`scope_status=business`
且名称为 `待确认` 或 `source_evidence` 为空时，该入口属于 unresolved，禁止 generate。
`scope_status=excluded` 的技术候选必须有 `exclusion_reason` 和 `source_evidence`；满足这两个条件后，
不因缺少业务名称阻止 generate。

## 证据和覆盖

Python 证据层通过静态注册的项目适配器扫描语言、框架、配置和注册信息，分配稳定 `B-*` 分支 ID 与 `P-*` 持久化 ID；适配器由项目代码显式传入，Skill 不绑定 Java、Python、JPA、MyBatis 或某一种数据库。
代理只能补充面向人的标签，不能改变源文件、行号、条件、操作或对象名称。`business_relevant` 或
`reachability` 未确定时，如果该分支可能影响业务结果，必须返回 `CRITICAL_UNRESOLVED_BRANCH`。
持久化对象没有真实名称和中文业务名称时，必须返回 `PERSISTENCE_OBJECT_UNRESOLVED`。
项目适配器可以从源码注释或项目配置提供中文名称；通用适配器支持在持久化调用所在函数内使用
`devflow:persistence: 中文业务名称`，未提供名称时必须阻断，不能使用“业务对象”等占位词。

每个 ID 都要同时出现在入口 JSON、Mermaid `%% devflow:branch id="..."` 或
`%% devflow:persistence id="..."` 注释、对应矩阵和 run manifest。没有数据库动作的入口不添加数据库参与者。

## Host executor discovery and JSONL

运行时选择顺序固定为：显式 `DEVFLOW_AGENT_EXECUTOR`、静态内置 Codex/Claude
适配器。选择前只允许读取版本、帮助或能力信息；
探测不得写项目、修改 shell/环境变量、发送业务请求或创建持久化数据。每个适配器
隔离目标 CLI 的参数和响应转换，发现失败或能力不足就继续下一个候选。内置适配器由
运行时为每个入口启动一个受限、临时的 CLI 子进程，并在同一模块批次内并行执行；模块
Markdown 由运行时汇总并交给单写者提交。能力探测只能确认只读和代理写入边界，
`real_child_agents` 只有在这些子进程真实启动并返回后才写入 manifest。适配器不能伪造
`real_child_agents`、`read_only_source` 或 `brokered_module_writes`。

## Host executor JSONL

当设置 `DEVFLOW_AGENT_EXECUTOR` 时，运行时把一个批次作为一行 JSON
传给该命令。输入包含 `run_id`、`batch_id`、`parent_task_id` 和完整的
`tasks` 数组；命令必须输出一行 `{ "parallel": true, "capabilities": {...}, "events": [...], "results": [...] }`。
`capabilities` 必须同时声明 `real_child_agents`、`read_only_source` 和
`brokered_module_writes` 为 `true`；没有 `parallel: true` 会被拒绝。
每个结果必须包含 `task_id`、`status`（`success` 或 `failed`），成功时包含上面的入口
结构化结果，失败时包含 `error`。`events` 必须是本批次的真实生命周期回执（至少包括每个任务的
`started` 和完成事件（入口为 `success`、模块为 `ready`），以及对应的 `join_batch`）；运行时会为批次补记 `dispatch_batch` 并重新编号。
响应若包含非空 `writes` 会被拒绝；命令不得直接写项目文件；模块文件写入由运行时持有的模块写入能力完成。运行 manifest 记录执行器类型、适配器、探测结果、能力、`parallel` 和 `degraded` 状态。

## 失败和降级

默认运行时没有真实子代理能力时返回 `DELEGATION_UNAVAILABLE`，不生成 Markdown。只有用户显式允许降级时，
才允许串行执行，并在 run manifest 中记录 `degraded=true`、`parallel=false`。入口失败、覆盖不相等、任务父子
关系不正确、写入者不唯一或任何关键未决证据都会阻止模块完成。
