# 版本文件管理

本 Skill 的唯一权威版本文件是 `qa/contracts/bru-api-test-generator-version.json`。文件固定包含：

    {
      "skill": "devflow/bru-api-test-generator",
      "skill_version": "1.0.0",
      "artifact_root": "qa/contracts",
      "version": 1,
      "status": "draft",
      "business": {
        "repo": "<业务仓库>",
        "commit": "<业务基线>",
        "source_digest": "<源码摘要>"
      }
    }

业务锁中的 `version`、状态、指纹、源摘要和生成摘要继续保留；`skill_version` 只表示 Skill 发布版本。`qa-lock.yaml` 是 QA 状态锁，保存 OpenAPI、模块、用例和执行指纹，不能当作 Skill 版本文件。删除或改名任何一个文件都会使门禁失败；旧项目由操作员删除旧锁后重新 init。

bru-api 依赖已经完成的 `devflow/biz-flow-doc-generator` 及其已确认 Markdown。生成、预检、执行和完成更新都必须通过公共 CLI，并在业务源码摘要或 QA 状态过期时停止。