---
name: bru-api-test-generator
description: DevFlow bru-api domain skill.
---

The authoritative version file is `qa/contracts/bru-api-test-generator-version.json` and its `skill_version` is `1.0.0`. The biz-flow dependency is `biz-flow-doc-generator`.

使用已安装的 `devflow` CLI，并在 `biz-flow-doc-generator` 完成后运行本 Skill。
只读取项目 `docs/biz-flow/` 中已确认的 Markdown、锁和源码证据；不要重新发现或复制业务设计、模块归属、源码证据和流程文档。

本 Skill 只生成和维护 API 专属资产：OpenAPI、接口契约、用例、中文 Bruno
请求、中文 title/description/summary、执行配置、锁和报告。所有面向人的描述、Markdown 报告和文档正文必须使用中文，机器字段、ID、路径和协议值保持原样。`constraints/design-rules.yaml` 是可删除、可重建的映射缓存，不是业务事实来源。

按需读取 `references/` 中的覆盖率、执行、fixture、集成、版本和产物规则。
版本文件中的 `skill` 必须是 `bru-api-test-generator`，`artifact_root` 必须是 `qa/contracts`；
业务 `version`、状态、指纹和摘要继续保留，`skill_version` 只表示 Skill 发布版本。
`qa-lock.yaml` 继续作为 QA 状态锁；不要把它当作 Skill 版本文件。
证据缺失、过期、归属不明、目标不安全或 CLI 门禁失败时停止，并返回脱敏报告
或权威产物路径。

## Cross-skill routing

If a request is for a standalone sequence diagram, route it to the installed `sequence-diagram-generator` Skill. bru-api may consume accepted diagram or biz-flow reports as evidence, but it must not regenerate or edit sequence assets; API and source facts stay in the bru-api workflow and QA ownership lock.
