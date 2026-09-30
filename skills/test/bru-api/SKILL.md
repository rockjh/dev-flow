---
name: devflow/test/bru-api
description: DevFlow bru-api domain skill.
---

使用已安装的 `devflow` CLI，并在 `devflow/doc/biz-flow` 完成后运行本 Skill。
只读取项目 `docs/biz-flow/` 中已确认的 Markdown、锁和源码证据；不要重新发现或复制业务设计、模块归属、源码证据和流程文档。

本 Skill 只生成和维护 API 专属资产：OpenAPI、接口契约、用例、中文 Bruno
请求、中文 title/description/summary、执行配置、锁和报告。所有面向人的描述、Markdown 报告和文档正文必须使用中文，机器字段、ID、路径和协议值保持原样。`constraints/design-rules.yaml` 是可删除、可重建的映射缓存，不是业务事实来源。

按需读取 `references/` 中的覆盖率、执行、fixture、集成、版本和产物规则。
证据缺失、过期、归属不明、目标不安全或 CLI 门禁失败时停止，并返回脱敏报告
或权威产物路径。
