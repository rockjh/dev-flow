# 版本文件管理

本 Skill 的唯一权威版本文件是 `analysis/e2e-test-generator-version.json`。文件固定包含：

    {
      "skill": "e2e-test-generator",
      "skill_version": "2.1.0",
      "artifact_root": "analysis",
      "version": 1,
      "document_baseline": {"git_commit": "<40 位提交 SHA>"},
      "design": {},
      "protocol": {},
      "source": [],
      "support": {},
      "scenario_generation": {},
      "changes": {},
      "scenarios": {}
    }

该文件只记录本 Skill 的设计、协议、源码、支持配置、场景数据和清理指纹。`skill_version` 是 Skill 发布版本；`version` 和各业务字段是输入锁格式及生成摘要。运行时只接受当前 schema 的该 JSON，不读取、转换或自动删除其他版本文件。

e2e 的 init、generate、check、source-status 和 run 只读取自己的 JSON。文档基线只有在文档门禁和下游检查成功后才推进；缺少、损坏、技能元数据不匹配或任一指纹过期都会停止。

2.1.0 / E2E schema 11 将 delegated owner 绑定到当前宿主会话实际执行的任务及收集回执。
手填 owner 标签不能作为原生执行证明；不符合当前契约的运行必须重新准备。任务和 manifest 在
`~/.local/state/devflow/artifacts/e2e/`，业务版本权威仍只有上述 JSON。
schema 11 包含 `generate/init --serial-approval` 的明确授权串行交接。
它创建新 run 并关联前次 run，沿用 host_task、collect 和现有业务锁，保留原生执行历史。
手填 `sequential_degraded` 标签不能替代已收集的串行任务和完整静态验收。

存在原生或串行交接任务时，prepare 和聚合 contracts 检查不推进文档基线。全部 owner 成功收集、
当前输入的既有有序静态验收通过后才推进；pending、失败或陈旧结果保留旧基线及待处理变更。
首次基线为 null 的原生运行可以经 check 正常收集和验收，不能用未验收状态建立成功基线。
