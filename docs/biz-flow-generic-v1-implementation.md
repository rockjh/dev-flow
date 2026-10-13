# biz-flow 通用化 v1 实现与验证

运行时使用静态适配器，项目不需要业务词典或目录白名单。当前发行版本为 9.1.0，biz-flow Skill 为 5.1.0、领域 schema 为 6、宿主协议为 5.0。变更保留在工作区，未提交或发布。

## 实现对应关系

| 需求 | 实现和可核验位置 |
| --- | --- |
| G-01 生命周期与重试 | `src/test/biz_flow_doc_generator/test_generic_acceptance.py` 覆盖 prepare → collect → check → verify×2 → accept，失败 collect、resume、损坏文档和修复重试。 |
| G-02 固定快照 | `git.py` 始终 git archive；manifest 保存 target，accept 写入该 target。指纹归一化行尾及路径分隔符，工作区与新 HEAD 不成为证据。 |
| G-03 扫描范围 | `discovery.py` 剪枝工具/构建目录，应用提交中的 gitignore、仓库 info/exclude，以及提交配置 `.devflow-biz-flow.json` 的唯一 exclude 字段。 |
| G-04 用户所有权 | `documents.py` 在总览机器区块持久保存归属、文件名、描述和确认摘要；重跑不重新命名，改名后移动原有拥有的模块文件。 |
| G-05 门禁真实性 | `cli.py` 分别报告 input_contract、entry_reconciliation、business_copy、markdown_structure、mermaid_render；未执行必有警示。公共 CLI 的失败信封也保留 gates。 |
| G-06 增量结果 | `core/schema.py` 与 `validation.py` 将机器 entry_facts 和 analysis 分离；代理提交 review、annotations、resolutions，不回抄事实数组。正常 void 完成由适配器生成，再由代理解释。 |
| G-07 有证据的说明 | resolution 绑定 CODE\|fact_id、冻结来源对象、可达 path、精确非空 controls、空 unknowns；三类说明持久保存并显示在文档中。伪造来源、无关路径或未知 IO 均拒绝。 |
| G-08 产品契约 | 规范 Skill、默认提示词和 references 说明当前命令/schema/适配边界；`scripts/release.py` 生成 npm 副本，发布契约测试逐字节核对。 |
| G-09 注册适配器 | `test_generic_adapters.py` 覆盖 Spring MVC/JAX-RS、FastAPI、Express/Nest、Kafka/RocketMQ/RabbitMQ、定时、CLI、事件和文件注册；既有平台注册测试覆盖模板方法去重。动态注册单列 coverage_gaps。 |
| G-10 行为适配器 | Java/Python/TS/JS/Go 提供有界源码分析、条件连接符、循环、结果及可证明的异常转换；一跳可绑定委托展开，未知语义按入口阻断。 |
| G-11 持久化 | `storage.py`、各语言适配器仅接受静态对象：SQL、Redis/KV、文件、S3、显式 JPA/SQLAlchemy/Prisma/GORM 映射；不猜物理表名。 |
| G-12 渲染校验 | Markdown/覆盖、业务文案和实际 Mermaid 渲染分离；60 秒默认超时，成功 SVG 校验并按图及渲染器缓存，失败可重试。90 图缓存测试覆盖跨内存缓存复用。 |
| G-13 部分交付 | prepare --module、prepare --resume、check/verify/accept --run-id；汇总同 target/mapping 下已验收且文档哈希仍匹配的模块。局部验收不推进整个项目基线。 |
| G-14 性能 | 扫描及行为事实缓存绑定 target/指纹/适配器；扫描与逐入口证据进度写 stderr。夹具预算为单阶段扫描 300 秒、整轮 1800 秒。 |
| G-15 输出与诊断 | 公共 CLI 使用核心 UTF-8、脱敏、退出码和信封；缺失 manifest、模块不存在或快照不匹配给出错误码、位置和恢复动作。 |
| G-16 状态卫生 | 接受后删除解出的源码，保留审计 manifest；clean 枚举、按 run-id 清理，--all 包括重建缓存。删除路径校验及保留无关文件有回归测试。 |
| G-17 宿主协作 | Skill 中三条协调约束；回执绑定 child_agent_id、batch_id、task/attempt/status。三栈生命周期使用原生顺序、并行观察及授权串行夹具，不探测品牌 CLI。 |

## 验证记录

- 三栈为 Java/Spring+JPA、Python/FastAPI+SQLAlchemy、TypeScript/Nest+Prisma；另有 Go 行为与 GORM 夹具。
- 三类 resolution、32 个 agent worktree、dirty/新 HEAD、gitignore/info-exclude、改名持久化、局部验收、文档破坏、渲染缓存和十份文档确定性均有自动化覆盖。
- 1500 文件、10 模块、两轮完整生命周期的独立测量为 **54.125 秒**，两轮模块文档逐字节一致，预算为 1800 秒。此为合成夹具测量，不是任意真实仓库的耗时保证。
- 全仓库 pytest、compileall、diff 检查和最终隔离安装结果见下表。
- `.github/workflows/test.yml` 安装实际 Mermaid CLI、构建载荷并执行全仓库测试，包含上述生命周期夹具；工作流尚未在远端运行。

## 明确边界

annotations 是本版业务标签协议；不接受任意 steps/outcomes 机器数组。空结果的正常完成语义由适配器证明，缺失事实只能走已实现的类型化补证及重新冻结，不能让代理猜结果。

resolutions 解释已由源码证明的 void 完成、纯内存/任务提交误判和条件连接符。它不豁免真实 critical gap；动态资源、未知外部契约、无法证明的异常匹配或执行器调度继续阻断相应入口。

Java JPA/QueryDSL API 有明确版本和配置证明要求；SQL 不支持 CTE、子查询、多语句或引号对象名；Java switch 规则式语法、复杂控制和未证明异步语义保留缺口。完整静态能力以 Skill 的 behavior-evidence.md 和运行 gaps 为准，不宣称编译器级调用图或所有框架变体均受支持。

夹具中的宿主回执有专用测试放行路径，生产验证拒绝 fixture 身份；测试通过不代表当前会话启动过分析子代理，也不替代目标业务仓库的实际验收。

## 最终检查（2026-10-13，Windows / Python 3.12.10）

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q` | **901 passed，51 subtests passed，844.49 秒**。 |
| 三栈并行及更新后的 Python 定时夹具补验 | **5 passed，78.08 秒**；覆盖新增并行参数及 Python 顺序/串行路径。 |
| 最终预检门禁与清理命令补验 | **2 passed**；包括公共 CLI 失败信封和缺失 manifest 的恢复提示。 |
| `python -m compileall -q src/toolkit src/test` | 通过。 |
| `git diff --check` | 通过。 |
| `python scripts/release.py` | 通过；单一 devflow 控制台入口，每个注册领域一个规范 Skill，规范与 npm 树逐字节一致。 |
| 隔离 npm → pipx → Skill → doctor | postinstall 与禁用脚本后显式 install 两种方式均通过，版本均为 9.1.0；隔离目录已清理，未改全局安装。 |

全仓库测试启动后增加的并行参数及最后的诊断修订由上述补验覆盖。最终安装 wheel 的 SHA-256 为 `92a3e4d505e35f7d8f8cb0a4b10c1f42e6f11c6375598bacd050959c5a5225a8`；构建产物保持为忽略文件，不纳入提交。
