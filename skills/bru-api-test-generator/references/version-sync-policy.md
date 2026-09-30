# 版本同步策略

`qa/contracts/bru-api-test-generator-version.json` 是本 Skill 唯一的版本文件；`qa/contracts/qa-lock.yaml` 只保存 QA 状态和业务指纹。版本文件包含完整 skill 标识、skill_version、artifact_root，以及业务 version、status、source digest、OpenAPI 和设计摘要。

生成前读取已确认的 biz-flow Markdown 和当前业务源码摘要。源码或设计发生变化时先完成影响分析、重新生成受影响模块并通过 QA lock 检查，再推进业务锁状态。Skill 版本不匹配、JSON 损坏或任一业务指纹过期时命令失败。

版本文件的 `skill_version` 表示发布版本，不随工具发布版本或领域 schema 版本自动写入；领域 schema 版本只用于内存契约校验。