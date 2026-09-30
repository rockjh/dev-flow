# 版本文件管理

本 Skill 的唯一权威版本文件是 `docs/biz-flow/biz-flow-doc-generator-version.json`。文件固定包含：

    {
      "skill": "devflow/biz-flow-doc-generator",
      "skill_version": "1.0.0",
      "artifact_root": "docs/biz-flow",
      "source": {"git_commit": "<40 位提交 SHA 或 null>"}
    }

`skill_version` 是 Skill 发布版本；`source.git_commit` 是已确认源码基线，不能替代或覆盖 Skill 版本。init 只创建该 JSON；discover、generate、check、verify 只读取该 JSON。旧的 `biz-flow.json`、`biz-flow.yaml` 和根目录 `.devflow.lock.json` 不属于运行时兼容路径，升级时由操作员删除后重新 init。

只有 check 和 verify 通过后，才允许将 `source.git_commit` 更新为当前提交。失败或证据不完整时保留旧基线并停止。