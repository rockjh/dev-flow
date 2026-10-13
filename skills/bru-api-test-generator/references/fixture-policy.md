# API 测试数据与 fixture

fixture 只提供协议及已审核设计支持的输入，不创建业务预期。复用 biz-flow 已验收资产，源码取证限于数据结构、前置准备、连接配置和清理支持。生成示例和真实运行数据分开；不得把示例 ID、凭据或状态当成目标项目事实。

文件资产位于 `qa/fixtures/`，登记在 `qa/contracts/fixtures-manifest.yaml`。上传接口必须有且仅有一个该 endpoint 独占的合法 fixture，并使用专属环境变量；不能使用通用 `UPLOAD_FILE` 或 `FILE` 作为多个接口的绑定。成功上传用例必须实际引用该变量。

以下是 fixture manifest 条目的结构示例；路径、摘要及证据必须按实际文件生成，示例不能直接作为通过记录：

```yaml
version: 1
fixtures:
  - id: example-upload-valid
    type: legal
    endpoint_scope: [EXAMPLE_UPLOAD]
    variable: EXAMPLE_UPLOAD_VALID_FILE
    path: fixtures/example-upload/valid.txt
    sha256: <sha256-of-actual-file>
    evidence:
      source_kind: openapi
      file: contracts/openapi.json
      symbol: EXAMPLE_UPLOAD
      line: 1
      endpoint_scope: [EXAMPLE_UPLOAD]
      confidence: high
```

物化校验检查文件存在、SHA-256、所属上传 endpoint、环境变量及其实际解析路径，以及来源证据。活动环境变量中的相对文件路径以 Bruno 根目录解析；与 manifest 的 QA 根目录相对路径必须指向同一文件。无效扩展名、MIME、大小及空文件只在 OpenAPI 或已审核设计明确约束时生成。真实私有文件和凭据不得提交。

数据库前置步骤属于 `cases.yaml` 的 `database_steps`。只有不存在可用前置 API 时才允许数据准备；响应缺少必要状态时才允许数据库补充断言，见 [database-access.md](database-access.md)。准备计划必须声明数据源、数量、幂等性、只读 precheck、运行独占选择器、创建后验证、清理及清理后不存在验证。

写入与清理分别授权。已有明确范围授权时沿用；生成授权不推导数据库执行授权。非交互调用使用当前命令的显式参数，执行前仍通过环境及所有权门禁：

```text
devflow bru-api mock-data-generate --qa-root qa --module <module-id> --allow-write
devflow bru-api mock-data-clean --qa-root qa --run-id <actual-run-id> --allow-cleanup
```

生产和受保护环境拒绝操作。所有新建数据使用 `DEVFLOW_DATA_NAMESPACE` 绑定 run-owned 精确标识；禁止覆盖原有业务数据、宽条件删除、通配符清理或全库操作。precheck 发现已有数据时只验证和复用，不把它纳入本次清理。创建尝试先记账，创建验证后才记为成功；按反向依赖顺序清理，并验证缺失。任何准备、验证或清理失败均保留实际失败，不能报告完成。

同一文件只有一个活动写入者。模块子代理不能修改公共 fixture、环境、依赖或权威锁；提出公共变更需求，由主 Agent 审查和统一处理。路径必须在已授权资产根目录内，敏感值只在运行时解析，诊断只展示变量名、数据源标识和脱敏摘要。
