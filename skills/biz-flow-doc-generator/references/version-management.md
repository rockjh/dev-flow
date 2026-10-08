# 版本与源码基线

唯一权威版本文件为 `docs/biz-flow/biz-flow-doc-generator-version.json`：

```json
{
  "skill": "biz-flow-doc-generator",
  "skill_version": "2.0.0",
  "artifact_root": "docs/biz-flow",
  "source": {"git_commit": "<40 位提交 SHA 或 null>"}
}
```

Skill 发布版本与 source.git_commit 分别表示工具能力和已验收源码基线，不得互相覆盖。Git dirty 及 source fingerprint 在总览/外部 manifest 中报告；commit 相同但 dirty/fingerprint 不同不能复用陈旧确认或证据。项目仅持久化业务 Markdown 和此 JSON，扫描/证据机器结构不得另建项目 JSON；执行及审核 manifest 在共享状态目录。

init 创建版本文件；旧版有效版本文件通过 `init --project <project> --upgrade` 显式升级到 2.0.0，保留原 source.git_commit，不把迁移当成源码验收，并撤销旧流程确认。普通 init 不隐式迁移或覆盖失效锁；升级后重新 discover、入口验收和分类确认。discover 创建目录但不推进接受基线；可选 review 同样不推进。生成文档仍不代表接受成功：只有 check 和连续两次 verify 通过后，才允许将 source.git_commit 推进为本次验收提交。失败、部分入口完成、关键证据缺失或不稳定时保留原基线。更新时保留未变文档，报告仅版本变更与业务变更文档。

源码注册或模块映射改变后重新发现并校验确认；纯说明变更不机械撤销未变入口归属。不可解析旧基线时明确全量回退，不能假称增量比较。旧 biz-flow.json、biz-flow.yaml、根 .devflow.lock.json 不属于运行时兼容路径，迁移只能由操作员显式执行，不得自动读取旧状态。

2.0.0 将流程改为两个独立大步骤：无需代理的注册业务入口目录及一级业务域清单骨架（一个域一个文件，域内场景按入口分节）；确认后仅入口可达链的有界并行分析和时序图。保留 1.x 的稳定声明身份、全量入口清单、业务化概览、真实证据补齐、sole JSON、脱敏、增量与覆盖/稳定性门禁；分类前强制 review 改为第二阶段可选审核。
