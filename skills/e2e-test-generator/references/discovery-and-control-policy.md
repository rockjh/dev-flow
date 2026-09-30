# 工作区发现与测试控制策略

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 工作区契约

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
# 用途：记录工作区、依赖、配置和只读运行探测证据；禁止保存凭据值或业务数据。
schema_version: 1

# 工作区清单：列出扫描范围内全部仓库、构建工程、模块和已有 E2E 工程。
inventory:
  roots:
    - <workspace-root-reference>
  repositories:
    - id: <repository-id>
      root: <relative-or-resolvable-path>
      commit: <40-character-git-sha>
      build_files:
        - <build-descriptor-path>
      modules:
        - id: <module-id>
          path: <module-path>
          kind: <application|sdk|starter|client|facade|library|e2e|other>
  existing_e2e:
    - <relative-path>

# 依赖拓扑：每条边必须有构建描述或源码调用证据。
topology:
  nodes:
    - id: <repository-id>:<module-id>
      relevant: true
  edges:
    - from: <node-id>
      to: <node-id>
      mechanism: <build|http|rpc|message|database|cache|job|configuration|embedded>
      evidence:
        - <from-repository-id>#<source-anchor>
  searches:
    http_rpc:
      queries: [<search-expression-or-symbol-family>]
      evidence: [<repository-id>#<source-anchor>]
      conclusion: <source-backed-conclusion-or-explicit-not-found>
    messages:
      queries: [<search-expression-or-symbol-family>]
      evidence: []
      conclusion: <source-backed-conclusion-or-explicit-not-found>
    database:
      queries: [<search-expression-or-symbol-family>]
      evidence: []
      conclusion: <source-backed-conclusion-or-explicit-not-found>
    cache:
      queries: [<search-expression-or-symbol-family>]
      evidence: []
      conclusion: <source-backed-conclusion-or-explicit-not-found>
    jobs:
      queries: [<search-expression-or-symbol-family>]
      evidence: []
      conclusion: <source-backed-conclusion-or-explicit-not-found>
    configuration:
      queries: [<search-expression-or-symbol-family>]
      evidence: [<repository-id>#<source-anchor>]
      conclusion: <source-backed-conclusion-or-explicit-not-found>

# 配置发现：只记录非敏感值或敏感值来源；precedence 稳定列出来源，同一 owner 内从低到高排列。
configuration:
  sources:
    - id: <configuration-source-id>
      owner: <node-id>
      kind: <file|profile|environment|config-center|command-line|local-override|other>
      location: <path-or-non-secret-reference>
      profile: <profile-or-null>
      overrides: [<lower-priority-source-id>]
      evidence: [<repository-id>#<source-anchor>]
  precedence:
    - <configuration-source-id>
  services:
    - id: <service-id>
      owner: <node-id>
      port:
        value: <non-secret-value-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
      context_path:
        value: <non-secret-value-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
      health:
        value: <non-secret-value-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
      openapi:
        value: <non-secret-value-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
  data_sources:
    - id: <data-source-id>
      owner: <node-id>
      type: <discovered-type>
      name:
        value: <non-secret-value-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
      connection_source:
        reference: <credential-or-config-reference-only>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
  middleware:
    - id: <middleware-id>
      owner: <node-id>
      capability: <messages|cache>
      type: <discovered-type>
      logical_name:
        value: <non-secret-name-or-null>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
      connection_source:
        reference: <credential-or-config-reference-only>
        effective_source: <configuration-source-id>
        resolution: <resolved|unresolved>
        source_key: <exact-key-in-effective-source>
  controls:
    - id: <control-id>
      owner: <node-id>
      capability: <jobs|test_or_admin_api|mocks_and_faults|dynamic_configuration|scheduled_jobs>
      type: <mock|test-api|fault-injection|job|dynamic-config|other>
      source: <repository-id>#<source-anchor>

# 运行探测：用户未说明服务已启动时 outcome 必须为 not_requested。
runtime_probe:
  requested: false
  outcome: not_requested
  blockers: []
  listeners: []
  processes: []
  associations: []
  read_only_smoke: []

# 阶段门禁：仅在相应证据完整后由主代理置为 true。
gates:
  inventory_complete: true
  topology_complete: true
  configuration_complete: true
  runtime_probe_complete: true
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 清单与拓扑流程

1. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
2. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
3. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
4. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
5. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 只读运行时探测

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

1. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
2. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
3. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
4. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
5. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
processes:
  - id: <process-id>
    pid: <positive-observed-process-id>
    command_reference: <non-secret-command-or-artifact-reference>
    startup_arguments: [<non-secret-effective-argument>]
    working_directory: <observed-working-directory-reference>
    profile: <effective-profile-or-null>
    evidence: [<read-only-observation>]
listeners:
  - id: <listener-id>
    host: <observed-local-bind-or-loopback-host>
    port: <observed-port>
    protocol: <observed-protocol>
    evidence: [<read-only-observation>]
associations:
  - process: <process-id>
    listener: <listener-id>
    node: <topology-node-id>
read_only_smoke:
  - node: <topology-node-id>
    method: <GET|HEAD|READ>
    target_ref: <credential-free-local-url-or-source-proven-read-reference>
    result: <status:NNN-for-http-or-bounded-read-result>
configuration_checks:
  - id: <service-or-component-id>
    node: <topology-node-id>
    profile: <effective-profile-or-null>
    sources: [<low-to-high-source-id>]
    effective: <confirmed|unconfirmed>
    evidence: [<runtime-behavior-or-read-only-observation>]
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

每个 `场景定义.yaml` 都包含以下所有控制类别，即使某类别没有可用能力：

- `public_api`
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- `messages`
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
decision:
  safe_control_path: true
  blockers: []
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
- 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。

分配前，主代理将每个控制矩阵作为发现工作状态保存，并据此决定实现是否安全。分配后，所有者子代理将审查后的矩阵写入其 `场景定义.yaml`，只能收紧或按源码修正；安全控制决策发生变化时，必须在生成代码前返回主代理审查。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
generation:
  mode: delegated
  owner: <subagent-task-id>
  write_scope: scenarios/<中文业务名称>
  degradation_reason: null
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 受控 SQL

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

```yaml
safety:
  authorization_required: true
  target_environment: <exact-test-environment>
  purpose: <preparation|time_advance|expiry_simulation|state_trigger>
  consumer_source: <repository-id>#<source-symbol>
  exact_selector: <scenario-owned-selector-symbol>
  expected_rows: 1
  snapshot: <snapshot-operation-symbol>
  mutation: <bounded-control-operation-symbol>
  trigger: <business-trigger-or-wait-symbol>
  verification: <business-verification-symbol>
  restoration: <restoration-operation-symbol>
  restoration_verification: <restoration-verification-symbol>
  operations:
    - id: <operation-id>
      depends_on: []
      consumer_source: <repository-id>#<source-symbol>
      exact_selector: <scenario-owned-selector-symbol>
      expected_rows: 1
      snapshot: <snapshot-operation-symbol>
      mutation: <bounded-control-operation-symbol>
      verification: <post-mutation-verification-symbol>
      restoration: <restoration-operation-symbol>
      restoration_verification: <restoration-verification-symbol>
```

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

1. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
2. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
3. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
4. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
5. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
6. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
7. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
8. 本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 门禁测试

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。

## 强制执行映射

本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
| --- | --- |
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
本节规定端到端测试的业务流程、证据要求和安全校验；具体字段与命令必须以项目契约和实际证据为准。
