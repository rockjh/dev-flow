# 行为事实与补证

只支持领域 schema 6、宿主交接协议 5.0、Skill 5.1.0。字符串 outcomes、复制事实数组、review.steps 以及不符合当前 schema 的版本锁和回执一律拒绝。保留人工内容及失败诊断，按当前 init/discover/prepare 流程准备有效输入，不转换历史运行。

## 事实、解释与运行

先以浅扫描验证已确认分类，再为选中入口建立可达行为事实。注册身份、分类和源码快照必须一致。entry_facts 包含注册、参与方、sources、calls、branches、persistence_actions、effects、结构化 outcomes、flow、gaps 和 coverage。每次调用有独立 context_id；B/P/O 等事实绑定来源和条件；flow 保留真实位置和入口/后台阶段。无持久化只有在当前可达范围分析完整时才记为 none_in_verified_scope。

Agent 只读取任务指定的提交快照，不能从 dirty 工作区取得本次行为证据。analysis 绑定 facts_hash，只提交带 evidence_refs 的业务摘要和逐事实/参与方 annotations。不复制或修改事实，也不自行编排步骤。入口正常结束、写入尝试、事务边界、提交任务、拒绝和后台结果分别解释；不把存储 API 返回当成事务提交，不把后台结果写成同步响应。catch 不删除 try 内动作；finally 在 try/catch 后表达。未知错误类型传播、控制出口合并或 finally 覆盖尚不能证明时保留缺口。

## 静态适配范围

Java 使用 tree-sitter，解析器版本写入 adapter_dependencies；行为适配器版本为 5.1.0。字段、参数、局部变量、唯一接口实现、继承方法、基本重载和链式返回按全限定类型绑定，精确重载优先于可证明的基本数值拓宽/Object；不能按类型短名跨包绑定。构造实参先于构造体执行，构造器歧义、未建模初始化器和构造链保留缺口。同步回调仅在形参实际调用处展开，保存回调不执行；集合 forEach 方法引用按参数数量绑定。已知 Executor 类型将提交、拒绝和后台分别记录；直线后续动作与正常返回受 accepted 条件约束，图中保留该条件。条件/循环提交的继续路径合并、拒绝的 catch 映射尚不能证明时阻断。动态派发、反射、复杂泛型、未知外部库、递归和预算耗尽不能宣称完整。

JPA 支持直接或源码可追踪的泛型仓储、绑定到 JPA 的显式 Table/Column，以及源码实现的适配层；自定义同名注解不能证明映射。当前固定 API 版本为 spring-data-jpa 3.3.0、querydsl-jpa 5.0.0。从 API 所属源码模块的最近 Maven POM 解析直接依赖、本地父 POM、属性及 dependencyManagement；无关模块不参与版本证明。外部 BOM、激活 profile、其他版本、自定义物理命名、未解析 schema 和动态查询保留缺口。QueryDSL 支持可绑定 EntityPathBase 的 update/delete、set/where/execute；条件字段必须绑定实体和生成路径，保留 where、赋值和行数关联。默认命名仅接受下述补证。事务注解只构成声明证据；代理/容器激活、传播及回滚尚不能证明时产生 TRANSACTION_ACTIVATION_UNRESOLVED，不能宣称已提交。普通 execute/save/send、注释 SQL、内存 Map 和 Path 构造不因名称变成存储动作。

Python 支持同文件顶层/类方法、简单接收者、if/循环、and/or 短路、条件表达式、字面量或通配符 match、内建异常的 catch 转换和结构化返回，按求值顺序检查参数。局部函数/Lambda 声明不执行函数体；不能绑定的调用、协程/await、生成器、推导式、match 守卫或结构模式、动态展开、未证明装饰器、自定义异常匹配、try-else、覆盖结果的 finally 和上下文管理器保留缺口。仅在导入类型与字面对象可证明时识别 sqlite3/SQLAlchemy SQL、Redis、文件 open 和 mypy_boto3_s3.S3Client 的 Bucket/Key。SQLAlchemy 要求 DeclarativeBase 模型的显式 __tablename__，query 构造不记 IO，支持直接 query(Model).all/first/one/count。

TypeScript/JavaScript 与 Go 使用静态 tree-sitter 适配器，支持唯一同文件委托、有界语法的 if/循环/switch、短路、返回及抛出；JavaScript catch 记录转换结果。Prisma 只接受已导入且唯一绑定 PrismaClient 的调用和显式 @@map 表名；Go GORM 要求导入的 DB 类型、已绑定实体及字面 TableName 方法。无法证明的派发、fallthrough、异步/defer、复杂控制或外部契约保留缺口。不会把 model 名猜成物理表名。

外部 HTTP 仅识别可绑定的 requests/httpx、全局 fetch、Go net/http 字面 URL，或具有导入、字面客户端名及映射的 Java Feign。目标名和调用位置来自源码；只证明调用尝试，不证明远端送达或业务成功。动态目标、遮蔽绑定和未知客户端契约保留缺口。

SQL 字面量只支持明确单语句对象，不支持 CTE、子查询、逗号连接和引号对象名；字符串值中的 SQL 词不构成表名。Java 对绑定 JdbcTemplate/Statement、Jedis/StringRedisTemplate 采用同一字面规则。不能解析时报告 PERSISTENCE_OBJECT_UNRESOLVED。

## 有证据的误判说明

analysis 可增量提交 resolutions；无需回抄机器事实。每项 finding 使用 CODE|fact_id，evidence 使用本次冻结的完整来源对象，path 是下节所述可达路径，controls 必须精确为 [entry_id, ...目标 conditions] 且非空，unknowns=[]，explanation 写明确说明。仅接受适配器已证明的三类：OUTCOME_UNRESOLVED + normal_completion（入口 void 正常结束）；PERSISTENCE_OBJECT_UNRESOLVED + non_persistence（纯内存/路径构造或已证明任务提交）；BRANCH_LINE_UNRESOLVED + non_business_decision（短路连接符或三元表达式）。说明随结果保存到 manifest，并在文档中标出正常完成、误判或非业务决策行。此通道不删除真实分支，不免除未知 IO；真实缺口仍需下面的可验证补证，不能用空 unknowns 伪造解决。

仅有 Executor/TaskExecutor 接口不能证明延后执行，它们允许同步调用任务；未绑定实现时产生 EXECUTOR_SCHEDULING_UNRESOLVED。任务阶段在清单后段展示是阶段分隔，不证明任务启动晚于入口返回；实际并发交错仍不在静态证明范围。

## 补证与重新冻结

有缺口时提交 kind=evidence_request，读取 biz-flow.evidence-request schema。请求绑定当前 run/task/entry/source/facts_hash、finding/target、源码证明、调用 path、controls 和 binding。

按冻结事实构造 path：末项为 target_id；从目标的 context_id 沿 calls 的 details.parent_context 向入口回溯，将每次调用的 fact_id 依次前置。目标本身是调用时不重复加入。controls 必须精确等于目标的 conditions（包括顺序）；sources 使用冻结的完整来源证明对象，并包含目标的全部 evidence_refs 及下述额外证明。不能用任意合法 ID、行号或自行拼出的声明替代这条调用上下文链。

binding 的 classification 只接受下表字面值，其余字段由相应源码声明证明。parameter_types 使用全限定类型并保持签名顺序，空数组只用于表中明确列出的类型。

| 请求 type | classification | binding 与额外证明 |
| --- | --- | --- |
| branch_classification | constant_true / constant_false | declaration_id 等于目标首个来源的声明；parameter_types=[]。目标必须是对应常量 if，不能把任意条件判为常量。 |
| call_binding / callback_binding | spring_primary | declaration_id 为候选方法完整身份；receiver_type 为该实现的全限定类型；parameter_types 为声明签名。sources 还须包含候选方法和实现类型声明。 |
| behavior_classification | java_se17_path_construction | declaration_id 为 java.nio.file.Path.of(java.lang.String,java.lang.String[]) 或 java.nio.file.Paths.get(java.lang.String,java.lang.String[])；receiver_type 为对应 JDK 类型；parameter_types=["java.lang.String","java.lang.String[]"]。 |
| resource_mapping | jpa_standard_default_table / jpa_standard_default_columns | declaration_id 和 receiver_type 均为已绑定实体的全限定名；parameter_types=[]。sources 还须包含实体及 declaration_id=jpa-naming-configuration 的配置证明。已有显式 JPA Table 使用后者。 |
| outcome_fact | caught_error | declaration_id 等于抛出目标首个来源的声明；receiver_type 为已证明的 java.lang 异常类型；parameter_types=[]。sources 还须包含对应 catch 控制证明。 |

没有额外约束的字段仍必须满足 schema；语法合法不表示语义通过。若冻结候选证据不足以取得准确声明、签名或来源证明，保留具体缺口，不猜测 binding。

当前可验证的补证范围：

- branch_classification：if 的 AST 常量 true/false。
- call_binding / callback_binding：多实现调用或方法引用中，由已导入的 Spring Primary 与 Service/Component 声明证明的唯一实现。引用调用、候选方法和类型声明，准确匹配接收者与全限定签名。
- behavior_classification：JDK 17 API 配置中的 Path.of/Paths.get 字符串重载只构造路径，不执行文件持久化。
- resource_mapping：直接或源码泛型继承的 JPA 实体，由唯一 properties 配置同时明确 Standard physical strategy 与 JpaCompliant implicit strategy，且没有 schema/其他配置冲突，以 jpa_standard_default_table 重建默认表名及字段；已有显式 JPA Table 时，以 jpa_standard_default_columns 补齐默认列。不能提交任意表名或列名替换。
- outcome_fact：源码显式抛出的 JDK IllegalArgumentException/IllegalStateException/RuntimeException，由唯一、最近的可证明兼容 catch 捕获；必须引用抛出和 catch 控制证明，不把内部错误写成对外失败。

同一类型的其他语义仍拒绝，保留原缺口；不允许用合法行号、代理身份、空 unknowns 或文字“已解决”放行。签名/路径/控制不匹配、未证明的配置、异常类型遮蔽和无进展请求均拒绝。

CLI 从相同提交重新验证并重建，事实变化才创建 B；A 标记 superseded，B 记录 supersedes_run_id，原包不改。源与分类未变时不再请求分类或执行方式授权，但必须真实重新执行 B 的全部任务。旧结果与回执不能完成 B。重复目标或无变化停止重开。check、每次 verify 和 accept 都核验绑定提交的基础事实、已保存补证、最终事实、结果和文档摘要。同 target/fingerprint/adapter 的基础事实可复用带校验摘要的缓存；有补证时仍逐批验证并重放适配器。不能把旧清单和代理事实取并集。

关键未决只定位受影响入口；collect 对运行范围实行全覆盖和一次写入，范围内任一入口失败不生成该运行的最终文档，也不推进基线。可用 module 范围准备独立运行；局部验收不能推进整个项目的基线。新任务包重新分析所选范围全部入口；同一包可用 prepare --resume 复用校验通过的结果及其原始回执，仅重派 pending 入口，最终 collect 必须提交完整范围。任务包绑定 version_input_hash，分析期间修改版本锁会拒绝；accept 写入合法基线后保存 accepted_version_hash，后续 check/verify 仍独立核验。报告阶段一疑点、阶段二 gaps、待验证请求、最终验证结果及实际渲染范围。

渲染空控制分支时保留条件并注明该条件内无业务动作。安装 Mermaid CLI 时除检查退出码，还解析输出 SVG 并拒绝无效 XML 或非有限几何坐标；退出码 0 不能单独证明图可用。没有 Mermaid CLI 时只能报告确定性语法子集与事实对账，不能宣称已完成浏览器渲染验证。
