# Python 端到端工作流契约

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 契约追踪

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```text
设计规则 -> 正式协议入口与模型 -> 设计状态变化/结果 -> 设计关联键 -> 支持性观察方式 -> 控制方式 -> 清理/恢复
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 场景定义

每个 `scenarios/<中文业务名称>/场景定义.yaml` 都是该场景的权威文件。顶层必须严格使用以下分区：`meta`、`generation`、`readiness`、`preconditions`、`constructability`、`integrations`、`controls`、`isolation`、`steps`、`cleanup` 和 `source`。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
# 用途：定义一个业务 E2E 场景的来源、控制、步骤和恢复契约；禁止保存凭据或连接值。
meta:
  id: <STABLE_SCENARIO_ID>
  name: <中文业务名称>
  status: pending_environment
  participants: [<participant-service-a>, <participant-service-b>]
  actor: <业务参与者>

# 生成职责：多场景时每个场景必须有独立 delegated owner；降级时如实记录原因。
generation:
  mode: delegated
  owner: <subagent-task-id>
  write_scope: scenarios/<中文业务名称>
  degradation_reason: null

# 就绪判定：四项状态共同决定 meta.status，blockers 只写缺口而不写敏感值。
readiness:
  source_contract: confirmed
  safe_control: confirmed
  runtime_configuration: missing
  test_data: missing
  blockers:
    - connection:<MISSING_ENDPOINT_ENVIRONMENT_VARIABLE_NAME>
    - business_data:<MISSING_BUSINESS_DATA_VARIABLE_NAME>

# 业务前置：只写可验证条件，不写连接信息。
preconditions:
  - <design-defined-precondition>

# 可构造性：每个前置和步骤都完整评估 schema 定义的候选路径。
constructability:
  preconditions:
    - id: <design-defined-precondition>
      data_ownership: <test_owned|environment_owned|not_data>
      constructible: true
      candidates: <candidate-matrix-from-devflow-schema>
  steps:
    - step_id: <step-id>
      candidates: <candidate-matrix-from-devflow-schema>

# 运行依赖：类型和 ID 均来自工作区发现，不限定具体技术。
integrations:
  services:
    - <discovered-service-id>
  components:
    - id: <discovered-component-id>
      type: <discovered-component-type>
      required: true

# 控制矩阵：每类都必须完成评估，即使能力不存在。
controls:
  public_api:
    status: usable
    assessment: <source-backed-capability-conclusion>
    evidence:
      - <repository-id>#<source-symbol>
    planned_use:
      - <business-action-symbol>
  test_or_admin_api:
    status: not_found
    assessment: <searched-locations-and-conclusion>
    evidence:
      - <repository-id>#<search-or-source-symbol>
    planned_use: []
  mocks_and_faults:
    status: not_applicable
    assessment: <source-backed-relevance-conclusion>
    evidence: []
    planned_use: []
  dynamic_configuration:
    status: not_applicable
    assessment: <source-backed-relevance-conclusion>
    evidence: []
    planned_use: []
  scheduled_jobs:
    status: not_applicable
    assessment: <source-backed-relevance-conclusion>
    evidence: []
    planned_use: []
  messages:
    status: not_applicable
    assessment: <source-backed-relevance-conclusion>
    evidence: []
    planned_use: []
  database_read:
    status: usable
    assessment: <source-backed-capability-conclusion>
    evidence:
      - <repository-id>#<repository-method-symbol>
    planned_use:
      - <business-evidence-symbol>
  database_control:
    status: not_applicable
    assessment: <source-backed-relevance-conclusion>
    evidence: []
    planned_use: []
    safety: null
  observability:
    status: usable
    assessment: <source-backed-capability-conclusion>
    evidence:
      - <repository-id>#<query-or-event-symbol>
    planned_use:
      - <business-evidence-symbol>
    correlation_keys:
      - <design-defined-correlation-symbol>
    business_evidence:
      - <observable-outcome-symbol>
    recovery:
      - <idempotent-recovery-symbol>
  decision:
    safe_control_path: true
    blockers: []

# 隔离边界：关联键、资源和可变控制必须由当前场景真正独占；锁名称不能替代隔离证明。
isolation:
  namespace: <scenario-unique-namespace>
  correlation_keys:
    - <scenario-owned-correlation-reference>
  owned_resources:
    - kind: <record|message-client|cache-key|file|other>
      identity: <scenario-unique-resource-reference>
      cleanup: <idempotent-cleanup-symbol>
      restore: <restoration-symbol>
      verify: <restoration-verification-symbol>
  mutable_controls: []
  serial_lock: null

# 业务步骤：control 必须引用控制矩阵类别，side_effect 决定运行时门禁。
steps:
  - id: <step-id>
    action: <business-action-symbol>
    control: public_api
    side_effect: write
    design_rule_id: <DESIGN_RULE_ID>
    protocol_ref: <FORMAL_PROTOCOL_OPERATION_ID>
    phase: final_business
    data_ref: 业务数据.json#/<json-pointer>
    expect:
      - <business-outcome-symbol>
    status: executable
    status_reason: <design-and-execution-support-backed-reason>
    evidence:
      - <repository-id>#<source-symbol>

# 清理恢复：动作必须来源明确、幂等且按资源创建顺序立即注册。
cleanup:
  strategy: <api|fixture|control|composite>
  actions:
    - <cleanup-symbol>
  verifies:
    - <restoration-evidence-symbol>

# 源码基线：每项对应一个参与本场景的仓库。
source:
  - repo: <repository-id>
    commit: <40-character-git-sha>
    anchors:
      - <source-symbol>
```

架构规则：

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- `data_ref`（如存在）必须严格采用 `业务数据.json#/<pointer>` 形式，并且只能在选择活动环境后按 RFC 6901 解析。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 确定性状态门禁

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 业务数据

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```json
{
  "<selected-test-environment>": {
    "<step-data-key>": {
      "<protocol-field>": "<protocol-valid-synthetic-value>",
      "<environment-owned-field>": "${<SELECTED_ENVIRONMENT_VALUE_REFERENCE>}"
    }
  },
  "<named-test-environment>": {
    "<step-data-key>": {
      "<protocol-field>": "<protocol-valid-synthetic-value>",
      "<environment-owned-field>": "${TEST_ENV_SCENARIO_VALUE}"
    }
  }
}
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## YAML 注释策略

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

1. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
2. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
3. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
4. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
5. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
6. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
7. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

扩展生成项目中唯一的 `devflow e2e check`；不要创建重复的校验器。该命令接受每个有序阶段名称、聚合参数 `--gate discovery|contracts|static|all`，以及可选的 `--scenario <中文场景名称>`。每个有序阶段都会校验前一阶段的内容寻址封印。聚合的 discovery/contracts/all 模式仅用于诊断，不能创建这些封印，也不能授权执行 `static`。至少检查以下内容：

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 最终报告

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
