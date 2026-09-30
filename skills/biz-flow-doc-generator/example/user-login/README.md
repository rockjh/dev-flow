# 完整示例：用户登录

本目录是完整的、具有源代码证据的 `devflow/biz-flow-doc-generator` 示例。
示例内容不是线上状态，不包含任何凭据。

## 目录说明

- `app.py` 是两个登录入口的源代码证据：密码登录和 OAuth2 登录。
- `docs/biz-flow/` 包含已确认的总览、业务模块文档和版本锁。
- `docs/biz-flow/biz-flow-doc-generator-version.json` 是核心契约要求的 skill 版本文件。

流程覆盖密码认证和 OAuth2 授权码登录；账号读取、首次登录账号写入、
会话写入、提供商失败、凭据错误、账号禁用和写入冲突均有明确分支。
两个入口分别生成时序图，详细分支集中在模块文档的分支矩阵中。

## 复现流程

执行发现前先为示例初始化本地 Git 历史，然后在本目录运行已安装的
`devflow` 可执行文件：

```text
git init
git add app.py README.md
git commit -m "添加用户登录示例"
devflow biz-flow init --project .
devflow biz-flow discover --project .
# 查看并确认 docs/biz-flow/业务流程覆盖总览.md。
devflow biz-flow generate --project .
# 当前环境没有真实子代理时，只有得到用户明确许可才使用串行降级：
# devflow biz-flow generate --project . --allow-degraded
devflow biz-flow check --project .
devflow biz-flow verify --project .
```

Markdown 业务模块文档是可读产物。证据始终关联文档列出的源代码位置，
不会用笼统的“数据库”或“外部服务”参与者推断分支。
默认生成会在子代理能力不可用时返回 `DELEGATION_UNAVAILABLE`；成功运行会在
`~/.local/state/devflow/artifacts/biz-flow/` 留下执行清单，记录任务树、批次、并行性和覆盖验收。
