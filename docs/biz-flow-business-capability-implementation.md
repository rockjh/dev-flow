# biz-flow 业务能力改造实施记录

状态：方案尚未全部完成。基础修复、验收门禁和下述仓内 Java 语义已实施；框架能力扩展及目标项目验收仍未完成。当前工具版本 9.2.1，biz-flow Skill/adapter 5.2.1，领域 schema 6，宿主协议 5.0。本文补充 [通用 v1 实施记录](biz-flow-generic-v1-implementation.md)，不将历史验证结果作为当前代码或业务项目验收证据。

## 逐项核实结果

以下按业务改造方案章节核实实现和验证，不以测试总数、零 gap 或 prepare 状态判定全部完成。

| 方案范围 | 当前结论与证据 | 未完成工作及下一动作 |
| --- | --- | --- |
| 3.1 注册与归属 | 已有静态注册适配、触发链去重、人工归属保留和独立入口目录门禁；`discovery.py`、`documents.py` 及 discovery 回归。全范围另检查 registration coverage_gaps。 | 目标项目未指定；无法确认其候选集合、排除、动态注册、模块归属及实际覆盖。先固定 target 后 discover/check entries。 |
| 3.2 生命周期与继承 | 仓内继承调用、super、private/static 及继承方法引用分别保留实际接收者和声明。`java_behavior.py`、`test_behavior_integrity.py`。 | 库外平台委托/模板全生命周期、请求响应重载和 ThreadLocal 读写清理尚未扩展；按实际可达框架版本补充契约，不能用仓内继承回归代替。 |
| 3.2 依赖证明 | 最近所属模块 POM、仓内父 POM、属性及 dependencyManagement 有有限支持；未解析父 POM 与 profiles 阻断。 | 未实现固定 BOM 成员摘要及固定 SNAPSHOT 构建绑定；既有固定 API 摘要也不能代表任意发行版本。取得目标依赖声明和对应发行源码/字节码，再扩展固定摘要及证明。 |
| 3.3 构造 | 普通仓内类支持接收者求值、实参、this/super 委托、父构造、实例字段及初始化块、构造体顺序；this 委托不重复初始化。完整夹具经 collect/check/verify×2/accept。 | 静态初始化时机、库外父构造、生成构造及 record/enum 生命周期继续保留 gap。 |
| 3.3 生成与计算 | 既有基础 JDK/集合 forEach、直接 lambda/方法引用按现有边界工作。 | Lombok 生成配置、MapStruct 策略/钩子、Optional/Stream 惰性和短路、完整签名/返回类型 API 摘要未补齐；须按实际项目中出现的行为实施，不能整体视为纯计算。 |
| 3.4 真实 IO | 既有字面量 SQL/KV、显式 JPA 物理映射和有限 QueryDSL update/delete 证明；写入尝试不声称提交。 | QueryDSL 读取及复杂链/连接/投影、事务代理激活/传播/回滚/提交、动态外部目标未完成；冻结实际事实后逐入口补齐。 |
| 3.5 控制与失败 | 已证明无正常返回的仓内调用/构造/同步回调终止直线继续路径；抛出后的实参、赋值和正常响应停止，catch/finally 保留。 | 条件早退合流、循环出口、短路异常、finally 覆盖和一般异常类型传播仍有限制；unsupported gap 阻断，逐项实现所需控制语义。 |
| 3.5 后台 | 提交/接受/拒绝和候选后台阶段分开；接口/线程池类型不证明调度。 | 实际执行器实现、拒绝策略、匿名任务、调度及重试契约未补齐，不能宣布后台处理已完整。 |
| 3.6 补证与诊断 | 已有 typed evidence_request、重建新包和逐入口 behavior_report；既有精确补证仅适用于明确支持的语义。 | 新语义须实现适配器验证，不能靠 resolutions 清除未知；目标项目的逐入口缺口统计和恢复记录尚未产生。 |
| 4 快照与安全 | Windows 长子路径、本地/UNC 路径转换、目录别名拒绝、标准库安全删除和失败恢复已回归。固定 target、唯一写入者及核心所有权门禁保留。 | 当前 Windows 环境未执行 POSIX 路径分支或真实 UNC 服务器 IO；相应平台验收仍须在适用环境完成。 |
| 5 业务验收 | 工具支持模块独立验收和全范围单独验收；模块 accepted 集合不能替代全范围运行或推进项目基线。 | 尚无目标仓库、固定提交、设计资料及实际依赖证明；未进行真实原生业务分析、模块验收或全范围 accept。 |
| 6 版本与 Skill | 规范 Skill、默认提示词、参考、示例锁、Python/npm 与 adapter 同步；旧缓存失效，旧运行拒绝，schema/宿主结构未变。 | 项目旧锁归档/init/人工内容恢复须在具体目标仓执行；工具安装测试不改写任何业务项目锁。 |
| 7 开发与安装 | 下方分别记录上一阶段基础检查和本次补验，发布复制规范 Skill。 | 通用夹具和隔离安装不替代业务场景验收；最终完成仍依赖上述实际业务范围与所有门禁。 |

## 本次新增修复

新增回归先复现了接收者构造漏展开、未知父构造静默放行及仓内构造链未建模的问题。运行时复用原 facts/flow、类型绑定及核心 schema，补齐普通类构造生命周期和继承派发；不增加框架适配、项目配置或动态插件。

新增直线失败回归覆盖普通调用、局部变量、字段赋值、构造实参、返回表达式、条件、循环条件及同步回调。已证明抛出时不生成后续动作和正常响应；复杂短路/循环合流继续阻断。未解析的父 POM 不能证明完整依赖 profile。实现及回归位于 `java_behavior.py`、`test_behavior_integrity.py` 和 `test_generic_acceptance.py`。

switch 所有分支均返回的既有场景保持支持；只有提前退出与正常继续并存、合流尚未证明时保留 critical gap。已识别的 Lombok 生成构造不能被替换为隐式默认构造；该拒绝门禁不代表完整 Lombok 语义已实现。

验收汇总补充 source_fingerprint 匹配：同一提交及模块映射下，忽略规则改变证据范围后，旧 accepted 记录不能证明当前范围完成。真实旧范围先通过夹具验收，再改变仓库 info/exclude，回归确认汇总返回 partial。

## 已实施范围

| 方案要求 | 实现及验证位置 |
| --- | --- |
| 异步拒绝 facts 合法 | `java_behavior.py` 只将 branch_id/handlers 投影到 possible_handlers；嵌套 catch 的 facts 及 prepare 均接受结构验证，异常传播未证明时仍保留 critical gap。 |
| 执行器保证 | 已支持执行器的声明类型不能证明实际调度及拒绝策略；缺少实现和配置证明时保留 EXECUTOR_SCHEDULING_UNRESOLVED，候选后台阶段不作为已验收行为。 |
| Windows 长子路径 | `paths.py` 为快照文件 IO 和标准库 rmtree 的根统一添加扩展长度前缀，分别处理本地、UNC 和已有前缀；Git 进程参数使用普通路径。实际回归从短根下超长子路径完成 archive、扫描、冻结、哈希、collect、verify×2、accept、clean。 |
| 目录别名和恢复 | 哈希或复用快照前检查内部 symlink/junction；目标内容不被读取。清理继续调用 shutil.rmtree，原失败回归仍拦截真实删除入口；部分删除从固定提交恢复，失败不推进基线。 |
| 注册覆盖与全范围验收 | 注册 coverage_gaps 独立阻断全范围 check/verify/accept；入口数量对账不能代替覆盖完整。模块范围可验收，其 accepted 集合不能替代有效的全范围运行。 |
| 逐入口诊断 | prepare/resume 返回 behavior_report 权威路径和模块摘要；外部诊断报告保留包绑定、入口状态、完整 gaps、接收者/声明绑定、来源、依赖配置和恢复动作。零 gap 仍须实际源码分析。 |
| 实际渲染 | 缺少 Mermaid 时保留 executed=false/passed=false 并阻断文档验收；恢复后连续两次 verify。保持默认超时预算。 |
| 版本与发布 | 工具/Python/npm 版本同步，规范 Skill、提示词、六份参考及示例锁同步；adapter 升版使事实和注册缓存失效。事实字段和交接结构未变，保留 schema 6/协议 5.0，旧运行不转换。npm 副本由 release.py 生成。 |

## 尚需目标项目输入的工作

目标业务仓库、固定提交及设计资料尚未指定。平台委托完整生命周期、所属模块依赖版本与发行源码/字节码证明、Lombok/MapStruct、实际使用的集合回调、QueryDSL 查询、事务代理激活、控制合流及后台调度等扩展，需要先读取该项目冻结 facts，再逐入口选择实际出现的语义实施；当前保留既有支持边界及 critical gaps。

目标项目验收需使用本轮已安装版本，先 discover/check entries，再按真实模块完成 prepare → 原生源码分析 → collect → check → verify×2 → accept，最后另建全范围运行。必须返回实际模块三列表、排除/疑点/注册覆盖、逐模块和入口验收数、实际渲染、稳定性、target/dirty/fingerprint、退出状态及脱敏工件指针。自动化夹具和安装 smoke checks 不替代这些业务证据。

## 基础修复阶段验证（9.2.0 / adapter 5.2.0）

验证命令使用实际 Python 安装及其 Scripts 目录；WindowsApps 的 python 别名在本环境不能运行测试。相关回归通过后先由 release.py 生成 npm 树，再运行完整 pytest 校验规范与生成载荷，并对该 wheel 验证隔离 npm → pipx → Skill → doctor，覆盖 postinstall 与禁用脚本后显式 install；最终执行 compileall 和 diff 检查。

| 上一阶段检查（Windows / Python 3.12.10） | 结果 |
| --- | --- |
| 相关行为、路径及门禁回归 | 20 passed、1 skipped（POSIX 路径用例）；补验嵌套 catch prepare 及内部目录别名删除为 3 passed。 |
| Skill / 发布契约 | 11 passed；规范 Skill quick_validate 通过。 |
| release.py | 通过；唯一 devflow 控制台入口，每个注册 Skill 一个载荷目录。 |
| 隔离 npm → pipx → Skill → doctor | 正常 postinstall 与禁用脚本后的 `npx --no-install dev-flow install` 均通过，共 63.01 秒；版本 9.2.0、四个 Skill 逐字节一致、六语言解析器正常，npm 包装器优先处于 PATH 时无递归。隔离目录已清理。 |
| 全仓库 pytest | 938 passed、1 skipped（POSIX 路径用例）、51 subtests passed，656.08 秒。 |
| compileall / diff --check | 均通过。 |

安装检查不改写其他项目锁和历史运行，不构成目标业务验收。

## 本次补验（9.2.1 / adapter 5.2.1）

| 本次检查（Windows / Python 3.12.10） | 结果 |
| --- | --- |
| 行为、构造、继承、发现、补证及完整生命周期夹具 | 104 passed，73.92 秒；含新增的构造/捕获失败 collect/check/verify×2/accept 及实际 Mermaid 渲染。另补验源码指纹汇总门禁 1 passed，9.45 秒。 |
| 最终控制/交接/渲染/安全与 Skill、发布契约补验 | 155 passed、1 skipped（POSIX 路径用例），210.88 秒；包含 switch 既有支持和新增混合出口阻断。与上一行部分用例重叠，不相加作为唯一用例数。 |
| Skill quick_validate / 参考文件检查 | 均通过，所有必读引用存在于规范目录。 |
| release.py | 通过；唯一 devflow 控制台入口，四个注册 Skill 各一个规范载荷目录。 |
| 隔离 npm → pipx → Skill → doctor | 最终 wheel 的正常 postinstall 与禁用脚本后显式 install 均通过，共 61.03 秒；版本 9.2.1、四个 Skill 逐字节一致、六语言解析器正常、绝对 pipx 入口无 PATH 递归；隔离目录已清理。 |
| 全仓库 pytest | 965 passed、1 skipped（POSIX 路径用例）、51 subtests passed，691.11 秒，退出码 0。 |
| compileall / diff --check | 通过。 |

最终 wheel SHA256：`adb22f8c142610c1e035dbbf9aea658892f467dcd018dedf083ef9e0b0b10598`。本次未发布、未提交 Git，也未进行目标业务项目验收。
