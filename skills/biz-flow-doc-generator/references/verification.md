# 可重复验证

修改 Skill 或领域实现后，从仓库根目录运行以下命令：

```text
python -m pytest -q
python -m compileall -q devflow tests
git diff --check
devflow biz-flow init --project <fixture>
devflow biz-flow discover --project <fixture>
devflow biz-flow generate --project <fixture>
devflow biz-flow check --project <fixture>
devflow biz-flow verify --project <fixture>
```

没有真实子代理执行器时，`generate` 默认必须失败并返回
`DELEGATION_UNAVAILABLE`。只有测试明确允许降级时才使用
`devflow biz-flow generate --project <fixture> --allow-degraded`，并确认共享状态目录中的 run manifest
记录 `degraded=true`、`parallel=false`、完整的 coordinator/module/entry 任务树和单写者事件。
对每个入口检查源码候选 `branch_id` 与 `persistence_id` 是否同时存在于结构化入口结果、Mermaid 注释和矩阵；
缺失、改写、未知可达性或真实持久化对象名称缺失都必须阻止生成。

对于更新夹具，重复执行 `discover`，编辑源代码以新增/修改/删除入口，运行 `devflow biz-flow update`，然后运行 `check` 和 `verify`。分别注入一个格式错误的排除项、一个无效证据位置、一个占位步骤、一个过长业务要点和一个格式错误的 Mermaid 块；每项都必须失败，并在错误中包含入口 ID 或源位置。连续运行两次 `verify`，比较其 `stable` 结果和 Markdown 文档数量。
