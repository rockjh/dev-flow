# 执行配置

`qa/execution/config.yaml` 只包含执行选项；工具始终使用已安装的共享 CLI。

```yaml
本节规定端到端测试的流程、证据和安全约束，所有技术字段必须依据已确认的项目契约。
tooling: shared-cli
coverage_profile: full-matrix
cli_timeout: 60
sign:
  provider: disabled
```

允许的覆盖配置为 `contract-draft` 和 `full-matrix`。`verified` 是执行结果而不是配置。活动 Bruno 环境位于 `qa/execution/environments/<active_environment>.bru`，可包含变量占位符和公共请求头。凭据值只能存放在运行时环境中，禁止写入契约或报告。

生成的启动器只是便捷薄封装，用于调用已安装的 `devflow bru-api` 命令，不包含 Python 实现。运行启动器可在 CMD 和 Shell 中执行测试，以及独立的模拟数据生成与清理。`devflow bru-api scripts` 只报告已安装的领域 schema，不同步文件。

预检会在 Bruno 运行前校验项目锁、QA 锁、执行配置、环境语法、静态覆盖、目标 URL、必需变量、工具可用性和报告目录。权威报告始终位于 `qa/results/` 下。

活动环境名称同时是模拟数据的安全边界。操作员列为受保护的生产别名和环境，在考虑授权前就拒绝创建与删除。数据源凭据从 `constraints/mock-data.yaml` 指定的进程环境变量读取；已提交的 Bruno 环境中只能出现非敏感默认值和空凭据占位符。
