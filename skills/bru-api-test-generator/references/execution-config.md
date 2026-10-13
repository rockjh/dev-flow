# 执行配置

`qa/execution/config.yaml` 只保存执行选项，唯一工具模式为已安装的共享 CLI：

```yaml
active_environment: local
tooling: shared-cli
coverage_profile: full-matrix
cli_timeout: 60
sign:
  provider: disabled
```

`coverage_profile` 只允许 `contract-draft` 或 `full-matrix`；`verified` 是执行验收结果。`cli_timeout` 是 Bruno CLI 版本检查的正数秒数，`run --cli-timeout` 可覆盖一次运行。环境名必须是安全文件名，不能带路径或 `.bru` 后缀。未知字段、内嵌认证策略、Header/Cookie 配置及令牌选择器均拒绝。

活动环境位于 `qa/execution/env/<active_environment>.bru`。变量和公共请求头使用独立的 KV 块；以下仅展示格式，凭据值必须在运行时提供：

```text
vars {
  baseUrl: http://127.0.0.1:8080
  AUTH_TOKEN: ""
}

headers {
  Authorization: "Bearer {{AUTH_TOKEN}}"
}
```

CLI 解析公共请求头中的 `{{VAR}}`，由 `collection.bru` 注入非空值；请求自身的 Header 优先。负向用例通过 `request.omit_common_headers` 显式移除指定公共头。不得把缺失认证配置解释为无需认证，也不能把运行时观测结果改写成设计预期。

`sign.provider` 只允许 `disabled` 或 `sha256`。选择 `sha256` 时必须声明 `version: v1`，运行时提供 `ACCESS_KEY` 和 `SECRET_KEY`；选择 `disabled` 时不能声明版本。只有目标协议明确采用该实现的签名算法和规范化规则时才启用，不为未知协议猜测签名方式。

预检检查版本与 QA 锁、配置和环境语法、静态覆盖、目标地址、必需变量、工具及报告目标。预检包含网络访问，只在已有对应环境授权时运行；生成委派本身不授予该权限。

环境名也是模拟数据的安全边界。生产别名和受保护环境拒绝写入及清理；其他环境仍需通过允许列表与当次授权。数据库凭据由 `qa/constraints/mock-data.yaml` 指定的进程环境变量提供，不能把已解析的凭据、连接字符串或敏感载荷写入契约、日志和报告。
