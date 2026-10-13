# Bruno API 执行规则

生成项目只保留 Bruno 请求、fixture、API 契约、执行配置、轻量启动器和业务文档。启动器调用已安装的 `devflow`，不复制 runner、checker 或工具包源码，不添加第二套执行实现。

生成、静态检查和真实执行分别报告。静态检查不代表请求已发送；委派生成不授权预检网络访问、远程测试、数据库修改或消息发布。已有对应目标和操作授权后，使用当前 CLI：

```text
devflow bru-api check --qa-root qa --all
devflow bru-api preflight --qa-root qa
devflow bru-api run --qa-root qa
```

默认 `run` 执行全部模块，`--module <module-id>` 限定单模块。`qa/execution/run.bat` 和 `run.sh` 只是这些命令的轻量入口。`devflow bru-api scripts status --qa-root qa` 查询脚本契约状态，不把工具包实现同步到项目。

请求前必须通过 API 契约、业务与 QA 版本锁、静态覆盖、活动环境、Bruno collection 和工具检查。`qa/.devflow.lock.json` 绑定安装版本及领域 schema，不能手改锁绕过检查。子代理只在原任务授权的模块目录生成；执行、公共配置、全局锁和最终合并仍由主 Agent 按领域流程管理，见 [parallel-generation.md](parallel-generation.md)。

执行器将脱敏中文结果写入 `qa/reports/latest.md`。原始 Bruno JSON、规范化回执、预检数据和执行日志是过程工件，正常结束时清理，不复制为正式 QA 资产。与 Agent 委派有关的交接及权威报告使用任务包返回的 state 路径，与 Bruno 测试回执分开。

证据缺失、目标不安全或含糊、静态门禁失败、锁过期、执行失败或清理失败时报告具体原因并停止完成声明。保留仍可取得的脱敏诊断和恢复标识；不得填造通过状态、隐藏未执行用例或以人工确认代替验收。
