---
name: bru-api-test-generator
description: Generate and maintain source-linked API contracts, Chinese Bruno cases and QA assets from accepted biz-flow documents and OpenAPI. Use for API test generation and module owner delegation through the installed devflow CLI.
---

The authoritative version file is `qa/contracts/bru-api-test-generator-version.json` and its `skill_version` is `2.1.0`; domain schema is 7. The biz-flow dependency is `biz-flow-doc-generator`.

使用已安装的 `devflow` CLI，并在 `biz-flow-doc-generator` 完成后运行本 Skill。
只读取项目 `docs/biz-flow/` 中已确认的 Markdown、锁和源码证据；不要重新发现或复制业务设计、模块归属、源码证据和流程文档。

本 Skill 只生成和维护 API 专属资产：OpenAPI、接口契约、用例、中文 Bruno
请求、中文 title/description/summary、执行配置、锁和报告。所有面向人的描述、Markdown 报告和文档正文必须使用中文，机器字段、ID、路径和协议值保持原样。`constraints/design-rules.yaml` 是可删除、可重建的映射缓存，不是业务事实来源。

按需读取 `references/` 中的覆盖率、执行、fixture、集成、版本和产物规则。
生成或修改 Markdown 时必读 [coverage-manifest](references/coverage-manifest.md)。生成、修改或验证任何时序图前，必读由 sequence-diagram-generator Skill 统一维护并同步的本地 [diagram-conventions](references/diagram-conventions.md)；公共规范或领域文档门禁失败时停止。
存在模块委派时必须先读 [parallel-generation](references/parallel-generation.md)：通过现有 `worker-start --delegate` 一次冻结已授权模块集合，主 Agent 使用当前会话实际可用的原生子代理工具分派、等待、收集，再逐模块 `worker-check --run-id --receipt` 校验。CLI 的 tasks_prepared/unknown 是正常交接，必须继续；不探测品牌 CLI 或外部执行器。按宿主槽位并发或分批，原生顺序执行有效且不需串行授权。每个子代理只写其独占模块目录和 state 交接位置，不能写源码、公共配置、权威锁、其他模块或全局报告；共享工作区提示词不代表 OS 沙箱。
保留真实 owner、attempt、输入/结果摘要和工具/会话引用；并行仅凭真实重叠/活动快照证明，不能编造内部时间、调用 ID 或回收记录。缺少工具/被禁止/实际启动失败须区别说明；只有明确的当前范围串行选择才可用 serial 模式，不能从“直接生成”推导。不得把失败子代理的业务结论改成主 Agent 结论仍沿用原 child ID。报告区分任务准备、子代理执行、结果收集、领域检查和协调者合并，未收齐全部任务不得声称整个 run 成功。委派生成不授权执行远程测试、请求服务、改数据库或发消息。
版本文件中的 `skill` 必须是 `bru-api-test-generator`，`artifact_root` 必须是 `qa/contracts`；
业务 `version`、状态、指纹和摘要继续保留，`skill_version` 只表示 Skill 发布版本。
`qa-lock.yaml` 继续作为 QA 状态锁；不要把它当作 Skill 版本文件。
证据缺失、过期、归属不明、目标不安全或 CLI 门禁失败时停止，并返回脱敏报告
或权威产物路径。

## Cross-skill routing

If a request is for a standalone sequence diagram, route it to the installed `sequence-diagram-generator` Skill. bru-api may consume accepted diagram or biz-flow reports as evidence, but it must not regenerate or edit sequence assets; API and source facts stay in the bru-api workflow and QA ownership lock.

## Git source snapshot gate

When the project has a Git version record, generation must read only the recorded committed snapshot (or committed HEAD when no baseline is recorded). Never read modified or untracked source files. If a tracked file is modified but uncommitted, use its pre-change committed content and record that commit; stop on missing or invalid Git evidence.
After successful completion, delete process-only temporary artifacts and retain only owned business assets, the version lock, and authoritative reports or recovery evidence.
