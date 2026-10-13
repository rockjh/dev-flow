# 原生场景所有者交接

本流程沿用 E2E 的设计确认、generate、check 和有序领域门禁。主 Agent 是唯一协调者；
CLI 只准备与验证任务，不能调用会话工具，也不能证明 JSON 中的工具调用真实发生。

1. 完成设计、协议和已提交源码发现，运行已安装 `devflow e2e generate --project <授权项目>`。
   多场景返回 `host_handoff.status=tasks_prepared`。单场景明确要委派时增加 `--delegate`。
   `init` 带设计/协议输入生成多场景时也会返回同样的任务交接，必须继续下列分派、收集与验收步骤。
   起始场景是待分析资产，不是子代理已完成的结果。`generation.host_task` 在准备时标记冻结任务，
   `owner` 要到真实收集后才绑定 child；准备状态不能验收。只使用返回的任务，不能手改冻结任务或 manifest。
   原生任务准备或收集失败时保留文档旧基线和 pending_changes。首次原生运行的基线可以为 null，
   通过 check 完成收集与有序验收后才建立基线；不能借 init、source-status 或聚合 contracts 提前推进。
2. 读取 `devflow schema e2e.host-task`、`devflow schema e2e.host-results` 以及返回的 manifest/task 文件。
   当前宿主的实际工具列表和调用结果决定能力；未判断、工具可用尚未启动、槽位不足、明确禁止、
   工具缺失、实际启动失败、已启动任务失败须分别记录。`tasks_prepared` 不表示宿主不可用。
3. 用当前宿主提供的实际工具分派业务任务，名称及调用方式遵守宿主说明。
   宿主要求直接调用的工具必须直接调用。首次业务任务同时验证启动能力，不创建无业务用途的探测代理。
   有空闲槽位就派发独立任务；槽位不足等待或分批，不嵌套派生绕过限制。保留实际 child ID。
4. 每位所有者独立阅读任务对应的设计、正式协议及绑定的提交源码，分析控制矩阵、数据隔离、
   业务步骤及清理恢复，完成或修正自己的目录。禁止将起始 inventory 或 CLI 模板复制为分析结果。
   只读范围包括源码、其他场景、`common/`、`configuration/`、发现文件、依赖和版本锁。
   场景目录以外的公共变更只报告需求，主 Agent 在本次交接结束后审查处理。
   保留场景 YAML 的中文用途头及各顶层区块前的说明注释；重写 YAML 后也必须满足已有静态注释门禁。
   每个步骤保留且只保留一次字面量 `record_step` 或 `step_guard` 证据，包括阻塞步骤。
   路径解析和其他函数调用放在测试函数内，禁止导入期 I/O；生成校验不执行场景测试。
5. 使用真实等待、消息或继续任务工具收集结果，核对源码证据、场景及写入者。
   仍在运行不算失败。重试保留 task/attempt 和旧错误；每个任务只接受一次成功。
   同一场景不得有两个活动写入者。已空闲代理可复用，owner 可相同但 run/task 不得混用。
6. 主 Agent 将结果及真实观察写入 state 下的交接 JSON。结果摘要用已安装
   `toolkit.e2e_test_generator.host.scenario_digest(<该场景路径>)` 计算；该函数仅计算工件哈希，
   不执行测试。仅 `generation` 的协调元数据不参与摘要，其他 YAML 文本、注释、格式和场景文件均参与。
   `source_evidence` 采用 `repo#anchor`，必须来自当前场景 `source`。
   `written_paths` 只列该 child 真正修改的自身目录文件；共享工作区的提示词不等于 OS 沙箱。
7. 运行 `devflow e2e check --project <项目> --host-results <state交接JSON> --gate contracts`。
   CLI 拒绝缺失、重复、陈旧、跨 run、错误计数、范围外写入、源仓库变化及无证据的并行声明。
   全部必需任务成功后写入 `generation.owner` 和 `host_task`，更新现有锁的场景指纹，
   并保存权威收集 manifest 与每任务 result。接着执行已有有序领域门禁及静态验证。
   汇总 contracts 检查不创建有序门禁封印，也不授权静态或远程运行。
   原生任务全部成功收集，并在同一有序会话通过 discovery、contracts 和 static 封印，
   且结果、输入及冻结需求文档仍匹配后，才按领域规则推进文档基线及清除 pending_changes。

`mode=native`、`degraded=false` 与 `parallel=false` 可以有效完成；一个槽位或复用代理不需要串行授权。
`parallel=true` 必须有工具记录证明至少两个不同 child 的业务任务同时活动。
观察 `active_task_ids` 使用 `<task_id>:<attempt>`；`observed_at` 标注 `host` 或
`coordinator_observed`，后者不能称为 child 内部开始时间。仅调用与收到结果的时间边界不能证明重叠。
宿主未提供内部调用 ID、生命周期或关闭工具时不编造字段；完成、空闲与已回收须分别报告。

以下是 schema 形状示例，明确为 fixture，真实 CLI 必须拒绝；生产回执来自当前会话的真实调用记录。

```json
{
  "protocol_version": 1,
  "domain": "e2e",
  "run_id": "fixture-run",
  "mode": "native",
  "degraded": false,
  "parallel": false,
  "completed_child_agents": 1,
  "fixture": true,
  "observations": [],
  "receipts": [{
    "run_id": "fixture-run",
    "task_id": "fixture-task",
    "task_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "input_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "write_scope": "scenarios/示例场景",
    "child_agent_id": "fixture-child",
    "attempt": 1,
    "status": "success",
    "result_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "tool_records": ["fixture://not-a-real-host-call"],
    "analysis_summary": "测试样例，不表示真实场景分析完成。",
    "source_evidence": ["fixture-repo#src/example.py"],
    "written_paths": ["scenarios/示例场景/场景定义.yaml"]
  }]
}
```

失败 attempt 使用真实 `failed`、`interrupted` 或 `timeout`，记录 `error`，`result_sha256=null`。
工具实际启动失败且没有创建 child 时使用 `status=spawn_failed,child_agent_id=null`，保留工具错误；
该 attempt 不进入活动代理观察和 child 计数。重试为新的连续 attempt；已启动的任何状态必须保留非空 child ID。
任一必需任务未成功都不收集为完成；旧失败保存在提交及拒绝诊断中，不由主 Agent 代写业务结论。
相同成功交接与工件可幂等重收集，不同结果不可覆盖旧收集。输入变化必须重新 generate，并保留旧运行。
即使输入相同，重新准备也会绑定新的 run/task；旧运行不能覆盖场景当前的任务引用。
多场景始终需要所有权、冻结需求和有序静态门禁，删除 host_task 或改写 mode 不能跳过基线验收。
显式委派过的单场景也由本项目 state 中的冻结任务保持该约束；从未委派的单场景仍沿用普通生成流程。
拒绝收集时，CLI 在拒绝诊断中保留正确绑定的显式失败 attempt；后续提交必须完整保留，并用新 attempt 重试。
其他任务的输出修正不能抹去失败；错误 run/input、空工具引用或无效 child 等记录不会阻止合法恢复。

工具缺失、禁止或启动不可恢复时，只沿用当前范围内明确串行授权。“直接生成”“不用确认”不构成授权。
缺少授权则一次说明实际原因并提供串行或停止选择。取得当前范围明确选择后：

1. 读取 `devflow schema e2e.serial-approval`，把授权文件写到 state 中。必须使用 `decision=serial`，
   `reference` 指向用户明确选择串行的会话记录；`scopes` 精确列出全部现有及即将生成的场景目录。
   `native_status` 只能是 `tool_missing`、`host_forbidden` 或 `spawn_failed_unrecoverable`，
   用 `reason` 和 `diagnostic_reference` 保存实际原因及依据。槽位不足、已启动任务失败不等于工具不可用。
   `prior_run_ids` 列出当前场景引用的全部旧 run，以及需要保留关联的旧诊断运行；无旧运行时为 `[]`。
   文件只是会话选择的结构化交接，不能自行构成用户授权，真实性仍由主 Agent 核对。
2. 执行 `devflow e2e generate --project <项目> --serial-approval <state授权JSON>`，使用原生成输入。
   `init --serial-approval <文件>` 仅与设计/协议生成输入一起使用，沿用同一路径；不能与 `--delegate` 同用。
   CLI 在写入项目及初始化文档状态前预览完整场景范围并核对授权。返回新的 `tasks_prepared` run，
   保留旧 manifest、失败 attempt、子代理标识及诊断。禁止手改旧 run 为串行，或删除 host_task 假装未委派。
3. 主 Agent 按冻结任务真实阅读已提交源码、设计和协议，逐场景完成或修正独占工件，记录未决及阻塞；
   不执行远程测试。每项回执 `child_agent_id=null`，`tool_records` 指向实际主 Agent 分析会话记录，
   绑定任务、输入、结果哈希和源码证据。`mode=serial,degraded=true,parallel=false,completed_child_agents=0`，
   `observations=[]`，`serial_approval` 必须与新 manifest 完全一致。失败保留真实状态、错误及连续 attempt。
   起始模板、空写入清单或未变化的起始工件不能作为串行完成结果；应在场景工件中保留本次分析及其证据。
4. 使用同一 `check --host-results <state交接JSON> --gate contracts` 收集，随后执行完整有序静态验收。
   收集后场景记录 `mode=sequential_degraded,owner=main-agent`、真实 `host_task`、原因及
   `serial_approval={reference,scope}`，scope 精确等于 write_scope。收集不能推进基线；
   所有权、输入、结果、冻结需求与既有有序门禁均通过后才推进。整个新运行零子代理，旧运行历史保持原样。

下例仅演示授权 schema，所有引用均为 fixture，不能当成真实用户选择或宿主诊断：

```json
{
  "decision": "serial",
  "reference": "fixture://session/explicit-user-serial-choice",
  "scopes": ["scenarios/示例场景"],
  "native_status": "host_forbidden",
  "reason": "测试示例中的宿主明确禁止，不是真实诊断。",
  "diagnostic_reference": "fixture://session/host-prohibition",
  "prior_run_ids": []
}
```

串行回执沿用上面的 `e2e.host-results` fixture：改为 `mode=serial,degraded=true`，
`completed_child_agents=0`，`child_agent_id=null`，加入该新 manifest 的完整 `serial_approval`；
保留 `fixture=true`。生产 collect 仍拒绝 fixture，不把示例或自动测试当成真实串行验收。

最终脱敏报告分别说明任务准备、子代理执行、结果收集和领域验收；结果收集不是领域验收通过。
标明 `host-attested` 边界：主 Agent 核对会话真实性，CLI 校验结构、一致性及领域证据。
随机 ID、成功字符串或工具引用不能被宣称为机器防伪。生成始终不授权测试请求、数据库修改、发布消息或部署。
