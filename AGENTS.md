# devflow 仓库规则

这些规则适用于整个仓库。更深层目录中的 `AGENTS.md` 可以增加约束，但不得放宽本文件的要求。

## 架构

- Python 包源码位于 `src/toolkit/`，仓库测试位于 `src/test/`；唯一的 `pyproject.toml` 保留在仓库根目录。开发环境通过 `python -m pip install -e .` 安装后运行 CLI。

- Python 导入包使用 `toolkit`；项目发行名称、公共 CLI 和 npm 安装器使用 `devflow`，npm 包名称为 `dev-flow`。
- 唯一的控制台入口是 `devflow = toolkit.cli:console_main`。`python -m toolkit` 会调用同一个入口。
- 共享契约位于 `src/toolkit/core/`；领域模块位于 `src/toolkit/bru_api_test_generator/`、`src/toolkit/e2e_test_generator/` 和 `src/toolkit/biz_flow_doc_generator/`。可安装的 Skill 位于 `skills/<skill-name>/`，并安装到 `~/.agents/skills/<skill-name>/`。
- 命令使用静态注册。不得加入动态插件发现、运行时扫描、兼容性门面、占位模块或第二套扩展机制。
- 不得恢复旧版包名或命令名、旧版 Skill 目录、旧版 npm 包装器、第二个 `pyproject.toml`，也不得在生成项目中复制工具包源代码。

## 契约

`src/toolkit/core/envelope.py`、`errors.py`、`schema.py`、`redaction.py` 和 `artifacts.py` 是信封、退出代码、作用域模式、脱敏、工件和锁的权威实现。所有领域都必须通过这些核心模块路由结果。流水线默认输出 JSON，TTY 默认输出 Markdown，进度信息写入 stderr；除非请求 `--full`，大型结果都应返回摘要及权威路径。领域模式版本独立于工具版本。

当前启用的领域是 `bru-api`、`e2e` 和 `biz-flow`。修改包、CLI、Skill、状态、安装和发布结构时，必须保留它们现有的业务、安全、所有权和报告语义。

## 生成资产与发布

生成项目包含业务资产和调用已安装 `devflow` 的轻量启动器，不得包含工具包源代码。每个 skill 只使用自己的权威版本文件：`docs/biz-flow/biz-flow-doc-generator-version.json`、`qa/contracts/bru-api-test-generator-version.json` 或 `analysis/e2e-test-generator-version.json`；共享状态位于 `~/.local/state/devflow/`；Skill 目标目录为 `DEVFLOW_SKILL_HOME` 或 `~/.agents/skills/`。

npm 流程依次使用 `npm/dist/` 中的内嵌 wheel、pipx、一个 Skill 目录，最后运行 `devflow doctor`。包装器解析 pipx 安装的绝对路径，绝不能通过 `PATH` 递归启动自身。禁用 npm postinstall 时，`npx dev-flow install` 是显式恢复命令。

旧状态迁移必须由操作员在运行时启动之外显式执行。运行时代码只读取新的状态目录，绝不回退到旧路径。

## Skill 编写

每个可安装 Skill 都是有版本的产品表面，必须遵守本节规则。`skills/` 目录不保留独立规则文件，其结构与参考文件约定一律以本节为准。只有同时更新运行时领域、提示词、参考资料、生成资产、npm 载荷和验证流程后，新 Skill 才算完成。

Codex 的项目指令链由从项目根目录到当前目录找到的 `AGENTS.md` 文件构成。选择 Skill 后会加载 `SKILL.md`；`agents/openai.yaml` 提供可选的 Skill 界面、调用和工具依赖元数据。必须保持这些层级一致：更窄范围的 `AGENTS.md` 或 Skill 指令可以增加约束，但不得削弱仓库契约或授权不安全操作。必需行为必须写入 `AGENTS.md`、`SKILL.md` 或可执行门禁，不能只写在可选的界面元数据中。

对于每个新增或修改的 Skill：

- 只使用 `skills/<skill-name>/` 下的一个规范目录。目录名、`SKILL.md` frontmatter 中的 `name`、锁中的 `skill` 值以及生成的 npm 载荷必须完全一致。不得添加别名、旧路径或需要手工维护的副本。
- 保持 `SKILL.md` 简洁且可执行。必须说明 CLI 路由、允许的项目根目录和资产、安全与所有权门禁、权威输出，以及每个工作流必须阅读的参考资料。绝不能要求模型猜测缺失证据或静默绕过失败门禁。
- 每个 Skill 只提供一个 `agents/openai.yaml` 接口，并包含项目要求的 `display_name`、`short_description` 和领域专用 `default_prompt`。必要时可以使用文档规定的图标、调用策略和工具依赖等可选字段。默认提示词用于补充 `SKILL.md`；必须只路由到该 Skill，要求使用已安装的 `devflow` CLI，保留核心契约，要求返回已脱敏的权威输出，并明确不安全、含糊或验证失败时的停止条件。不得使用在无关 Skill 之间路由的通用提示词。
- 将详细流程、模式、示例和策略放在 `references/` 中。参考路径必须相对于 Skill、保持稳定，并从 `SKILL.md` 或默认提示词中明确路由。生成的业务数据必须与可复用说明分离，绝不能嵌入密钥或凭据。
- 保持行为确定：不得加入运行时提示词发现、仅依赖网络的说明、隐藏工具回退、动态插件加载，也不得加入会在没有显式工作流和领域验证门禁的情况下修改源代码、状态、锁或历史的指令。
- 先更新规范 Skill，再通过 `scripts/release.py` 重新生成或复制 npm 载荷。检查生成后的树，确认路径和名称匹配，并运行下方完整验证命令。
- 不得声称 `devflow` CLI 未实现的能力。
- `SKILL.md` 或默认提示词引用的每个参考文件都必须存在且位于该 Skill 目录内；禁止引用不存在的路径。

审查 Skill 变更时，除常规代码正确性外，还要检查提示词优先级、领域隔离、证据要求、脱敏、资产路径、失败行为，以及规范目录与 npm 目录的一致性。

## 验证

对于代码、模式或模板变更，先运行相关测试，然后运行：

```text
python -m pytest -q
python -m compileall -q src/toolkit src/test
git diff --check
```

发布变更还需运行 `python scripts/release.py`，确认 wheel 只包含 `devflow` 入口、npm 载荷包含一个 Skill、版本已同步，并完成隔离的 npm -> pipx -> Skill 同步 -> `doctor` 流程。不得提交 `dist/`、npm wheel/vendor/tgz 产物、缓存或本地状态。
