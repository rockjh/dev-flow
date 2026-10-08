# 版本与源码基线

唯一权威版本文件为 `docs/biz-flow/biz-flow-doc-generator-version.json`：

```json
{
  "skill": "biz-flow-doc-generator",
  "skill_version": "3.0.0",
  "artifact_root": "docs/biz-flow",
  "source": {"git_commit": "<40 位提交 SHA 或 null>"}
}
```

Skill 发布版本与 source.git_commit 分别表示工具能力和已验收源码基线，不得互相覆盖。Git dirty 及 source fingerprint 在总览/外部 manifest 中报告；commit 相同但 dirty/fingerprint 不同不能复用陈旧确认或证据。项目仅持久化业务 Markdown 和此 JSON，扫描/证据机器结构不得另建项目 JSON；执行及审核 manifest 在共享状态目录。

init 创建版本文件；旧版锁不会自动迁移，必须归档旧项目后重新 init。discover 创建目录但不推进接受基线；prepare 只创建任务包，collect 校验结果并生成文档，只有 check 和连续两次 verify 通过后 accept 才推进 source.git_commit。失败、部分入口完成、关键证据缺失或不稳定时保留原基线。

源码注册或模块映射改变后重新发现并校验确认；纯说明变更不机械撤销未变入口归属。不可解析旧基线时明确全量回退，不能假称增量比较。旧 biz-flow.json、biz-flow.yaml、根 .devflow.lock.json 不属于运行时兼容路径，迁移只能由操作员显式执行，不得自动读取旧状态。

3.0.0 将流程改为入口目录确认与 prepare/collect 两阶段；行为分析只能来自宿主原生子代理或明确授权的串行会话。旧执行器、review、generate、update 和 allow-degraded 均不再属于协议。
