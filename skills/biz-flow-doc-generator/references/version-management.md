# 版本与源码基线

唯一权威版本文件为 `docs/biz-flow/biz-flow-doc-generator-version.json`：

```json
{
  "skill": "biz-flow-doc-generator",
  "skill_version": "5.1.0",
  "artifact_root": "docs/biz-flow",
  "source": {"git_commit": "<40 位提交 SHA 或 null>"}
}
```

Skill 发布版本与 source.git_commit 分别表示工具能力和已验收源码基线，不得互相覆盖。Git dirty 及 source fingerprint 在总览/外部 manifest 中报告。确认绑定 target commit、归一化提交快照指纹及模块映射签名；绑定变化才失效。工作区 dirty、未跟踪文件或 HEAD 前进不改变已冻结 target，也不单独撤销确认。项目仅持久化业务 Markdown 和此 JSON；扫描/证据机器结构不得另建项目 JSON；执行及审核 manifest 在共享状态目录。

init 创建版本文件；只接受当前 schema 和 Skill 版本，不转换其他格式。discover 创建目录但不推进接受基线；prepare 只创建任务包，collect 校验结果并生成文档，只有 check 和连续两次 verify 通过后 accept 才推进 source.git_commit。失败、部分入口完成、关键证据缺失或不稳定时保留原基线。

prepare 将唯一版本 JSON 的完整字节摘要绑定为 version_input_hash，任务包和 manifest 都保存该值，即使 docs 被 Git 忽略也受保护。collect、check、verify 和 accept 拒绝任务准备后任何外部版本文件改写，包括基线、其他字段和格式。accept 自身合法推进基线后保存 accepted_version_hash，后续验收核对该值；原始任务包保持不变。旧运行缺少此保护项时须重新准备，不手工补写历史。并发操作使用共享状态目录中的 ProjectDomainLock OS 锁；持锁进程退出后由操作系统释放，不以 PID 探活、删除锁文件或终止其他进程恢复。

项目根目录按真实克隆位置解析；项目内 docs 及 docs/biz-flow 不得是符号链接或 Windows junction，不能把业务资产写到项目外。父目录尚不存在时可正常初始化，别名或逃逸则在创建资产前停止。

源码注册或模块映射改变后重新发现并校验确认；纯说明变更不机械撤销未变入口归属。不可解析已验收基线时明确报告无法增量比较，按现有规则重新分析完整范围。运行时只读取上述权威 JSON 和共享状态目录，不读取其他版本文件或状态路径。

5.1.0 使用领域 schema 6、宿主协议 5.0：入口目录确认后 prepare/collect，冻结源码事实与业务注释分离；补证经适配器校验后新建运行。行为分析只能来自宿主原生子代理或明确授权的串行会话。其他协议、执行器、review、generate、update 和 allow-degraded 入口均不支持；不符合当前契约的运行须重新准备。

所有运行读取入口（包括 prepare --resume）在读取业务结构前检查当前协议和 schema，再按核心 handoff schema 和当前 adapter 校验。任务包还必须属于 biz-flow 且声明当前宿主协议；哈希一致不替代契约校验。默认选择本项目最新的非 superseded 运行，若该运行不受支持则停止，不自动回退到较早的运行；需要选择另一份合法当前运行时显式提供 run-id。验收汇总只计入当前契约有效、adapter 一致、项目/文档/target/mapping 匹配且文档哈希未变的 accepted 记录。拒绝旧记录时保留原始字节和版本锁，不补字段、不改版本、不迁移状态；操作员可显式清理或重新 prepare。合法的当前 5.1.0/schema 6/协议 5.0 运行继续遵循本版本工作流，本次门禁修复不另设兼容分支。
