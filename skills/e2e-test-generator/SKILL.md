---
name: e2e-test-generator
description: DevFlow 端到端测试领域技能。
---

The authoritative version file is `analysis/e2e-test-generator-version.json` and its `skill_version` is `1.0.0`. This skill owns only its E2E artifacts.

使用已安装的 `devflow` CLI，并仅路由到明确映射的 `e2e-test-generator` 领域。版本文件为
`analysis/e2e-test-generator-version.json`，其中 `skill_version` 为 `1.0.0`、`artifact_root` 为
`analysis`；文件中的 `document_baseline.git_commit`、设计、协议、源码、支持配置、场景和清理指纹
都是本 Skill 自己的业务输入锁。保留领域级 schema、锁、脱敏、所有权和工件规则。生成的场景名称、title、description、summary、Markdown 和报告正文必须使用中文；机器字段、ID、路径、协议和代码标识保持原样。

根据所选工作流，阅读 `references/` 中关于发现、控制、执行、夹具、集成、版本和生成工件的相关流程，包括 `references/version-management.md`。出现证据缺失、目标不安全、所有权不明确或 CLI 门禁失败时必须停止；返回脱敏报告或权威工件路径。

## Cross-skill routing

If a request is for a standalone sequence diagram, route it to the installed `sequence-diagram-generator` Skill. E2E scenarios may reference an accepted sequence report, but this Skill does not generate or rewrite sequence assets. Code facts remain bound to the E2E workflow evidence.
