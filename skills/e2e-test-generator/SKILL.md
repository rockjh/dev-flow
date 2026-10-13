---
name: e2e-test-generator
description: 根据已授权的设计、协议和源码证据生成及维护端到端测试场景。用于 devflow E2E 发现、控制矩阵、场景拆分、原生场景所有者委派、独占资产生成和领域验收；生成任务不授权实际执行测试。
---

The authoritative version file is `analysis/e2e-test-generator-version.json` and its `skill_version` is `2.1.0`. This skill owns only its E2E artifacts.

使用已安装的 `devflow` CLI，并仅路由到明确映射的 `e2e-test-generator` 领域。版本文件为
`analysis/e2e-test-generator-version.json`，其中 `skill_version` 为 `2.1.0`、`artifact_root` 为
`analysis`；文件中的 `document_baseline.git_commit`、设计、协议、源码、支持配置、场景和清理指纹
都是本 Skill 自己的业务输入锁。保留领域级 schema、锁、脱敏、所有权和工件规则。生成的场景名称、title、description、summary、Markdown 和报告正文必须使用中文；机器字段、ID、路径、协议和代码标识保持原样。

根据所选工作流，阅读 `references/` 中关于发现、控制、执行、夹具、集成、版本和生成工件的相关流程，包括 `references/version-management.md`。出现证据缺失、目标不安全、所有权不明确或 CLI 门禁失败时必须停止；返回脱敏报告或权威工件路径。

## 场景所有者的原生宿主交接

生成工作流必读 `references/e2e-workflow.md`、`references/scenario-artifact-policy.md`、
`references/discovery-and-control-policy.md` 和 `references/native-scenario-owners.md`。
项目根目录必须是用户明确授权的 E2E 生成项目；只写该项目的 E2E 资产及
`~/.local/state/devflow/` 下的领域交接。保持已提交源码、设计、协议、控制矩阵、数据隔离和清理恢复门禁。
生成、修改或验证任何时序图前，必读由 sequence-diagram-generator Skill 统一维护并同步的本地 [diagram-conventions](references/diagram-conventions.md)，并遵守 scenario-artifact-policy 的领域补充；公共规范或领域文档门禁失败时停止。

多场景执行已安装 `devflow e2e generate` 后，主 Agent 必须读取返回的任务包及实际 schema，
按当前宿主真实工具启动原生场景所有者，控制可用槽位、等待并收集真实结果，再执行
`devflow e2e check --host-results <交接文件> --gate contracts` 及已有有序验收。
单场景明确需要委派时使用 `generate --delegate`。`tasks_prepared` 是正常交接状态，主 Agent 应继续调用宿主；
`init` 带设计/协议输入并返回多场景任务时同样接续原生所有者，不能停在初始化完成。
CLI 不访问会话工具，也不通过品牌 CLI、PATH 或环境变量判断会话能力。每位所有者必须独立分析并完成或修正场景，
CLI 生成的起始资产不能代替子代理的分析结果。
所有者保留 YAML 中文用途和区块注释、逐步骤证据及导入期安全门禁；提交摘要前检查自己的生成工件。

场景所有者仅能写自己的 `scenarios/<中文业务名称>/`，不得写源码、其他场景、公共目录、
`configuration/`、发现工件、依赖或权威版本锁。共享工作区只具备范围校验时必须如实报告。
生成授权不授予远程测试、数据库修改、消息发布或发布权限。代理复用按独立 task/attempt 绑定，
`native + parallel=false` 有效；只有真实活动观察证明重叠才报告并行。

工具缺失、禁止、启动失败、槽位不足及任务失败必须分别记录；有可用工具就继续原生工作流。
没有当前范围内明确串行授权时不得降级；“直接生成”“不用确认”不构成串行授权。
工具缺失或启动不可恢复且没有串行授权时停止并一次提供串行或停止选择。
串行接管须新建授权清晰的运行，保留旧失败证据；不得沿用失败子代理 ID 代写结论。
取得明确选择后，以 `devflow schema e2e.serial-approval` 编写 state 下的授权 JSON，使用
`generate --serial-approval <文件>`；`init` 带生成输入时支持同一选项。授权必须覆盖全部现有及将生成的场景目录，
记录实际原生不可用原因、会话选择和诊断引用，并关联旧 run。新串行任务仍须由主 Agent 真实分析并写入场景，
通过相同 `check --host-results` 收集及完整有序静态验收；零子代理回执不能把起始模板当成完成结果。
回执真实性由主 Agent 对照真实会话工具记录确认，CLI 只验证结构和一致性。
分别报告任务准备、子代理执行、结果收集及领域验收状态；任一必需任务或门禁失败不得报告整体完成。
存在原生或串行交接任务时，准备、收集失败或聚合 contracts 通过均不得提前推进文档基线或清除 pending_changes。
必须全部 owner 成功收集，当前结果、输入及冻结需求文档一致，并通过既有完整有序静态验收后才推进；
首次基线为 null 时通过 check 完成这些门禁，不能借 init、source-status 或未验收任务建立成功基线。

## Cross-skill routing

If a request is for a standalone sequence diagram, route it to the installed `sequence-diagram-generator` Skill. E2E scenarios may reference an accepted sequence report, but this Skill does not generate or rewrite sequence assets. Code facts remain bound to the E2E workflow evidence.

## Git source snapshot gate

When the project has a Git version record, generation must read only the recorded committed snapshot (or committed HEAD when no baseline is recorded). Never read modified or untracked source files. If a tracked file is modified but uncommitted, use its pre-change committed content and record that commit; stop on missing or invalid Git evidence.
After successful completion, delete process-only temporary artifacts and retain only owned business assets, the version lock, and authoritative reports or recovery evidence.
