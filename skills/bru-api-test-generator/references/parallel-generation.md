# 模块原生子代理委派

本工作流复用现有 `worker-start`、`worker-check`，适用于独立模块生成；普通业务/网络/测试并发不属于 Agent 委派。先冻结已授权的 OpenAPI、模块映射、执行配置、`qa/constraints/rules.yaml` 和已验收业务设计。业务规则与预期结果继续来自 biz-flow 已确认资产，源码只能补运行支持事实。

一次准备完整授权模块集合，避免每个工作器把合法同伴的写入当成越界：

```text
devflow bru-api worker-start --qa-root <absolute-project>/qa --delegate --module <module-A> --module <module-B> --stage generation
devflow schema bru-api.worker-task-package
devflow schema bru-api.worker-result
devflow schema bru-api.worker-submission
```

CLI 返回 `state=tasks_prepared`、`host_capability=unknown`、run ID、task package 与摘要。这表示等待主 Agent 接入，不是完成，也不是宿主没有能力。任务包及所有交接位于 `~/.local/state/devflow/` 下的 bru-api 领域；不要在被分析项目根目录创建脚本或结果 JSON。项目内 worker-assignments 不作为执行输入；只使用当前准备的 state 任务包。

主 Agent 读取任务包和实际 schema，按当前工具列表使用宿主原生启动/等待/消息/继续任务工具。名称和调用形式以宿主说明为准；宿主要求直接调用的工具必须直接调用，不能假设 Python 能调用会话工具。首次真实业务任务启动即验证能力，不创建无业务用途的探测代理，不检查 PATH、品牌 CLI 或执行器环境变量。独立任务在空闲槽位允许时同时派发，超出槽位则等待、分批或复用空闲代理；不得嵌套派生绕开限制。

任务中的 `write_scope` 是两个独占目录：`qa/contracts/modules/<directory>/` 和 `qa/bruno/<directory>/`。子代理可写所属 API 契约、用例、logic、模块物化状态、模块锁和 Bruno 请求；只读源码、业务资产、其他模块、共享配置、`index.yaml`、`generation-state.yaml`、全局锁、版本和 `qa/reports/`。只在自己的 state `result_path` 写交接。生成授权不包含实际执行测试；`run`、preflight、数据库写入和外部请求须另有明确授权。

宿主若共享工作区，`permission_enforcement=shared_workspace_instructions` 只声明提示词限制，不能声称启用了 OS 沙箱。确实使用宿主隔离、worktree 或暂存补丁时才声明对应保障。CLI 校验本 run 所有授权模块外的工作区内容未变、各任务报告只涉及自身目录，并在最终收齐时复核各模块输出。它不能仅凭共享文件系统快照把同伴目录的某次写入准确归因到某个进程；主 Agent 必须保证同一文件只有一个活动所有者，并对照真实工具记录审查。无法保证时使用现有隔离/暂存补丁方式后提交，不以提示词冒充强隔离。

子代理完成真实生成后返回 `bru-api.worker-result`，含 `attempt`、所属目录的实际 `artifact_hashes`、`changed_paths` 和自己的分析 `diagnostics`。可以使用安装包的 `toolkit.bru_api_test_generator.host.worker_result(qa_root, package, task, attempt=..., diagnostics=...)` 仅计算实际文件摘要；该函数不启动代理、不替代生成或源码分析。主 Agent 只转换格式，不编造业务结论。

主 Agent 将结果和实际执行证据组装为 `bru-api.worker-submission`。字段来自 schema：绑定 run/task/package/task/input/result 摘要，`attempts` 从 1 连续递增，最多 3 次；失败保留错误和真实子代理/工具引用，只有最后一次可为 success。`record_origin=host-attested` 表示主 Agent 已对照当前宿主提供的实际工具记录；fixture 只允许在显式测试入口使用，生产校验拒绝。`time_source=host` 只用于宿主提供的内部时间；主 Agent 观察用 coordinator_observed；不可得时使用 unavailable 和空时间。没有关闭工具用 reclaim_state=unsupported，没有观察到回收用 not_observed，不能填造 reclaimed_at。

任务失败时也保留交接与实际目录摘要，不能把失败改写成成功。正确绑定且一致的失败 attempt 由 CLI 保存到本 run 的 `attempts-*.json`，运行仍未完成；恢复提交必须完整保留这些失败记录，再追加连续的新 attempt。其他 run 或不一致的回执不能冻结本 run 的失败历史。

逐模块提交 state 中的显式文件：

```text
devflow bru-api worker-check --qa-root <absolute-project>/qa --module <module-A> --run-id <returned-run-id> --receipt <state-receipt-A> --stage generation
devflow bru-api worker-check --qa-root <absolute-project>/qa --module <module-B> --run-id <returned-run-id> --receipt <state-receipt-B> --stage generation
```

阶段必须匹配准备时冻结的 stage。相同包和结果重复提交幂等；不同成功结果、陈旧输入、越界输出、缺证或领域门禁失败均拒绝且保留 state 诊断，不推进权威版本。只完成部分任务时报告 partial，唯一成功 child 集合决定子代理数，不能用模块数代替；复用同一代理只计一次。

native 与实际并行度分开：单任务、单槽位或快速完成可正常得到 `native + parallel=false`。并行报告必须有宿主精确执行区间重叠，或真实 active status 快照 `active_observations`，绑定 observed_at、active_task_ids、active_child_agent_ids、active_attempts、time_source、tool_reference。协调者的派发/收信时间区间不能证明实际重叠。最终收齐后 CLI 才校验这些跨任务证据；不人为延长任务制造重叠。

活动快照精确绑定当次实际启动的 attempt；其后失败不抹去当时的活动事实。所有已启动 attempt 的宿主内部时间都参与同一 child 的重叠冲突检查。仅在同一声明来源内比较快照与已知的时间端点；缺少一侧时间不要求编造，也不能忽略已有端点的矛盾。

工具缺失、被宿主禁止或不可恢复启动失败时，保留具体依据；没有明确串行授权则一次提供串行或停止选择。“直接生成”“不用确认”不是串行授权。已有范围明确的授权无需重复询问。串行重新准备时用 `--execution-mode serial --execution-approval <explicit-session-choice-reference>`，由主 Agent 真实完成分析/生成，报告 degraded=true、parallel=false、零子代理；不能改写旧 native 历史。原生顺序执行不降级，不需要此授权。普通不带 delegate 的 worker-start/check 只提供本地边界检查，不构成子代理执行证据，也不能用于静默串行回退。

最后主 Agent 检查 `report.json`、manifest 与真实会话引用，再按已有流程合并共享设计映射、索引、generation state，全局物化/锁校验和最终中文报告。run 的 domain_checks_passed 仅说明冻结阶段的所有模块检查通过，coordinator_merge=pending 不等于整体 QA 验收或测试执行。`host-attested / structure-and-consistency-only` 明确 CLI 只能证明结构和一致性，UUID 或引用字符串本身不能机器证明真实执行。保留脱敏权威路径，分别报告准备、执行、收集、领域检查和最终合并；任何必需项失败不得声称统一完成。
