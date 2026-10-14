# 两阶段可重复验证

修改 Skill/实现后先执行相关测试，再执行仓库规定的完整 pytest、compileall、git diff --check。发布由 scripts/release.py 更新 npm 载荷，验证规范树一致及隔离 npm -> pipx -> Skill -> doctor，最后在实际安装上测试。

## 第一阶段

```text
devflow biz-flow init --project <fixture>
devflow biz-flow discover --project <fixture>
devflow biz-flow check --project <fixture> --stage entries
```

在无代理可用环境也必须完成入口目录。检查只有真实注册业务入口，线程池/普通辅助方法无独立入口身份；同 HTTP 的 Controller/Application 去重，独立消费者和恢复任务保留。覆盖适用注册类型；不支持/动态范围报告缺口，不能虚报无遗漏。

核对全部候选 = 业务 + 排除 + 待识别；业务 ID 集合 = 总览 = 最终模块入口章节，单一归属。每入口有名称、trigger、源证据，排除有原因。所有模块按项目一级业务域建立业务化 Markdown 骨架，同域的配置、查询、回调、恢复及不同渠道在同一文件，跨域入口只归属主结果域；保留各入口业务链路差异，无占位图。对话/CLI 与总览完整三列内容一致。文件名以业务域和主要功能的一句业务化概括让读者大致知道文件内容，不能只写域名或缩写、堆叠技术标识、罗列全量入口动作或按功能拆域；业务描述独立于文件名，参考 Swagger 分组说明、接口摘要和业务注释归纳主要能力；同类接口合并，允许分号和多句，不用“负责 + 文件名摘要”或逐接口清单替代。完整入口清单另表保留，不能把简洁概括当成遗漏入口。排除及识别疑点按类别数量原因显示。

发现产物不得携带深调用链、分支、持久化审核未决。连续两次 discover 保持 ID、排序、归属稳定；用户局部修改不影响其他模块。已发现候选的身份/归属未决阻止该范围定稿；不支持或动态注册单列覆盖缺口，不阻断其他可证明入口。

协调者根据完整入口清单复核文件名是否自然表达业务对象及核心职责、关系或生命周期，描述是否有 Swagger 或源码说明依据、保留主要功能对象并合并同类接口；确认多句内容未被截断、client/HTML 元数据已清理、共享 Controller 的其他域能力未混入。参考项目业务文档时只提取命名风格，不能硬编码其模块名；长域应概括功能族，不能强加“处理”“业务”“流程”等后缀或堆全量功能动词。仅有动作串或“日志查询”等过泛名称时，依据源码业务标签通过现有分类调整路径纠正，保持业务域 ID 和全部入口归属不变，不把可由源码解决的命名问题推给用户。命名摘要负责概括，无遗漏由完整入口清单验收，不新增命名确认机制。

## 第二阶段

取得一次分类授权后：

```text
devflow biz-flow prepare --project <fixture> --confirm
devflow schema biz-flow.submission
# 主 Agent 读取实际任务包，调用原生工具、等待并核对结果，写入脱敏交接文件。
devflow biz-flow collect --project <fixture> --run-id <run-id> --results <state-submission>
devflow biz-flow check --project <fixture>
devflow biz-flow verify --project <fixture>
devflow biz-flow verify --project <fixture>
devflow biz-flow accept --project <fixture> --run-id <run-id>
```

prepare/collect 阶段使用宿主原生子代理或明确授权的串行会话；必读 behavior-evidence.md、agent-orchestration.md 及实际 entry-result/entry-analysis/entry-facts schema。检查只读源码、每入口独立结果、真实 child/attempt、可得时间来源和实际回收状态及模块单写者。无回收工具记录 unsupported，不编造 reclaimed_at。native + parallel=false 有效，只有实际重叠证据才报告并行。确认所有关键分支、错误映射、异步返回/后台执行、状态变化、真实存储及外部动作；fact/step ID 在事实、Mermaid 注释、矩阵、manifest 一致。独立对照提交源码与冻结 entry_facts.flow，核对调用/返回顺序、控制块嵌套、跨方箭头及成功/失败路径；annotations 不能修改事实。补证经适配器验证后新建运行并重新实际分析，不复用旧回执。

工具缺失、明确禁止或无法恢复的启动失败时，沿用当前范围已有明确串行授权；没有授权则一次提供串行/停止选择并保留准备任务。槽位不足应等待或分批，不是无原生能力。“直接生成”不构成串行授权。完全串行结果必须有 serial_approval 范围及选择引用、degraded=true、parallel=false、completed_child_agents=0，不能抹除之前子代理的执行历史。

注入无效源位置、未知结果相关分支、缺少真实存储对象、占位步骤、失效 fingerprint、重复写入者、错误 Mermaid，相关入口/模块必须失败且不推进基线；其他完整模块可保留，不声称整体完成。渲染器存在则实际渲染；缺少渲染器明确结构验证范围。

check/verify 必须保存逐门禁 executed/passed/errors，不能将未执行写成通过。破坏任一模块内容或图后 check 必须失败；修复后可重试。分别验证入口对账、Markdown/分支/持久化覆盖、业务占位文案和 Mermaid 渲染。默认渲染超时 60 秒，成功图按内容和渲染器哈希缓存，超时/失败不缓存。源清单与行为缓存的键包含提交、指纹和适配器信息；缓存不能改变运行 target。

验收前 verify 失败必须清零连续成功次数，修复后重新通过两次 verify 才能 accept。验收后重复 verify 保持 accepted，使用固定提交重建事实；不能因源码快照已清理而回退状态或使后续 check/collect 失效。prepare --module 的验收即使覆盖当前全部入口也不推进项目基线。将运行目录或 source 目录替换为软链接/junction 必须拒绝，不能删除别名目标；源码清理失败不能推进版本锁，解除故障后可以重试 accept。

向运行注入旧/缺失协议、旧/缺失 schema 或旧 adapter，prepare --resume、collect、check、verify、accept 均须拒绝并保持旧文件及版本锁原样。最新运行不受支持时默认命令必须停止，不能自动回退到更早运行；其他项目的旧运行不影响本项目诊断。即使重算哈希，错误协议或领域的任务包仍须拒绝。旧/无效 accepted 记录不得计入局部验收汇总。

自动化夹具至少检查 Java/Spring+JPA、Python/FastAPI+SQLAlchemy、TypeScript/Nest+Prisma 的 prepare → collect → check → verify×2 → accept，并在串行、原生顺序和带并行观察回执的模式运行。夹具回执仅用于测试，不是实际会话执行证据。对同 target 加脏文件、移动 HEAD、加入 agent worktree 后指纹与基线仍相同；快照篡改必须失败。用户改名、描述和归属经过两轮 prepare/collect 保持稳定。模块范围含阻断入口时其余模块可独立验收。重复生成的模块字节一致，失败 collect 不丢映射。

## 增量、版本和交付

在 Git 夹具提交新增/修改/删除入口或共享调用变化后，新建 discover/prepare 运行并实际分析，再 collect、check、两次 verify 和 accept。只支持当前 prepare/collect 流程。验证新增归属需确认、受影响入口重分析、删除章节同步清理、未变内容保留；无法读取已验收 commit 时报告无法增量比较，重新分析完整范围。核对 commit、dirty、fingerprint 和唯一版本 JSON，任何失败保持原 source.git_commit。

最终对话直接输出完整三列模块表及排除/疑点类别，不用链接替代；同时返回已脱敏外部 manifest、退出状态、各入口类型覆盖、逐入口未决、两次稳定性。实际目标项目的扫描及流程文档证据是验收依据，夹具通过不能代替实际项目验证。
