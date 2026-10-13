# Bruno 执行证据与报告

静态 manifest 表达计划；真实 Bruno reporter 及其规范化结果证明实际执行。Agent 委派回执只证明生成任务的交接，不构成 API 测试执行证据，见 [parallel-generation.md](parallel-generation.md)。

runner 在操作系统临时目录保存原始报告与 `execution-evidence.json`，对敏感字段、令牌和响应体进行脱敏及大小限制，结束后清理。不能把临时文件路径当成持久报告，也不能把 fixture 回执作为真实执行证明。

通过要求请求确已执行、请求状态正常、没有运行时错误、至少出现一个 assertion/test observation，且所有观察均通过。Bruno 顶层 `pass` 字段单独不足以证明用例通过。数据库 assertion 的连接、查询和期望检查失败同样使所属用例失败；只保留有界的断言结果，不保留凭据、完整行或文档。

规范化结果保留 `executed`、`passed`、逐用例 HTTP 状态、脱敏响应摘要/结构及失败细节。`observed-rules.yaml` 中的成功观察只用于审计，不改变设计预期或生成断言。

设计声明的 `flows.yaml` 还必须对账真实顺序、步骤通过状态、capture/use 和 absence 观察。对应名称来自实际 reporter 中通过且唯一的 `devflow:flow:*` 事件；契约只给出预期名称。缺事件、重复用例、事件失败或顺序不符均失败。顺序执行不证明业务并发。

每次尝试的面向人结果写入 `qa/reports/latest.md`；运行中被静态或预检门禁阻断时也记录未执行及原因。报告至少区分总数、已执行、通过、失败和未执行。失败及未执行项保留模块、case ID、接口、脱敏请求摘要、预期、实际、原因分类及是否有未决确认。

当前原因分类为：

- `generation_failure`、`insufficient_source_evidence`：生成、覆盖或来源证据不满足契约。
- `insufficient_data`：前置数据缺失或模拟数据准备未获授权/失败。
- `environment_unavailable`、`endpoint_unreachable`：环境或目标不可用。
- `request_failure`、`assertion_failure`：实际请求或断言失败。
- `manual_confirmation`：仍有阻断确认项，不能豁免完成要求。

单模块运行校验模块锁，不推进全局锁或整体完成状态。全模块验收必须重新对账 OpenAPI、模块、业务逻辑、用例、流程与真实执行结果；生成任务收齐或静态检查通过均不能替代测试验收。

模拟数据创建前登记 run-owned 资源，记录实际创建与清理结果。独立模拟数据操作的恢复台账由 CLI 管理，正常 `run` 结束时会删除其过程文件；不要承诺运行结束后所有 run ID 都可恢复。中断、保留数据或清理失败时报告 CLI 实际返回的恢复标识和仍存在的台账，禁止编造已清理记录。授权、隔离及恢复规则见 [database-access.md](database-access.md) 和 [fixture-policy.md](fixture-policy.md)。
