# sequence-diagram-generator 实施与验证记录

规则来源为根目录 AGENTS.md。设计 1.0；工具 8.2.0；领域 schema 1；Skill 1.0.0。本文记录实际结果；验收范围按用户最终要求限定为本地时序图工作流。

## 已实现

静态 CLI 路由、不可变模型和核心 schema、来源与需求快照、五语言适配器（JS/TS 分别解析）、宿主任务协议、需求映射、结构化序列树、Markdown/Mermaid/矩阵、独立重建和所有权保护的事务提交已实现。唯一入口仍为 devflow = toolkit.cli:console_main。

规范 Skill 位于 skills/sequence-diagram-generator/，含六份相对引用资料和 revision-zero 示例，不含伪造执行或线上记录。项目基线只使用 docs/sequence-diagram/sequence-diagram-generator-version.json。

SourceOrder 单独冻结每个出口的步骤顺序及标签。门禁拒绝步骤倒置、分支标签改写、嵌套全部终止后的动作，以及引用无关目标证据的标签/需求映射。事务测试涵盖竞争基线、人工编辑、journal 各阶段中断和 replace 已完成但 journal 尚未更新的恢复。

Java 绑定明确的 ExecutorService.submit、typed Future 和同路径 get；等待依赖实际派发步骤，任意 get 不代表等待。JS/TS 分析直接导入并构造的 EventEmitter 同步 on/once/emit 顺序，且同名 app.js/app.ts helper 保持文件内绑定。Python sqlite3 区分语句发起、驱动返回和 commit/rollback，并记录 P-ID；词法遮蔽、条件分支和零次循环不能产生假接收方证明。Rust use 别名只绑定真实导入名；直接本地函数 spawn/join 表达并行派发和同句柄完成观察，Go 直接单 channel producer/receive 表达发送值和观察接收，其他调度继续报告缺口。

## 安装与真实运行

固定 tree-sitter 0.25.2、Java 0.23.5、JavaScript 0.25.0、TypeScript 0.23.2、Go 0.25.0、Rust 0.24.2。扫描不安装依赖，不执行目标源码、构建、生成器或宏。

scripts/verify_sequence_dependencies.py 已验证 Python 3.11 对应 Windows amd64、Linux manylinux2014 x86_64、macOS x86_64 二进制 wheel 可用性，runtime_executed=false。实际运行平台为 Windows/Python 3.12.10；未把下载写成三平台运行通过。

已重新生成发布树，核对四个注册 Skill 各自规范/npm 文件哈希一致，wheel 只含 toolkit 和唯一 devflow 入口。禁用 postinstall 后，在隔离 npm 目录执行实际 npx --offline dev-flow install，隔离 PIPX_HOME、PIPX_BIN_DIR、DEVFLOW_SKILL_HOME；doctor 对六种语法实际解析通过。一次临时代理安装失败后，不使用代理的重试成功，未修改全局网络设置或用户已安装 Skill。

Python 绑定修复后的最终安装版运行 ee48898b5b514fcca447985ef3d2fd1a 已 collect → verify → accept，revision=1、reproducible=true、实际 Mermaid render_status=passed，verified_digest=85cb696a6a8296a819cff5cc778e15fb302e05687104324db3857f1a057a097c。一个真实子代理会话顺序核对六个独立任务，未声称六代理并发；CLI 记录真实性为 host_attested。权威记录在核心状态根 sequence-diagram/runs/<run_id>/。

该代码夹具运行包含六个选定作用域、22 个步骤、6 个控制点及 12 个出口，critical gaps=0；没有需求资料，因此不能推断真实项目需求覆盖。

最新安装版的六语言运行 79572000831241e4bd0cdbf0cf5d8b94 已 collect → verify → accept，revision=1、reproducible=true、实际渲染 passed，58 个步骤、6 个双出口控制点、critical gaps=0，verified_digest=57448d21d749d5008e7cd267b9a88722b2d812866472084e22f02e97a500dc01。JS/TS 两个 helper 绑定各自文件，Rust 两次调用恢复各自调用实例。最新仅需求运行 0dc6012e4bbe4f19add4d418ae6c2906 同样已 accept，2/2 来源区段、3 个拟议步骤和通知失败 opt，implementation_consistency=not_evaluated，verified_digest=ee44c41261a77944f2271ef950929ba2c12f7a802e81ad0bacf658bccda8b30f。

首次仅需求运行 076d8f9bda004b26be74018c2045cb37 曾揭示映射器只接受代码目标的缺陷，按门禁 failed 并保留诊断。修复后使用新运行和真实新任务，不修改旧模型或复用回执。拟议目标绑定需求区段证据，代码目标绑定自身代码证据；需求证据不能冒充 implemented，partial/conflict 仍要求代码事实。

## Online document boundary

This Skill handles local sequence diagrams, requirement mapping, coverage reports, rendering and local accept only. Feishu online document or whiteboard conversion is outside this Skill and must be routed through the user-level prompt and installed Feishu CLI Skill. Local whiteboard CLI use is only a local layout regression and creates no online publication claim.

## 验证边界

- Linux/macOS 实际运行及 pipx 验收尚未执行；Windows 已用临时独立 OS 用户实际安装，状态位于该用户真实 home，doctor 六语法解析通过。
- 复杂异常前缀、动态派发和未绑定并发仍报告固定 critical gaps；ControlNode 邻接字段是证据 CFG，不承诺任意程序的完整并发交错。
- 显式 reference bundle 已支持绑定原生 shape/text 节点、样式推导、尺寸重排和冲突阻断；实际 whiteboard-cli 0.2.13 双次本地导出、PNG 渲染和目视检查通过。这些结果仅属于本地布局验证，不构成线上验收。
- 用户已将飞书转换交由用户级提示词及已有飞书 CLI Skill。原方案 T9 线上验收不再是本 Skill 的完成门槛；运行时仍保留已实现的发布协议，但规范 Skill 不路由或声明线上发布能力。

最终完整回归为 **616 passed, 38 subtests passed**（并针对 Rust/Go 完成关系和原生布局追加回归）。compileall、git diff --check 和 Skill quick_validate 均通过；发布树已刷新并复核四个注册 Skill 的文件哈希和 wheel 单入口。最终安装恢复和六语法 doctor 实际解析通过，临时独立 OS 用户实际完成 npm→pipx→Skill→doctor 及六作用域静态分析；线上发布仍未宣称完成。

Skill 保持实际能力声明，仅报告本地验收结果及上述平台、静态分析边界。
