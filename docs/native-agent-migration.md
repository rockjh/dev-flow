# 原生宿主委派改造与复核

核查基点为 `ccd373af2837ee0afd206183051af95f71f11b45`，实际仓库为 `E:/code/dev-flow`。结论：已有改造并非全部失效，四个领域均有可达原生交接流程；本轮补齐发现的门禁缺口，重新生成安装载荷并复核真实记录。所有改动仍在工作区，未提交、发布或覆盖已有未提交工作。

## 最新通用 Skill 复核

按用户最新要求，只支持当前契约，不保留兼容入口。四个 Skill 均按通用产品维护，不绑定本机路径、品牌 Agent CLI 或固定宿主工具名称。核查并非“全部失效”：biz-flow、sequence、E2E 以及全量扫描发现的 bru 模块委派均有可达流程；无委派需求的普通操作不强行启动代理。

本轮另外删除 bru-api 无调用方、仅转发导入的 `generation.py`、`materialization.py`、`execution.py`；CLI 继续直接调用领域实现。biz-flow 示例改为当前入口 fixture 说明，不再用历史版本叙述暗示真实宿主验收。旧字段拒绝、版本锁、业务模块归属及显式串行授权仍是有效门禁，不是兼容实现。

复核发现并发变更将 biz-flow 的工作区只读保护缩减到文档目录。本轮在固定交付副本保留了源码工作区核对，增加源码修改、删除、新增三种拒绝回归；冻结提交事实与工作区写入保护分别校验，不能把范围变化归因到具体写入者。Git 输出采用文件句柄，避免 Windows 管道丢失。另将实际渲染测试的持久缓存和内存缓存隔离，确保测试真实调用 renderer 并核验 SVG；未放宽渲染门禁。

**最终已验证实现位于 `C:/Users/Administrator/.local/state/devflow/validation/generic-skill-cleanup/current-contract-final/delivery/`。** 主工作区继续出现另一组并发修改，涉及 biz-flow 运行时、core schema、Skill 参考资料及示例，也再次改动了源码写入保护。本轮没有覆盖这些后续修改，不能将固定副本的结果当作当前共享工作区整体通过。差异和绑定见 `current-contract-final/final-binding.json`。前一个 delivery 和所有失败恢复记录继续保留；未提交、发布或改全局安装。

| 验证 | 本轮结果 |
| --- | --- |
| 专项回归 | 401 passed/37 subtests；补修后 265 passed/37 subtests；渲染回归 7 passed |
| 全量固定交付副本 | **835 passed、51 subtests passed**，494.19 秒；源码核对 unchanged=true |
| compileall、git diff --check | 固定交付副本全部 exit 0 |
| 规范 Skill | 四个 frontmatter 检查通过；所有命中的本地 reference 存在，无本机路径或残留三个门面；URL、fixture 引用和 YAML 转义已按语义排除 |
| 发布与隔离安装 | release exit 0；npm 禁用 postinstall 后显式安装，pipx、四个 Skill 同步和 doctor healthy=true；唯一 devflow 入口，安装源码/Skill 与固定副本一致 |

初次全量为 834 passed/1 failed，失败原因是渲染测试命中持久缓存而未捕获新 SVG；原失败日志保留在 `current-contract-final/verification/full-pytest.log`。隔离测试缓存后重新运行完整测试通过，不删除断言、不跳过 renderer。

| 领域 / run | 任务准备 | 子代理执行 | 结果收集 | 领域验收 |
| --- | --- | --- | --- | --- |
| biz `689899df1e8d4816a1656f7e1c79cc54` | 新提交的两个独立入口完成 | 本轮真实复用两位空闲 child，各自重新取证；实际活动快照支持 native/parallel=true | 两项新结果、任务/输入/结果摘要及真实回执通过 | 当前隔离安装版 collect、check、连续两次 verify、accept 全部为 0 |
| sequence `34519e9ed432459f9ba7fde4b6c9d602` | 历史任务绑定有效 | 历史单 child 顺序执行，native/parallel=false；未冒充新执行 | 当前安装版只读验证真实历史结果、回执及失败 attempt | 冻结事实、图形资产和已验收基线复验通过 |
| E2E `a67038eda4f240b2bffd90e76f4a9d18` | 历史两场景绑定有效 | 历史两位真实独占 owner；未冒充新执行 | 当前安装版 owner、scope、结果摘要及历史工具引用通过 | 生成资产与有序静态验收复验通过；场景仍 contract_blocked，不代表可执行测试成功 |
| bru `33b02501496f4f2c989575744ddbe8a2` | 历史两模块绑定有效 | 前序本会话两位真实 owner；本轮未重新执行 | 原 worker-check 和合并证据保留 | 当前安装版 materialize --check、check --all 均为 0；static-valid/draft，0 executed |

新 biz 源码提交 `89a7f62fdc7d0b4c111a100931a10bf4e14e5be4`，package 摘要 `65f5853467cc83ed772349bc838b09a1c5ecb41f8fec5a4cb873d60939209db8`。invoices 由 `/root/ownership_audit`、orders 由 `/root/skill_docs_repair` 独立读取本次冻结源码；各自结果摘要为 `e7f7e94a25e39a319e6fd5b79e63ef6d31a1c32ffaaaaa9221695050ca7b9d8b`、`1bc4424018e0f777b392b593316e39a5ee315eb7e3f6a6bc18fabc6002b0beff`。仅记录源码实际的固定返回，未编造存储、服务或失败路径。

当前 wheel SHA-256：`d1fc08a7e54fc8a662853f4b04c4e5e8d82b6c528c551e6ff0cac9b0fda23172`。工具和领域版本沿用下文已更新的当前主版本，未发布前不机械重复升版。测试后的唯一交付文档修改是本报告；wheel/tgz、缓存和 state 不提交。

最新证据以 `C:/Users/Administrator/.local/state/devflow/validation/generic-skill-cleanup/current-contract-final/` 为根：`delivery-verification/report.json`、full-pytest.log、source-binding.json；`isolated-install/payload-check.json`、doctor.json；`host-biz/preparation.json`、acceptance.json；`sequence-historical-check/installed-verification.json`、`e2e-historical-check/installed-verification.json`、`bru-historical-check/verification.json`；总索引为 `session-evidence.json`，包含本轮真实直接 followup_task/list_agents/结果消息的协调者引用。新 biz 权威 manifest 为 `~/.local/state/devflow/artifacts/biz-flow/689899df1e8d4816a1656f7e1c79cc54.json`。

真实性仍为 host-attested；CLI 仅验证结构与一致性。活动观察时间来源是 coordinator_observed，内部时间不可得、回收工具不支持，均未编造。没有运行 HTTP、业务测试、数据库操作、消息或发布。其他宿主、真实缺工具串行降级、超槽位调度及复杂用户项目未实测。以下内容均为前序历史，不替代本节结果。

## 前序交付与验证边界（历史）

按用户补充要求，不保留旧执行器、旧配置转换、旧字段读取或隐藏回退。规范 Skill 不依赖本机路径、品牌 CLI 或固定宿主工具名称。当前轮新增修补和结果以本节为准；后面的前序记录保留为历史，不能当作本轮结果。

最终固定源码副本通过 **832 tests、51 subtests**，compileall、diff 检查、发布生成及隔离安装全部通过。测试结束时发现其他工作在主仓库修改了 biz-flow 的 cli/discovery/documents/evidence、核心 schema，并新增 text_behavior.py。原工作区的这些变化全部保留，没有覆盖或用旧测试结果证明它们有效。

可审查的已验证 worktree：`C:/Users/Administrator/.local/state/devflow/validation/generic-skill-cleanup/delivery/`。它的 236 个源文件逐字节对应测试固定副本；只在测试结束后更新本报告。最终 wheel、规范 Skill、npm Skill 和隔离安装 Skill 均对应该副本。**当前共享工作区的并发变化尚未合并验证，不能宣称当前工作区全部验收完成。**

### 本轮实际完善

| 范围 | 修改与保障 |
| --- | --- |
| biz-flow | host.py 共用有效回执时间检查，保留失败 attempt 的有效时间来源、起止及回收状态，拒绝重试改写；无效时间格式仍可纠正。native_handoff 新增行为回归，agent-orchestration 同步 |
| sequence | host.py 拒绝未知任务/缺失结果并返回领域门禁错误；native 拒绝串行授权；重叠证据绑定 task/attempt，真实失败也保留、spawn_failed 排除；serial 不派生原生并行，失败历史不可改写。host_handoff 回归及 reference 同步 |
| E2E | host.py 在任何写入前拒绝场景 symlink/junction 别名，保护源码和场景独占范围；Windows junction 行为回归；核心 schema 修复中文资产路径乱码。场景 owner 的受限写入能力保留 |
| bru-api | manifest_io 统一拒绝旧 bru_file/file_name/case.seq；当前字段仅 bru/sequence，Bruno meta.seq 保留。物化、解析、设计映射、覆盖、约束、锁均使用该门禁；删除 copied-checker 导入回退 |
| bru-api 配置 | 移除恒值 shared_cli_mode、恒空 script_bundle_errors、local_scripts 参数、重复本地模板、旧启动器/README 自动替换和旧配置自动删除。当前轻量 shared-cli 启动器保留；不支持的旧配置在写入前拒绝并原样保留 |
| 真实验证发现 | 修复 check_api_coverage 模块过滤错误定位权威锁的问题；始终使用 qa/contracts 的版本文件。回归验证权威锁独有、qa 根伪锁被忽略、权威锁缺失不能用副本替代；离线 provenance 未验证状态不提升 |
| 全部 Skill | SKILL、默认提示词和领域 references 保持自包含；修复 bru 九份参考资料的翻译服务污染/乱码和错误 E2E 路由；示例仅恢复展示字段并改相对路径，请求、断言与证据语义不变；补充 bru/E2E 可执行的用途描述 |
| 安装与版本 | 从权威序列契约生成器生成静态契约，通过 release.py 生成 npm 载荷；未修改全局安装。工具 9.0.0、biz 5.0.0/schema 6/protocol 5.0、sequence 3.0.0/schema 3、E2E 2.0.0/schema 11、bru 2.0.0/schema 7；旧运行不自动迁移 |

### 当前真实执行结果

未配置外部 Agent 执行器。biz 与 bru 使用本轮真实工具重新分派；sequence/E2E 使用此前真实执行记录并以最终安装版复验，没有把旧 child ID 冒充新会话执行。

| 领域与 run | 任务准备 | 子代理执行 | 结果收集 | 领域验收 |
| --- | --- | --- | --- | --- |
| biz `b86da05326064f078c35a96413ec1ed0` | 两个冻结入口完成 | `/root/ownership_audit`、`/root/skill_docs_repair` 独立源码分析完成，真实活动快照支持 parallel=true | 两项成功结果、真实回执与哈希通过 | collect、check、两次稳定 verify、accept 均为 0 |
| sequence `34519e9ed432459f9ba7fde4b6c9d602` | 历史任务及当前绑定有效 | 历史一个真实 child 顺序处理，native/parallel=false；保留失败后重试 | 当前安装版验证任务/结果/attempt/child/引用 | entries、delivery、冻结事实、已验收基线只读复验通过 |
| E2E `a67038eda4f240b2bffd90e76f4a9d18` | 两个真实场景任务有效 | 历史两个真实 owner，重叠引用有效 | 当前安装版验证结果、owner 和独占范围 | 九步有序静态验收均为 0，11 个 seal 一致；新会话 b0ef4314e70d40f29d29e38cfc73c6ae，原 manifest 与业务资产不变 |
| bru `33b02501496f4f2c989575744ddbe8a2` | 两个模块任务完成 | 两个真实 owner 各自分析、物化独占目录；新增各自 materialization-state/module-lock；parallel=true 有真实活动快照 | 逐模块 worker-check 为 0，run 为 domain_checks_passed | 协调者全局 materialize、materialize --check、两个模块 check 和 check --all 均为 0；static-valid/draft，0 executed |

biz 新样例源码提交 `0daf2a79ba53d0400853ab4809a76792f22bec2e`。入口只返回源码确有的 code=0/data=[]，没有推导检索、存储或不存在的失败路径。biz 结果摘要为 `edae7669e4addda3a0bf1d9cf477e719fb5ad5889d7e152997e410acfcc020df`、`14bdb771d9788d21fb5288fad2f8fbbad50ee5c599c423e67cc7a0b5cd47ba6b`；bru 结果摘要为 `71178e2bf2f28f8c5a7195c828f9027ddd0ea22455ed22f45c444307c44fb421`、`c76b5076bc1f7d812146bf9b72f76cee3c559dd58ba23b2103f8cbd226d71cac`。

订单 owner 发现的旧模块 check 路径失败保留在其 diagnostics；没有将失败记录重写。补修后由最终安装版重新通过模块和全局检查。bru run 原报告的 coordinator_merge=pending 保留；协调者后续合并的完成证据单独位于 bru-final-acceptance.json，没有手改 manifest。

后续已授权的 bru 生成新增了 biz run 冻结范围外的 QA 资产，再对该旧 biz run 执行 check 正确得到 READ_ONLY_SCOPE_CHANGED。旧 accept 和原输入/回执均保留；未放宽保护或强行复用旧运行。实际 biz 验收时的安装版与最终 wheel 的 biz/core 源码逐字节相同，两个 wheel 仅 bru checker 不同，记录在 actual-acceptance-runtime-binding.json。

E2E 两场景仍为 contract_blocked，runtime_probe 始终 not_requested；bru 为离线静态有效的 draft。均未执行服务请求、业务测试、数据库操作、消息或发布。其他宿主、真实缺工具串行回退、超额任务排队及用户复杂项目未实测；这些不能由 fixture 或提示词搜索代替。

### 本轮自动与发布结果

| 检查 | 结果 |
| --- | --- |
| 领域与门禁专项 | biz+E2E 125 passed；sequence 72 passed；bru 157 passed/13 subtests；Skill/core/release 13 passed；最终版本锁定向 3 passed/2 subtests，均通过 |
| 最终全量固定副本 | 832 passed、51 subtests passed，584.30 秒；snapshot_unchanged=true |
| compileall / diff | 均 exit 0；主仓库并发漂移如实保留在原 verification/report.json，delivery-binding 证明交付副本对应已测试源码 |
| Skill 路由审查 | 四个规范目录，17 个必读本地 reference 路由无缺失或越界，无翻译服务污染；不是只检查 spawn_agent 字样 |
| release / 隔离安装 | release exit 0；npm 禁用 postinstall 后显式恢复安装，经 pipx、四个 Skill 同步、doctor healthy=true；唯一 devflow 入口，源码及 Skill 字节一致，六个 parser smoke 为 0 |

最终 wheel SHA-256：`113cb30fe74f566d28bf4e4fcab5b324163f98422f7202d45f7811e2b924f01c`。wheel/tgz、缓存和本地 state 均未加入提交。

以下路径均以 `C:/Users/Administrator/.local/state/devflow/validation/generic-skill-cleanup/` 为根：

- 当前会话索引：`session-evidence.json`；测试：`final-pass-current/verification/report.json`、full-pytest.log；交付对账：`delivery-binding.json`。
- 最终安装：`isolated-install-final/payload-check.json`、doctor.json；发布：`release-final-result.json`、release-final.log。
- biz：`biz-actual-validation.json`；权威 manifest 为 state/artifacts/biz-flow/b86da05326064f078c35a96413ec1ed0.json；输入变化拒绝记录：`biz-after-downstream-input-change.json`。
- sequence：`sequence-final-installed-check/installed-verification.json`；E2E：`e2e-final-installed-check/installed-verification.json`、`e2e-ordered-final-current/summary.json`。
- bru：`bru-preparation.json`、`bru-collection.json`、`bru-final-acceptance.json`；权威 report 为 state/artifacts/bru-api/378659dae060f76171649c1b/runs/33b02501496f4f2c989575744ddbe8a2/report.json。
- 并发改动逐文件差异：`concurrent-drift/`；本轮实现保存在 `delivery/`，原项目后续改动继续保留。

宿主真实性仍为 host-attested：上述工具引用是对实际直接 collaboration 调用与消息的协调者索引，不是宿主内部调用 ID 或签名证明。时间不可得时留空；没有回收工具就记 unsupported。CLI 只证明结构和一致性，没有宣称 JSON 全面防伪。

## 全部 Skill 核查

| 规范 Skill | 实际委派点 | 实现、契约与说明 |
| --- | --- | --- |
| biz-flow-doc-generator | 每个确认业务入口，prepare → 宿主子代理 → collect → check/verify/accept | `src/toolkit/biz_flow_doc_generator/{cli,host,validation,orchestration}.py`，核心 schema，SKILL、agent-orchestration、verification；保留逐入口冻结事实、正式补证、模块唯一写入与两次稳定验收 |
| sequence-diagram-generator | 冻结源码 scope 和已有需求映射任务，复用 prepare/collect/check/verify/accept | host/models/workflow/requirements/validation、权威序列契约生成器；SKILL、host-handoff、requirement-mapping 和示例；保留控制树、来源区分、渲染和基线 |
| e2e-test-generator | 多场景独立 owner；单场景可显式 delegate | contracts/host/cli/document_gate/source_versions、核心 schema；SKILL、native-scenario-owners、e2e-workflow、scenario-artifact-policy；独占 `scenarios/<中文业务名称>/`，公共目录由协调者处理 |
| bru-api-test-generator | 全量复核发现 references/parallel-generation 和可达 worker-start/worker-check 确有模块委派点，不能沿用初始“不适用”结论 | 复用 `worker-start --delegate`、`worker-check --run-id --receipt`；host/cli/核心 schema/parallel-generation；两类模块目录独占写入、共享索引由协调者合并 |

全部四个 SKILL、默认提示词、references、可达命令、schema、测试、生成器与载荷已核查。业务线程池、网络请求、测试运行器并发不是 Agent 委派。单场景普通生成和普通 worker 边界不额外启动代理；其门禁继续有效。没有新增动态插件、品牌注册器或第二套执行流水线。

## 前序修补（历史）

| 缺口 | 修补及测试位置 |
| --- | --- |
| biz-flow 版本文件在忽略目录中可能未受冻结保护；docs 别名可逃逸；旧 writer 锁用 `os.kill(pid,0)` 在 Windows 上有终止进程风险 | 冻结版本文件完整字节摘要，accept 后仅保存合法新基线摘要；拒绝缺少新保护的旧 manifest；限制 docs 路径，保护非临时文件；复用核心 ProjectDomainLock。host/cli、test_native_handoff、test_biz_flow_contract |
| 失败后重交可丢失历史，旧错误可能被改成首次成功 | 四领域均保留正确绑定的失败 attempt；新提交必须携带相同失败身份和错误后再连续重试。无效、外来或不一致回执不能污染合法恢复。biz rejected_submissions、sequence rejected receipts、E2E retained_failures、bru attempts-*.json，分别有行为回归测试 |
| 时间端点不足或来源不同导致误拒绝/漏检 | 保留实际可得的单侧时间；活动观察仅与相同来源的已知端点比较；sequence、bru 对全部已启动 attempts 检查同一 child 的宿主区间冲突；活动证据绑定实际 attempt，失败后的重试不能改绑旧观察 |
| sequence 选定需求子集仍可能向 mapper 分派未选片段；空白标签/诊断可通过 | 任务范围遵守 selected_segment_ids，保留完整冻结需求摘要；拒绝空白；权威生成器同步 minimum/pattern，再生成 core/sequence-contracts.json |
| E2E 旧 run 可覆盖当前任务；删除委派标签或改 main_agent 可绕过 ownership/基线 | collection 对照当前 generation.host_task；多场景和曾显式委派的单场景继续执行所有权、冻结输入与有序 seals。未委派单场景保留既有行为 |
| bru 失败记录名过长触发 Windows 路径限制 | 使用 24 位摘要文件名并核对文件内容摘要；不牺牲任务/结果绑定和失败历史 |

这些变更没有删除关键未决、复制 inventory 充当分析、放宽源码证据、修改 critical、填造成功业务结论或扩大测试执行授权。同期另一会话的 biz-flow 行为事实/补证改动已保留；本轮按实际契约集成和验证，未为重用旧运行重新放宽 mapping schema。

## 执行与可信边界

主 Agent 读取 CLI 的真实任务包和 schema，按当前工具及槽位分派实际业务任务、等待、核对后 collect，再执行领域验收。prepare 返回 unknown 是正常等待宿主接入状态。CLI 无法调用会话内工具；不存在 Python 自动宿主启动器。当前宿主 collaboration 工具直接调用，其他宿主以真实名称和调用规则为准。

`mode=native` 与 `parallel` 分开，原生单槽位顺序任务无需串行授权。只有真实宿主区间重叠或活动工具快照支持 `parallel=true`；分派/收信观察区间不能单独证明重叠。没有内部时间/关闭工具时记录 unavailable/unsupported，不编造调用 ID、开始/结束或 reclaimed_at。共享工作区中的提示词约束和范围摘要验证不是 OS 沙箱。

真实执行为 **host-attested**：协调者对照本会话工具与消息记录确认。CLI 只证明结构、输入/任务/结果绑定、覆盖、计数、事件和领域一致性。工具引用是主 Agent 对实际调用建立的索引，不是宿主内部调用 ID 或签名导出；随机 UUID/引用字符串不能证明真实运行。fixture 只用于自动测试，不能进入真实验收。

缺少/禁止工具或不可恢复启动失败才按现有领域规则进入明确串行授权。“直接生成/不用确认”不能视为串行授权；已有授权无需重复询问。原生历史不改成零代理；串行真实分析使用新运行和范围明确的会话选择引用。E2E 复用 init/generate 的 serial-approval 入口，未新增混合执行框架。生成不授权网络、数据库、发布消息或业务测试执行。

删除正常流程的 Codex/Claude CLI 探测、适配、子进程执行和旧 biz-flow NativeAgentExecutor/SubprocessAgentExecutor/DegradedExecutor。旧 review/generate/update 继续明确拒绝。`DEVFLOW_AGENT_EXECUTOR` 不用于判断宿主能力，prepare 忽略无关旧环境变量；没有隐藏外部回退。core/agents.py 仅共享多个真实调用方的记录一致性校验。

工具版本 9.0.0；biz-flow Skill 5.0.0 / schema 6 / handoff 5.0，sequence Skill 3.0.0 / schema 3，E2E Skill 2.0.0 / schema 11，bru Skill 2.0.0 / schema 7。旧运行不自动迁移或补写成新证据。四个权威版本文件保持各领域原路径。

字段和完整交接示例分别位于各规范 Skill 内的 agent-orchestration.md、host-handoff-example.md、native-scenario-owners.md、parallel-generation.md；示例明确为 fixture/说明，不冒充生产回执。安装载荷仅由 scripts/release.py 从规范目录生成。

## 前序真实宿主验收（历史）

没有配置外部 Agent 执行器；样例源码在 state 中独立仓库提交，代理读取冻结提交快照，不读取 dirty 目标源码冒充提交事实。

| 领域 / run | 任务准备 | 子代理执行 | 结果收集 | 领域验收 |
| --- | --- | --- | --- | --- |
| biz-flow `cc9fba632e3f45faad83ca62437fddca` | 两个独立注册入口，完成 | 两个真实 child 完成；实际 list_agents 观察支持 native / parallel=true | 完成，任务/输入/结果绑定通过 | check、两次稳定 verify、accept 通过；最终安装版只读 check 通过 |
| sequence `34519e9ed432459f9ba7fde4b6c9d602` | 两个冻结 scope，完成 | 单槽位复用真实 child，native / parallel=false；第二任务真实失败 attempt 1 后修正 attempt 2 | 完成 | 原实际 Mermaid 渲染、verify/accept 通过；本轮安装版 entries/delivery 与 handoff/基线只读复验通过，manifest 未变 |
| E2E `a67038eda4f240b2bffd90e76f4a9d18` | 两个独占场景任务，完成 | 两个真实 owner 完成，真实活动观察支持 parallel=true | 完成，owner、摘要、范围一致 | 当前安装版静态/所有权/场景检查通过，历史有序 seals 一致；新鲜有序静态复验结果见下文 |
| bru-api | 自动测试覆盖任务准备；真实样例在 understand/generate 设计门禁处阻断 | 未到真实 worker 分派 | 真实 worker 集成未验证 | 自动回归通过，不能推导真实业务集成通过 |

新 biz-flow 源提交 `685740e8d7931e194b89b8f5e7bb7a2108dff287`；package 摘要 `3e9458a7551ac58518a4539ea5e1f03fa4c4a37485fcf94e98ac7189463141ba`。invoices 绑定 `/root/sequence_native`，结果摘要 `c7c55c5e0265652520f35d830ea0eafa4444ccb9ff98533bfc20e3196dc91b17`；orders 绑定 `/root/sequence_impl`，摘要 `8c6dad9fcd05e808acf2a8b24b3a6761216ac5cb9235faa881e7f55a890289a4`。两个实际 followup_task 与子代理消息、工具活动观察由 session-evidence.json 索引。

本轮旧 biz-flow `97d96818c8ef42df84f076984bc23956` 两子代理确已完成；随后另一会话改变 mapping schema，collect 正确拒绝。保留原任务、结果和诊断，使用干净样例和固定安装版重新 prepare 上述 cc9 运行，没有改写旧 manifest 或沿用旧任务身份证明。更早的 c68、fa135、协议 4 记录仅作历史；缺少当前字段/保护时不继续宣称当前有效。

E2E 两场景为 contract_blocked：样例没有 HTTP 注册，未请求 runtime probe，也未执行业务测试。静态生成验收不能证明环境就绪或补出缺失的 HTTP 能力。历史有序会话过期时，当前 complete 正确报告 gate-order；没有手改时间/状态续期。新鲜有序静态验收已在最终安装版完成：`workspace_inventory`→`dependency_topology`→`initial_configuration`→`runtime_probe`→`control_matrix`→`scenario_split`→`scenario_ownership`→`shared_integration`→`static` 九步均为 0，session `221a9ad2e3c848f683cc2277a04caf7d` 到达 complete，11 个 seal 一致，runtime_probe 前后均为 not_requested。

bru-api 样例缺少明确 Request/Assert，并触发实际设计解析/版本冲突，日志保留。没有为通过门禁编造 QA 预期、修改已验收业务事实或泛化放宽解析器；该真实集成仍未验证。其他宿主工具集成、无原生工具宿主的真实串行降级及用户项目的复杂链路也未实测。

## 前序自动与发布验证（历史）

| 检查 | 结果 |
| --- | --- |
| 领域专项 | biz 54 项、路径/单侧时间 6 项、writer lock 1 项及版本/幂等/锁 3 项；sequence 72 项；E2E+core 225 项（6 subtests）；bru+core+Skill/release 217 项（28 subtests），分别通过 |
| 最后 biz 时间来源回归 | 4 passed；Skill/release 契约 7 passed |
| 最终 `python -m pytest -q` | **815 passed，38 subtests passed**（最终固定副本，1062.01 秒） |
| compileall 与 git diff --check | 通过（最终固定副本，snapshot_unchanged=true，workspace_drift=[]） |
| 序列契约生成 | 从 scripts/generate_sequence_contracts.py 生成，未手改副本 |
| scripts/release.py | 通过；wheel 仅 devflow 控制台入口；每个注册 Skill 一个规范目录 |
| 隔离 npm → pipx → Skill → doctor | 通过：禁用 postinstall 后显式 install，四个 Skill 与规范目录/npm 树逐字节一致，wheel 与 Python 源逐字节一致，doctor healthy=true，六个相关 parser smoke 通过 |

最初本轮全量 809 passed、38 subtests passed，但结束时一个 Skill reference 发生外部修改，不作为最终无漂移结果；之后补齐 biz 时间来源修补并重新固定最终快照。历史 730 项结果只作历史证据。最终报告是在验证结束后更新的说明文件，不改变已验证代码、测试或 Skill。

最终交付 wheel SHA-256：`442540f16241fd167c35ba95650882a18e2dddb48aeaaee27eab08fa29678d19`，与当前 npm tgz 内嵌 wheel 一致。此前领域复验安装包摘要为 `91d2cc4ffcec66d986ddeb4ae9d263f917fcd909eda0653bb72516640e4bdded`；两个 wheel 的全部成员内容逐字节一致，打包归档元数据不同。最终归档另行完成隔离安装检查，源码与 Skill 均一致。wheel/tgz、缓存和本地 state 均未加入提交内容。

## 前序脱敏权威路径（历史）

- 最终全量日志、检查结果和源快照摘要：`C:/Users/Administrator/.local/state/devflow/validation/native-audit/final-pass/verification/`。
- 本轮会话索引：`C:/Users/Administrator/.local/state/devflow/validation/native-audit/session-evidence.json`；旧真实记录索引保留在 `validation/native-unification-3u92r47o/session-evidence.json`。
- biz manifest：`C:/Users/Administrator/.local/state/devflow/artifacts/biz-flow/cc9fba632e3f45faad83ca62437fddca.json`，同名目录含 actual-domain-validation.json、源码摘要、两项结果和各阶段输出。最终安装版只读报告：`validation/native-audit/biz-final-check.json`。
- sequence manifest：`C:/Users/Administrator/.local/state/devflow/artifacts/sequence-diagram/runs/34519e9ed432459f9ba7fde4b6c9d602/manifest.json`，同目录有原 host-execution-report、verification 和实际验收输出；本轮复验：`validation/native-audit/sequence-final-check/summary.json`。
- E2E manifest：`C:/Users/Administrator/.local/state/devflow/artifacts/e2e/537fcf459bd907e54f0bedf2/a67038eda4f240b2bffd90e76f4a9d18/manifest.json`；本轮只读报告：`validation/native-audit/e2e-final-check/installed-verification.json`；当前有序验收：`validation/native-audit/e2e-ordered-final/`。
- bru 输入阻断：`C:/Users/Administrator/.local/state/devflow/validation/native-audit/bru-understand.json`、bru-generate.json。
- 最终安装证据：`C:/Users/Administrator/.local/state/devflow/validation/native-install-audit3/payload-check.json`、doctor.json；此前固定安装版的领域复验日志继续保留原工具路径。

已覆盖需求中的真实 biz 两入口、sequence 原生交接、E2E 两场景、真实多代理重叠和单槽位 native 顺序执行。上述未验证项继续如实保留；不能宣称所有领域、所有宿主及业务运行全部验收完成。
