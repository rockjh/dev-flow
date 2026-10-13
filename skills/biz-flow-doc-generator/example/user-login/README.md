# 用户登录入口示例

源码保留密码登录与 OAuth2 登录、账号绑定和内存会话逻辑，不包含真实凭据或数据库。ACCOUNTS_TABLE 与 SESSIONS_TABLE 是进程内字典。

本目录是入口目录 fixture：两个入口归属用户认证域，总览集中保存业务范围和完整入口清单，模块 Markdown 仅有标题。版本锁 source.git_commit=null；示例不包含真实宿主执行回执或已验收基线，不能作为生产验收证据。

复制到独立 Git 仓库并提交源码后，使用已安装 devflow：

```text
devflow biz-flow init --project <example>
devflow biz-flow discover --project <example>
devflow biz-flow check --project <example> --stage entries
devflow biz-flow prepare --project <example> --confirm
```

按 references/behavior-evidence.md 与 references/agent-orchestration.md 读取实际 schema、冻结事实和提交快照。当前 Python 适配器对部分条件出口、动态内存对象和未知调用会保留关键 gaps；应报告具体缺口，不能复制旧图或改写源码规避门禁。只有事实完整且真实宿主任务完成后，才可 collect、check、verify、verify、accept。prepare 不代表已完成。

缺失事实的补证使用独立 evidence_request。CLI 证明并重建后创建替换运行，必须重新执行全部任务。当前 analysis.resolutions 可解释适配器已证明的正常完成、误判和非业务决策行，格式和证据要求见 behavior-evidence.md；不能以说明替代未知事实。旧字符串 outcomes、复制事实数组、旧锁和旧回执不转换。未支持语义保留未决；不宣称整体完成，不推进基线。
