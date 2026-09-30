# 共享端到端执行策略

生成项目不包含门禁引擎、检查脚本、Python 运行脚本或共享运行时副本。根目录下可选的 `run-e2e.bat` 和 `run-e2e.sh` 启动器仅将参数转发给已安装的 `devflow e2e run`，不包含门禁逻辑。只能执行已安装的命令：

场景和公共业务模块从 `devflow.e2e_runtime` 导入证据、预检、轮询和恢复辅助函数；禁止在 `common/` 下重新实现这些辅助函数。

```text
devflow e2e init --project .
devflow e2e check --project . --gate <stage>
devflow e2e source-status --project .
devflow e2e run --project .
devflow e2e run --project . --scenario <scenario-name>
devflow e2e run --project . --static-only
```

引擎负责固定阶段顺序、内容寻址封印、一个小时的会话边界、每次运行请求的活动只读本地环境探测、源代码检查、收集、只读冒烟、业务执行、JUnit 校验、恢复和最终报告。调用方的 pytest 参数仅在最终业务调用时接受，不能改变选择或成功语义。

`devflow e2e run` 会移除继承的 pytest 插件和选项注入，不经过 shell 调用子进程，并将脱敏权威报告写入 `artifacts/e2e-run.json`。除非明确指定 `--full`，控制台只输出有界摘要和报告指针。

项目的 `.devflow.lock.json` 将执行绑定到精确的 devflow 发布版本和独立的端到端门禁 schema 版本。锁缺失或不匹配属于前置条件失败；绝不使用复制的旧代码作为回退。
