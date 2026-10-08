# 完整示例：用户登录

本目录是完整的、具有源代码证据的 `biz-flow-doc-generator` 示例。
示例内容不是线上状态，不包含任何凭据。

## 目录说明

- `app.py` 是两个登录入口的源代码证据：密码登录和 OAuth2 登录。
- 本地 `FastAPI` 类用于演示可扫描的路由声明，不启动 HTTP 服务；OAuth2 授权交换及用户资料读取也使用固定演示数据。
- `ACCOUNTS_TABLE` 和 `SESSIONS_TABLE` 是进程内存字典，分别模拟账号与会话数据；它们不是数据库表，重启后数据不会保留。
- `docs/biz-flow/` 包含已确认的总览、业务模块文档和版本锁。
- `docs/biz-flow/biz-flow-doc-generator-version.json` 是核心契约要求的 skill 版本文件。

流程覆盖密码认证和 OAuth2 授权码登录；账号读取、首次登录账号写入、
会话写入、提供商失败、凭据错误、账号禁用和写入冲突均有明确分支。
两个入口同属用户认证业务域，保存在同一模块文件，文件名以自然业务对象和核心职责概括两个已注册登录入口，命名与入口目录采用同源证据；不固定“处理”“业务”“流程”等后缀，也不堆全量功能动词。业务描述根据入口业务注释归纳登录能力，允许标点分段，同类动作合并，独立于文件名。完整入口和详细分支分别保留在入口清单、入口章节和分支矩阵中，不按密码登录与 OAuth2 渠道拆成不同模块。

归档文件为 `00-用户认证登录及账号绑定与会话建立.md`，业务描述为“支持密码登录和 OAuth2 登录；完成账号绑定与会话建立。”。本次归档命名维护只更新文件名、引用和范围概括，保留已验证的两张时序图及版本基线，不改写历史执行 manifest。

## 复现流程

执行发现前先为示例初始化本地 Git 历史，然后在本目录运行已安装的
`devflow` 可执行文件：

```text
git init
git add app.py README.md
git commit -m "docs：添加用户登录示例"
devflow biz-flow init --project .
devflow biz-flow discover --project .
devflow biz-flow check --project . --stage entries
# 查看并确认 docs/biz-flow/业务流程覆盖总览.md。
devflow biz-flow generate --project . --confirm
# 当前环境没有真实子代理时，只有得到用户明确许可才使用串行降级：
# devflow biz-flow generate --project . --allow-degraded
devflow biz-flow check --project .
devflow biz-flow verify --project .
devflow biz-flow verify --project .
```

已有旧版锁时，先执行 `devflow biz-flow init --project . --upgrade` 显式升级，原 Git 基线会保留，旧确认会撤销。第一阶段仅建立入口目录，不要求代理；第二阶段可选择 `review` 进行只读审核，它不是分类确认前的必需步骤。

Markdown 业务模块文档是可读产物。证据始终关联文档列出的源代码位置，
不会用笼统的“数据库”或“外部服务”参与者推断分支。
默认生成会在子代理能力不可用时返回 `DELEGATION_UNAVAILABLE`；成功运行会在
`~/.local/state/devflow/artifacts/biz-flow/` 留下执行清单，记录任务树、批次、并行性和覆盖验收。
