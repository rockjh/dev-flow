# Skill 编写规则

这些规则适用于 `skills/` 下的每个可安装 Skill，并补充仓库根目录的
`AGENTS.md`。

## 必需结构

每个 Skill 必须严格遵循以下契约：

```text
<category>/<skill-name>/
  SKILL.md
  agents/openai.yaml
  references/            # optional, but every referenced file must exist
```

`SKILL.md` frontmatter 必须包含稳定的 `name`，与完整的
`devflow/<category>/<skill-name>` 路径一致，并包含简短准确的 `description`。
正文必须说明命令路由、输入/项目边界、必需工作流、校验门禁以及返回的权威报告或工件。

`agents/openai.yaml` 必须包含一个 `interface`，并提供项目要求的
`display_name`、`short_description` 和 `default_prompt` 字段。允许使用文档规定的图标、调用策略和工具依赖等可选字段。提示词是指令补充，不是唯一的强制层。它必须：

1. 仅选择本 Skill 的领域路由；
2. 使用已安装的 `devflow` 可执行文件；
3. 只读取所选工作流需要的参考资料；
4. 保留架构、锁、所有权、安全、脱敏和工件规则；
5. 遇到证据缺失、歧义、不安全目标或门禁失败时停止；
6. 返回已脱敏的权威结果，或其路径和退出状态。

不得声称 CLI 未实现的能力。不得在此提示词中放入其他 Skill 的领域指令。

## 参考资料和变更规则

参考资料应使用相对于 Skill 的路径并按需加载。规范性规则应保留在一个规范参考文件中，不要将相互冲突的版本复制到多个 Skill。示例必须明确标注，不得伪装成实际项目状态或包含机密。

Skill 变更必须保留现有领域的业务语义。如果变更影响项目根目录、生成文件、锁、架构、脱敏或退出行为，必须同步更新 CLI 契约和测试。绝不能削弱安全或所有权门禁来让提示词看似成功。

`skills/` 下的规范树是唯一事实来源。npm 树是 `npm/skills/devflow/` 下的生成输出，必须通过 `scripts/release.py` 刷新；不要只手工编辑 npm 副本。发布前确认每个规范 Skill 都有一个匹配的 npm 副本，且不存在旧版 Skill 目录。

## 验收检查

对于新增或变更的 Skill，确认：

- frontmatter、目录名、提示词路由和锁中的 `skill` 值一致；
- 提示词引用的每个文件都存在且位于 Skill 目录内；
- 不安全、含糊和校验失败路径均有明确处理；
- 输出已脱敏，结果较大时指向权威工件；
- 发布暂存步骤后规范树和 npm 树完全一致；
- 根目录 `AGENTS.md` 中的仓库校验命令通过。
