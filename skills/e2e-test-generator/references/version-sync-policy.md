# 版本同步策略

`analysis/e2e-test-generator-version.json` 是 e2e 唯一的版本文件。它同时保存 document_baseline.git_commit，以及设计、协议、源码、支持配置、场景数据和清理指纹；没有第二个 version-lock 文件，也不读取文档目录中的旧 YAML。

init 只创建带有 skill、skill_version 和 artifact_root 的 JSON。generate 在材料化设计、协议和场景后写入全部业务字段；check、source-status 和 run 先校验 skill 元数据，再校验每个文件摘要和状态。下游门禁成功后才推进 document_baseline.git_commit。

`skill_version` 是发布版本，业务 `version` 是锁格式字段，端到端门禁 schema 版本仅用于内存结构校验。任何元数据不匹配、JSON 损坏、源码基线不可解析或清理指纹过期都必须停止。