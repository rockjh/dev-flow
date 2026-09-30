---
name: devflow/doc/biz-flow
description: 发现有源码证据支撑的业务入口，并生成经过确认的业务流程 Markdown。
---

使用已安装的 `devflow` 可执行文件，并且只路由到 `devflow biz-flow`。
项目根目录由显式的 `--project` 指定。生成物和项目锁必须位于
`<project>/docs/biz-flow`（项目锁文件为 `biz-flow.json`）下；不得在该目录之外写入工具包源码、凭据或进程内 JSON。
保留核心 schema、脱敏、锁、所有权和产物路径规则。

## 工作流与归属

本流程覆盖 whole project，并为每个入口保留 read-only entry 角色；关键契约标识包括 `doExecute`、`doServe`、`core_capabilities`、`sequenceDiagram` 和 `autonumber`。

1. 运行 `devflow biz-flow init`，然后运行 `devflow biz-flow discover`。
2. 在确定模块前扫描整个项目仓库。扫描源码、配置、注册信息、平台基类、HTTP/Webhook 路由、从常量/配置/注册信息解析出的消息消费者和主题、事件监听器、文件/导入触发器、CLI 命令、异步 worker、调度器以及 XXL-JOB `doExecute` 处理器。处理跨行 Java 签名和 `doServe` 等平台接收器。忽略 `.idea`、日志、缓存、构建输出、生成物/供应商资源及其他非业务路径；这些内容不得成为入口，也不得影响源码变更判断。
3. 对入口 ID 和 `core_capabilities` 去重。将每个入口分配到一个简短的业务职责模块。不确定的所有权保留为 `待确认`；不得仅凭 URL、主题、控制器、类或目录推断所有权。排除项必须给出原因和真实的 `file:line` 证据：`<!-- devflow:exclude id="..." reason="..." evidence="path:line" -->`。
4. 在生成前向用户展示拟定的模块名称、文件、入口 ID/触发器和排除项。在模块映射中记录用户确认，并要求存在 `<!-- devflow:module-confirmed -->`；仅使用 `--confirm` 不足以完成确认。
5. 确认后，每个 Markdown 文件运行一个模块角色。该角色是文件的唯一写入者，并且必须为每个入口启动一个只读入口角色。入口角色只返回结构化分析，绝不编辑文件。记录入口、函数、参与者、有序调用、所有可达分支、循环、异步工作、持久化、外部调用、成功/失败结果、源码证据和未决问题。增量更新时重新分析受影响的入口和共享调用链。

仅阅读本次操作所需的工作流参考，先阅读
`references/analysis-policy.md`、`references/requirements-matrix.md` 和
`references/verification.md`。如需查看完整的认证示例，还要读取
`example/user-login/README.md` 及其指向的示例项目文件；这些内容仅作说明，必须用目标项目的源码证据替换。

### 新示例的等价性门禁

为新建或修改 example 时，必须把 `example/user-login` 当作可发布形态基线，而不是只比较入口数量：

- 目录必须包含可运行的 `app.py`、说明工作流的 `README.md` 和
  `docs/biz-flow/业务流程覆盖总览.md`；确认并生成成功后，还必须存在至少一个带
  `biz-flow-entry` 标记、`sequenceDiagram`/`autonumber` 和分支矩阵的模块 Markdown，以及
  `docs/biz-flow/biz-flow.yaml` 和 `biz-flow.json`。
- README 中的命令顺序必须覆盖 `init -> discover ->（审阅并确认）-> generate -> check -> verify`，
  并说明失败时不得把未生成的 Markdown 或版本锁当作发布结果。
- 新示例必须逐项对照 user-login 的入口章节结构、每入口一图、数据读写/比较、成功和错误结果、
  持久化失败及覆盖报告；缺一项就修改源码或 Skill 约束后重跑，不能用“业务不同”跳过结构门禁。
- `discover` 必须在 `generate` 前报告 `unresolved=0`。若发现器无法解析某种 Python 写法，优先改为下列
  可静态追踪形式并重新发现：显式路由装饰器、`TABLE[key]`/`if key in TABLE`、显式字段读写、
  `LIST[:] = LIST + [item]`。示例不得使用 `dict.get`、`setdefault`、动态属性、别名容器、动态注册或
  隐式副作用来表达关键业务步骤；这些写法会使入口证据或 Mermaid 分支不可确定。
- 必须在同一示例目录重复执行 `check` 和 `verify`，并把输出与 user-login 对比；任一覆盖、稳定性、
  版本锁或产物路径不一致时，工作流仍视为失败，直到修复或明确记录阻断原因。

## 生成文档契约

以下内容按 fixed order 输出。

每个模块文件都有简短业务标题，并为每个入口提供一个章节。入口章节必须按以下固定顺序：

1. **业务标题**：简短的业务描述，例如 `设备关系同步` 或 `SIM批量导入`，不得使用 URL、主题、类、方法或路径。
2. **入口描述**：简洁触发器，例如 `POST /v0/internal/...`；
   `TOPIC SD-MNO-terminal-device_report` 或 `XXL-JOB 每日用量统计`。此处不得写源码路径、行号或完整类名。
3. **业务功能**：简单流程使用一句话，普通流程使用有源代码依据的
   针对正常、空结果、重复、无效状态、外部失败、异步和异常情况，使用有源码依据的项目符号列出处理方式。不得编造规则。
4. **业务时序图**：使用 Mermaid `sequenceDiagram`，并包含
   `autonumber`，并使用以下默认初始化头：

   ```mermaid
   %%{init: {"sequence": {"actorMargin": 150, "diagramMarginX": 30, "wrap": true}}}%%
   sequenceDiagram
       autonumber
   ```

使用源码中已知的具体参与者（例如 XXL-JOB、RCP 平台、RCP 数据库或 mno-operator），并写出实际操作、条件、查询、响应、写入、事务、消息发布/消费、异步提交、返回值和异常传播。分支使用 `alt`/`else`，迭代使用 `loop`，只有确实可选的路径才能使用 `opt`。不得用“当前系统”“数据库”“调用服务”或“处理数据”替代已知事实。每个已分析分支都必须有对应的图路径；关键行为未解决时阻止生成，非关键未知项则必须连同证据明确记录。

## 门禁与更新

所有面向人的标题、描述、Markdown 和报告正文必须使用中文；机器字段、ID、路径、协议和 Mermaid 关键字保持原样。

生成/更新后运行 `devflow biz-flow check`。它必须验证唯一
所有权、排除项、业务短标题、章节顺序、面向人类的文本中不含源码路径/行号、每个入口一个图、具体参与者/操作、分支覆盖、Mermaid 语法，以及最终 Markdown 中完整的结构化 `devflow` 标记。运行 `devflow biz-flow verify`；它会运行两次持久化检查，并且必须报告 `stable=true`。如果没有 Mermaid 渲染器，必须明确报告结构校验范围。

只有文档和覆盖检查通过后才能更新 `biz-flow.yaml`。将
将锁定版本更新到目标版本，准确添加/删除/移动入口；当源码和已确认的分区未变化时，保留稳定 ID、模块所有权、顺序和内容。

## 示例文档的细节与排版约束

用户登录、注册、授权和会话类流程必须把源代码中的数据动作写完整：

- 数据库读取要写明查询条件、返回字段和空结果分支，例如按邮箱查询账号并读取密码哈希。
- 数据库参与者要写明具体表名和中文名，例如 `accounts`（账号表）、`sessions`（会话表），不得只写“账号库”或“会话库”。
- 凭据校验要写明比较对象，例如输入密码与数据库哈希的比较结果，不能只写“校验登录”。
- 数据库写入要写明冲突检查、写入字段、提交结果和失败返回，不能只写“保存数据”。
- OAuth2 要分别记录授权码交换、回调地址或 state 校验、用户信息读取和提供商错误。
- 会话要记录令牌生成、会话表或存储写入、持久化失败和最终响应。

Mermaid 文本必须避免与参与者标签重叠。参与者使用短别名，动作使用短句，
动作文本不得重复参与者全名；使用紧凑的默认参与者尺寸，不得为解决重叠
而强制放大 `width` 或 `height`。从 `actorMargin: 140`、
`messageMargin: 35` 和 `wrap: true` 起步，再依据渲染结果调整间距。
长条件拆成多个 `alt` 分支，不能把多个查询、比较或写入动作拼成一个过长消息。
生成后必须使用 `check` 验证 Mermaid 结构，并在有 Mermaid 渲染器时检查实际布局。

当同一业务流程存在源代码确认的多个 HTTP、消息或任务入口时，优先按入口拆分
为多个 entry section 和多个时序图。不要把不同入口强行合并成一个顶层 `alt`。
每个 entry section 必须独立维护自己的分支矩阵，分别列出该入口的查询、比较、
写入、成功、失败和异常结果。总览可以统计入口覆盖情况，但不得用跨入口矩阵
替代入口自身的分支矩阵或时序路径。
分支矩阵至少包含“分支条件”“数据读取与比较”“数据写入与副作用”“响应”四列，
不得增加源代码函数依据列，也不得在业务文档中生成单独的源代码证据章节；源代码证据
仅保留在机器可读的扫描结果和入口标记中。
