# 代理编排与证据协议

## 两阶段角色和写入权

第一阶段的 CLI/协调者维护注册入口清单、模块归属、总览及 仅含标题的 Markdown 骨架，不需要代理执行器。第二阶段按已确认入口创建只读分析任务，使用有界并发；每个模块绑定唯一写入者，等待所需入口结果并验证合并后才提交最终文档。禁止多个代理共同编辑同一文件。

module 对应一级业务域而不是单个动作或渠道；同域的不同链路通过独立 entry 结果和章节保留，跨域入口只提交主业务结果域的写入者。运行记录保留 `coordinator -> module -> entry` 所有权关系，但不要求每个角色都启动独立模型进程；真实并行发生于只读 entry 子代理。批次可以按并发上限分批调度，不得把一个大模块一次启动无限子进程，也不能串行运行后宣称 parallel=true。模块任务提交、等待及写入事件必须可核查。协调者不代替失败入口代理编写业务行为；入口代理不修改源码、Markdown、映射或版本文件。渲染与文件替换由模块写入能力持有者完成。

## 入口结果

每个任务绑定入口身份、确认归属、指纹、提交快照和冻结 `entry_facts`，只读取相关可达行为和待复核项。先读取 `devflow schema biz-flow.entry-result`、`biz-flow.entry-analysis` 和 `biz-flow.entry-facts`。当前为领域 schema 6、宿主协议 5.0。下面是 **fixture 形状示例**，占位 ID/哈希不可提交生产验收：

```json
{
  "kind": "analysis",
  "analysis": {
    "entry_id": "<task.entry_id>",
    "source_fingerprint": "<facts.source_fingerprint>",
    "facts_hash": "<canonical digest of facts>",
    "review": {
      "trigger": {"text": "已核对的业务触发", "evidence_refs": ["<source-id>"]},
      "purpose": {"text": "源码支持的业务目的", "evidence_refs": ["<source-id>"]},
      "input": {"text": "实际接收的业务输入", "evidence_refs": ["<source-id>"]},
      "outcome": {"text": "源码支持的结果边界", "evidence_refs": ["<source-id>"]},
      "failure": {"text": "源码支持的失败边界", "evidence_refs": ["<source-id>"]}
    },
    "annotations": [
      {"target_id": "<fact-or-participant-id>", "text": "源码支持的业务表述", "evidence_refs": ["<related-source-id>"]}
    ]
  }
}
```

子代理必须独立阅读提交快照，核查完整可达链；不能复制静态清单作为完成分析。`annotations` 精确覆盖 calls、branches、persistence_actions、effects、outcomes 中每个 fact_id 和每个 participant_id，无重复、未知或缺失项。引用必须属于本入口事实，并与对应目标相关。业务名称、条件、规则及结果不能补写不存在的内容。入口缺少名称、注册证据或归属属于关键未决；已证据充分排除的候选不创建行为任务。

## 时序与控制结构

冻结 `entry_facts.flow` 表达真实执行顺序、调用返回、控制结构及入口/后台阶段。子代理只提供证据绑定的业务表述，不能调整事实顺序、条件、对象、控制树或可达性。不能按文件行号/声明顺序重排事实，或把条件平铺后追加无条件成功。

CLI 从冻结事实及注释渲染 Mermaid 和矩阵；fact/step/source ID 保留在元数据及注释，可见表述使用业务语言。参与方、资源真实名称、调用方向及返回箭头必须由源码事实支持。图示不能将后台完成描述为入口同步完成；不能仅凭结果概述虚构统一响应。

review 的 trigger、purpose、input、outcome、failure 使用简短中文表述及 evidence_refs，长度遵循实际 schema；路径及实现细节留在证据中。凭据脱敏不影响已证明的控制流时不增加虚假的缺口。普通内存字典不是外部持久化，不能虚构数据库、外部副作用或成功路径。

## 静态证据与代理补证

第二阶段证据层用静态注册的适配器冻结 calls、branches、persistence_actions、effects、outcomes、flow、sources、coverage 和 gaps。代理读取注册及调用方/被调用方证据，不把代码事实转交用户，也不反向编辑 entry_facts、manifest 或源码。

缺失事实通过 `kind=evidence_request`、`evidence_requests=[...]` 提交，先读 `devflow schema biz-flow.evidence-request`。请求绑定 run_id、task_id、entry_id、source_fingerprint、facts_hash、finding_id、target_id、type、path、controls、sources 和 binding。sources 使用冻结的完整源码证明；binding 给出声明/接收者/参数及分类，不能仅靠行号声称语义已证实。CLI 验证请求后由注册适配器重建事实，生成关联旧运行的全新任务包；主 Agent 必须实际重新派发，不能用旧分析或旧回执验收新包。对适配器已证明的三类解释，使用 analysis.resolutions 并遵守 behavior-evidence.md 的完整证据、路径和 controls 要求；说明不修改机器事实。无法合法补证时保留关键缺口并停止相关验收，不降级 critical 或手改冻结事实。

每个要求覆盖的事实都必须有注释，并保持结构化事实、Mermaid 注释、矩阵和 manifest 一致。无数据库动作不要求数据库参与方。任何关键 gap 或不完整 coverage 阻止最终分析验收；内部无关疑点不能混作已确认业务缺口。

## 宿主交接、失败和局部完成

`prepare` 只导出脱敏任务包，`host_capability=unknown` 是待会话判断，不代表不可用。不探测品牌 CLI 或用已废弃的执行器环境变量判断能力。必须按下列步骤接续，不能在准备后结束任务：

1. 读取 CLI 返回的 task_package、manifest，以及 `devflow schema biz-flow.task`、`biz-flow.entry-result`、`biz-flow.entry-analysis`、`biz-flow.entry-facts`、`biz-flow.receipt`、`biz-flow.submission`。每个 task 的 task_hash、input_hash、冻结 source_commit/source_snapshot、snapshot_hash 和独占 result_path 都由 CLI 给出。
2. 主 Agent 对照当前工具表，为首个真实入口调用宿主原生启动工具（例如当前宿主的 collaboration.spawn_agent）。将该 task、对应 entry_facts、冻结快照、问题、结果 schema 和权限交给子代理。记录真实返回的 child ID。工具要求直接调用时直接调用；名称和调用形式都以宿主说明为准，不通过 Python 或 functions.exec 伪装启动器。
3. 在当前可用槽位内并发启动独立入口；满槽时等待、分批或复用已空闲代理。使用实际消息/等待/继续工具收集结果，不把运行中当作失败。每次任务或重试独立记录 attempt，不能混用旧结果或嵌套派生绕过槽位。
4. 对照真实记录核对结果、证据和权限。仅做格式转换，不替失败子代理填写结论。将全部逐入口结果和回执写到 state 交接文件，再运行 collect。collect 后运行 check、连续两次 verify、accept；其中任一必需任务失败，不报告整体完成。

执行 manifest、任务包和结果位于 `~/.local/state/devflow/artifacts/biz-flow/`。子代理只读提交快照、资产及锁，只写自己的 result_path。实际权限保障为 `coordinator_scope_check`：共享工作区没有 OS 隔离，CLI 核对冻结源码快照、业务资产、映射及版本锁。工作区由用户或其他任务产生的源码编辑不影响固定 target。不能在被分析项目创建临时脚本或结果 JSON。主 Agent/CLI 是最终模块写入者。

回执至少绑定 run_id、task_id、task_hash、input_hash、child_agent_id、result_hash、attempt、status 和 tool_references。record_origin 为 host-attested；宿主事实由主 Agent 对照当前宿主提供的实际工具记录确认，CLI 只校验结构与一致性，不提供 JSON 防伪。宿主没有精确时间时，time_source 使用 coordinator_observed（仅是调用前后/收到结果的观察时间）或 unavailable（时间均为 null）；只取得开始或结束之一时保留该真实时间，另一项为 null，不补造完整区间，也不据此证明重叠。不要把观察时间称为子代理内部时间。reclaim_state 为 unsupported/not_observed 时 reclaimed_at 必须为 null；reclaimed 仅用于实际回收工具结果。任务完成、代理空闲与代理关闭分别说明。

mode=native 与 parallel 独立。单任务、单槽位、任务依赖或快速完成均可 native+parallel=false。parallel=true 需要宿主实际时间区间重叠，或 active_observations 中带 observed_at、time_source、tool_reference 和至少两个不同任务、不同 child 对应的 active_task_ids。每个 active_task_ids 值必须为 `<task_id>:<attempt>`，精确绑定该次已实际启动的回执、真实 child 及观察区间；真实启动后失败的 attempt 可保留活动证据，但不能将旧快照改绑到重试。spawn_failed 不可出现在活动快照。不带 attempt 的观察记录不符合当前契约，不能作为新运行证据。单凭分派/接收时间包围的区间不能证明重叠。同一来源的重试观察不得早于前次结束；同一 child 不可拥有不同任务的重叠宿主内部时间区间。不要延长任务制造重叠。

活动观察只与相同 time_source 的已知起止端点比较，不混用宿主内部时间和主 Agent 观察时间；只有一侧端点时仍检查该侧，缺失时间不补造。

无工具、宿主禁止或无法恢复的启动失败才进入串行授权流程。已有本范围明确授权继续使用；“直接生成/不用确认”不等于串行授权。serial_approval 保存 choice_reference 和精确入口 scope，mode=serial、degraded=true、parallel=false、completed_child_agents=0、receipts=[]。主 Agent 必须真实取证。先前有原生任务参与而后需要串行时，新建明确授权的运行并关联旧诊断，不清零历史。

以下是 **fixture 字段示例**，不能作为真实执行记录提交；ID、哈希、引用须从当前任务包与实际工具结果取得。生产 collect 明确拒绝 record_origin=fixture：

```json
{
  "run_id": "<prepared-run>", "task_id": "<prepared-task>",
  "task_hash": "<task.task_hash>", "input_hash": "<task.input_hash>", "batch_id": "<host batch identifier>",
  "child_agent_id": "fixture-child", "attempt": 1, "status": "success",
  "result_hash": "<sha256 of canonical result JSON>", "error": null,
  "record_origin": "fixture", "tool_references": ["fixture://spawn", "fixture://result"],
  "time_source": "unavailable", "started_at": null, "finished_at": null,
  "reclaim_state": "unsupported", "reclaimed_at": null
}
```

提交顶层使用 protocol_version="5.0"、run_id、source_fingerprint、mapping_hash、package_hash、mode、parallel、completed_child_agents、serial_approval、execution={receipts,active_observations} 和 results={entry_id:entry-result}，具体以实际 schema 为准。结果哈希覆盖完整 kind/analysis 或 kind/evidence_requests 包装，采用 UTF-8 JSON（ensure_ascii=false、sort_keys=true、separators 为逗号/冒号）的 SHA-256。completed_child_agents 是成功回执的唯一 child 集合大小，不能用入口数替代。失败 attempt 保留错误与输入绑定，只允许每任务一个最终成功结果。

实际启动失败且宿主未创建子代理时使用 status=spawn_failed、child_agent_id=null、result_hash=null，保留非空 error 和真实失败调用的 tool_references；不得编造 child ID 或回收记录。仅 spawn_failed 允许 null child，其余状态必须有真实非空 child ID。重试继续同一 task 的连续 attempt，提交时同时保留启动失败与后续成功；未创建的 child 不计入 completed_child_agents，也不能作为活动重叠证据。只有启动失败回执、缺少必需成功结果的运行仍被拒绝，不写业务资产或推进基线。

collect 拒绝后，已绑定本 run/task/input 的有效失败 attempt 保存在 rejected_submissions。后续提交必须继续携带相同的身份、状态、错误、工具引用、时间来源、有效时间与回收状态，再以递增 attempt 重试；不能省略旧失败、重写有效观察或用相同编号换成成功。无效时间格式可以纠正；未绑定、时间不一致或包含虚构 child 的无效回执不冻结为真实失败。

相同包及相同提交幂等；不同结果、陈旧输入、跨运行、未知/缺失任务或重复成功全部拒绝。可纠正格式失败保留诊断和原准备状态，不手改 manifest。范围、提交或映射实质变化必须重新 prepare。跨会话恢复只复用既有已收集事实；旧 child ID 不能当作新会话的工具执行证明。

`collect` 重新校验运行身份、源码和映射指纹、逐入口覆盖、结果 schema、证据完整性及执行记录。失败保留诊断、提交和入口目录；可纠正交接错误不伪造完成或手改状态，不自动降级。成功生成模式复用同一业务分析校验、Mermaid 渲染和模块唯一写入；`audit` 只保存审核结果，不写最终文档。

`check` 和每次 `verify` 都核验当前运行的提交事实与工件；同 target/fingerprint/adapter 可复用规范缓存，结果和文档逐次校验。只有相同事实、结果和文档哈希连续通过两次 verify，`accept` 才能按完整范围推进源码基线。使用 prepare --resume 时只重派 pending 入口，最终提交仍包含完整范围及未变的真实回执。

## 分诊后执行

启动当前包任务前读取 prepare/resume 的 behavior_report 和冻结 facts。无 gap 仍须独立分析提交快照中的全部可达行为；blocked 入口先按 behavior-evidence.md 核对精确补证或修复 adapter。其他完整模块可另建 --module 运行推进。新包全部必需任务使用真实新结果及回执；旧包的已完成子代理身份不成为新包执行证明。原生能力及可用槽位仅以当前会话工具为准。
