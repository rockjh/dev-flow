# 版本文件管理

本 Skill 的唯一权威版本文件是 `analysis/e2e-test-generator-version.json`。文件固定包含：

    {
      "skill": "devflow/e2e-test-generator",
      "skill_version": "1.0.0",
      "artifact_root": "analysis",
      "version": 1,
      "document_baseline": {"git_commit": "<40 位提交 SHA>"},
      "design": {},
      "protocol": {},
      "source": [],
      "support": {},
      "scenario_generation": {},
      "changes": {},
      "scenarios": {}
    }

该文件只记录本 Skill 的设计、协议、源码、支持配置、场景数据和清理指纹。`skill_version` 是 Skill 发布版本；`version` 和各业务字段是输入锁格式及生成摘要。`docs/e2e/e2e.yaml`、`analysis/version-lock.yaml`、`biz-flow.json`、`biz-flow.yaml` 和根目录 `.devflow.lock.json` 都不是运行时兼容路径，升级时由操作员删除旧文件后重新 init。

e2e 的 init、generate、check、source-status 和 run 只读取自己的 JSON。文档基线只有在文档门禁和下游检查成功后才推进；缺少、损坏、技能元数据不匹配或任一指纹过期都会停止。