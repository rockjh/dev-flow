# 场景级源代码版本与影响策略

每个 `scenarios/*/场景定义.yaml` 都记录自己的精简源代码依据。`discovery/workspace.yaml` 将稳定仓库 ID 映射到可解析根目录，但不存在全局场景注册表或重复的场景版本文件。Git 历史就是变更记录。

## 源代码契约

```yaml
# 源码基线：每项对应一个被当前场景直接依赖的仓库。
source:
  - repo: <repository-id-from-discovery>
    # 40 位 Git SHA，表示已经完成场景影响审查的提交。
    commit: <40-character-git-sha>
    # 用于重新定位入口、模型、状态变化、控制和清理的高价值源码符号。
    anchors:
      - <source-symbol>
```

尖括号值是元变量。`repo` 必须通过发现清单解析，`commit` 必须等于该仓库经过评审的发现快照。`anchors` 是一组精简的入口、服务、生产者/消费者、schema、仓库、作业、配置符号、控制项或清理方法，用于可靠地重新发现。源代码列表必须覆盖场景拓扑中标记为相关的每个仓库；调用方仓库不能代表下游服务、消息或数据存储所有者。

不要添加分支名、重复 commit 字段、时间戳、叙述性备注或复制的 diff。相关未提交源代码不能用 `commit` 表示，必须单独报告。

迁移旧版源代码版本格式时，不要机械选择更新的修订。以此前生成的修订作为比较基础，完成影响评审，仅重新生成受影响的产物，然后写入经过评审的 `HEAD`。

## 评审算法

对每个场景/仓库组合执行：

1. 通过 `discovery/workspace.yaml` 解析仓库，然后读取记录的 commit、当前 `HEAD` 以及已暂存、未暂存和未跟踪变更。
2. 验证记录的 commit 存在；否则重新执行完整的相关发现。
3. 检查 `git diff --name-status <commit>..<HEAD>` 以及可能相关文件的新旧实际内容。
4. 重新解析每个 anchor，跟踪受影响的调用方、请求/响应或消息模型、状态规则、关联关系、持久化、作业、配置、控制和清理。
5. 检查相关 dirty 内容；anchor 文件未变不代表没有影响。
6. 判断变更是否影响拓扑、配置优先级、前置条件、数据、动作、控制、预期、关联、集成、时序、清理、恢复或图表。
7. 获得更新授权后，仅重新生成受影响产物，并将发现仓库 commit 及所有受影响的 `source.commit` 更新为同一个经过评审的 SHA。在契约门禁前重新发现；仓库 diff 是审计轨迹。

不要声称已与 dirty 的相关源代码同步。将其视为权威依据前先要求提交 commit，或将生成结果标记为草稿并保持记录的 commit 不变。

如果出现新的仓库、构建模块、依赖边或配置源，应在重新生成场景前更新并重新验证工作区发现。不能仅依据此前场景的 anchor 推断拓扑。

## 结果

- `unchanged`：`HEAD` 等于记录的 commit，且不存在相关 dirty 变更。
- `no_relevant_change`：已检查提交的变更，不影响场景。获得授权后推进记录的 commit，不重写其他产物。
- `affected`：提交的变更影响契约或生成实现。仅更新受影响产物，然后推进 commit。
- `full_rediscovery_required`：旧 commit 不可用、anchor 无法解析，或工作区拓扑/配置发生实质变化。
- `dirty_review_required`：存在相关未提交源代码。报告该情况，不推进 commit，也不声称已同步。

## 脚本行为

`devflow e2e source-status` discovers `scenarios/*/场景定义.yaml` directly and resolves repository IDs through discovery. It accepts optional exact `--scenario <中文场景名称>`; unknown, ambiguous, or path-like values are errors.

每个场景/仓库输出一条结果，包含记录的/当前 commit、clean/dirty 状态、相关变更文件、受影响或未解析的 anchor、上述结果之一以及简明原因。

该命令是只读的。不得 fetch、更新定义、重新生成测试、丢弃变更、改写历史，或将多个场景合并为项目级决定。更新源代码 commit 必须在内容检查后通过单独且明确授权的流程完成。
