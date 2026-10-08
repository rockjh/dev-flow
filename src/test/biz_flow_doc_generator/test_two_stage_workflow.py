"""两阶段流程必须先完整交付入口目录，再依赖真实代理分析行为。"""

import json
import subprocess

from toolkit.biz_flow_doc_generator import cli
from toolkit.biz_flow_doc_generator import git
from toolkit.biz_flow_doc_generator.documents import _branch_matrix, write_discovery, write_entry_directory, build_index, render_module, _markdown_coverage
from toolkit.biz_flow_doc_generator.models import EntryPoint, ScanResult, GitInfo, EntryReview, FlowStep
from toolkit.biz_flow_doc_generator.validation import validate_branch_coverage


def test_business_branch_labels_match_diagram_and_matrix():
    branch = {"branch_id": "B-status", "business_relevant": True, "reachability": "reachable",
              "condition": 'return "active"', "label": "返回套餐生效状态",
              "outcomes": ["active"], "outcome_labels": ["套餐已生效"], "effects": []}
    entry = EntryPoint("entry", "url", "GET /plans", "query", "Plan.java", 1, "套餐", "Plan.java",
                       agent_branches=[branch])
    diagram = '```mermaid\nsequenceDiagram\nautonumber\n%% devflow:branch id="B-status"\n系统-->>用户: 返回套餐生效状态，套餐已生效\n```\n'
    assert validate_branch_coverage({"branches": [branch]}, diagram + _branch_matrix(entry)) == []


def test_empty_git_head_cannot_turn_worktree_into_a_historical_snapshot(tmp_path, monkeypatch):
    heads = iter(["", "a" * 40])
    monkeypatch.setattr(git, "_run", lambda root, *args: next(heads) if args[0] == "rev-parse"
                        else "## main" if args[0] == "status" else "")
    info = git.git_info(tmp_path)
    assert info.head == info.target == "a" * 40
    assert info.comparison == "current"


def test_windows_git_capture_preserves_commit_dirty_and_failure_details(tmp_path, monkeypatch):
    """真实子进程写入文件句柄，验证元数据、错误输出及空状态不会被误判。"""
    import sys
    from types import SimpleNamespace
    import pytest

    real_run = subprocess.run
    monkeypatch.setattr(git, "sys", SimpleNamespace(platform="win32"))
    def run(command, **kwargs):
        assert "capture_output" not in kwargs
        args = command[1:]
        if args[0] == "rev-parse":
            program = 'print("a" * 40)'
        elif args[0] == "branch":
            program = 'print("main")'
        elif args[0] == "status":
            program = 'print("## main\\n M app.py")'
        else:
            program = 'import sys; print("partial"); print("Git 失败", file=sys.stderr); sys.exit(7)'
        return real_run([sys.executable, "-c", program], **kwargs)
    monkeypatch.setattr(git.subprocess, "run", run)
    info = git.git_info(tmp_path)
    assert info.head == info.target == "a" * 40
    assert info.dirty and info.includes_uncommitted
    assert git.working_tree_paths(tmp_path) == [" M app.py"]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        git._run(tmp_path, "fail")
    assert failure.value.returncode == 7
    assert failure.value.stdout.strip() == "partial"
    assert "Git" in failure.value.stderr
    monkeypatch.setattr(git, "_run", lambda root, *args: "a" * 40 if args[0] == "rev-parse" else "")
    with pytest.raises(RuntimeError, match="工作区状态读取失败"):
        git.git_info(tmp_path)
    with pytest.raises(RuntimeError, match="工作区状态读取失败"):
        git.working_tree_paths(tmp_path)


def test_agent_controls_use_branch_evidence_and_action_text_has_one_limit(tmp_path):
    branch = {"branch_id": "B-status", "business_relevant": True, "reachability": "reachable",
              "condition": "enabled", "label": "检查账号可用性", "outcomes": ["可用", "不可用"],
              "outcome_labels": ["允许登录", "拒绝登录"], "effects": [], "source_file": "app.py", "source_line": 1}
    entry = EntryPoint("entry", "url", "POST /auth", "login", "app.py", 1, "用户认证", "app.py",
                       business_name="用户登录", caller="用户", agent_branches=[branch])
    entry.review = EntryReview("entry", "登录请求", "验证登录资格", "登录凭据", "返回认证结果", "拒绝无效凭据",
                               [FlowStep("alt", "检查账号可用性，允许登录", "app.py:1", branch_ids=["B-status"]),
                                FlowStep("action", "保存当前用户登录会话" * 15, "app.py:2"),
                                FlowStep("action", "允许登录", "app.py:3", "用户", response=True),
                                FlowStep("else", "拒绝登录", "app.py:1"),
                                FlowStep("action", "拒绝登录", "app.py:4", "用户", response=True),
                                FlowStep("end", "", "app.py:4")], "confirmed", "agent:test")
    result = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                        ["Python"], [], [entry], [], [], "b" * 64)
    mapping = {"name": "用户认证", "file": "00-用户认证.md", "display_name": "用户认证",
               "responsibility": "用户登录", "entry_ids": ["entry"]}
    text = render_module("用户认证", [entry], result.git, result, comparison="current", module_meta=mapping)
    (tmp_path / mapping["file"]).write_text(text, encoding="utf-8")
    index = build_index(result, tmp_path, {"用户认证": mapping["file"]}, comparison="current")
    coverage = _markdown_coverage(result, index, tmp_path)
    assert coverage["markdown_diagram_mismatches"] == []
    assert validate_branch_coverage({"branches": [branch]}, text) == []
    assert validate_branch_coverage({"branches": [branch]}, text.replace('%% devflow:branch id="B-status"', ""))


def test_domain_titles_do_not_split_actions_and_regroup_only_generated_skeletons(tmp_path):
    entries = [EntryPoint("e1", "url", "GET /plans", "query", "Plan.java", 1, "套餐", "Plan.java",
                          business_name="查询可售套餐", module_label="可售套餐管理"),
               EntryPoint("e2", "scheduled", "恢复套餐", "recover", "Plan.java", 2, "套餐", "Plan.java",
                          business_name="恢复套餐履约", module_label="套餐履约恢复")]
    result = ScanResult(root=tmp_path, git=GitInfo("main", "a" * 40, "a" * 40, False, False),
                        languages=["Java"], frameworks=[], files=["Plan.java"], entries=entries,
                        unresolved=[], source_fingerprint="b" * 64)
    _, mapping_path = write_discovery(result, tmp_path)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert len(mapping["modules"]) == 1
    assert mapping["modules"][0]["display_name"] == "套餐"
    assert mapping["modules"][0]["file"] == "00-套餐履约.md"
    stale = tmp_path / "99-套餐查询.md"
    stale.write_text("<!-- biz-flow-module: 旧查询 -->\n# 套餐查询\n\n<!-- devflow:entry-directory -->\n旧入口\n<!-- /devflow:entry-directory -->\n", encoding="utf-8")
    manual = tmp_path / "98-人工说明.md"
    manual.write_text(stale.read_text(encoding="utf-8") + "\n人工补充说明", encoding="utf-8")
    assert write_entry_directory(result, tmp_path, mapping) == []
    assert not stale.exists()
    assert manual.exists()


def test_explicit_skill_upgrade_preserves_accepted_git_baseline(tmp_path):
    (tmp_path / ".git").mkdir()
    docs = tmp_path / "docs/biz-flow"
    docs.mkdir(parents=True)
    path = docs / "biz-flow-doc-generator-version.json"
    metadata = {"skill": "biz-flow-doc-generator", "skill_version": "1.7.1",
                "artifact_root": "docs/biz-flow", "source": {"git_commit": "a" * 40}}
    path.write_text(json.dumps(metadata), encoding="utf-8")
    overview = docs / "业务流程覆盖总览.md"
    overview.write_text("<!-- devflow:module-confirmed -->", encoding="utf-8")
    args = ["--project", str(tmp_path)]
    assert cli.init_command(args) == 8
    assert json.loads(path.read_text(encoding="utf-8")) == metadata
    assert cli.init_command([*args, "--upgrade"]) == 0
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["skill_version"] == "2.0.0"
    assert upgraded["source"] == metadata["source"]
    assert "<!-- devflow:module-confirmed -->" not in overview.read_text(encoding="utf-8")


def test_entry_directory_is_complete_without_behavior_analysis(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "# 查询用户资料\n@app.get('/users')\ndef query_users():\n    save()\n    return []\n"
        "# 新增用户资料\n@app.post('/users')\ndef create_user():\n    save()\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "one.py").write_text("def save(): return True\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("def save(): return False\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "."),
                 ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("入口目录阶段不得启动代理")

    monkeypatch.setattr(cli, "create_run_manifest", forbidden)
    args = ["--project", str(tmp_path)]
    assert cli.init_command(args) == 0
    assert cli.discover_command(args) == 0
    output = capsys.readouterr().out
    assert "业务模块文件名 | 业务描述 | 入口数量" in output
    assert "Git 版本" in output
    assert "unresolved=0" in output
    docs = tmp_path / "docs/biz-flow"
    modules = [path for path in docs.glob("*.md") if path.name != "业务流程覆盖总览.md"]
    assert len(modules) == 1
    content = modules[0].read_text(encoding="utf-8")
    assert "HTTP：GET /users" in content
    assert "HTTP：POST /users" in content
    assert "```mermaid" not in content
    assert cli.check_command([*args, "--stage", "entries"]) == 0
    assert {path.suffix for path in docs.iterdir()} == {".md", ".json"}
    assert len(list(docs.glob("*.json"))) == 1
    metadata = json.loads(next(docs.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["source"]["git_commit"] is None

    # 重复发现不制造新文件或改变清单内容。
    before = {path.name: path.read_bytes() for path in docs.glob("*.md")}
    assert cli.discover_command(args) == 0
    assert before == {path.name: path.read_bytes() for path in docs.glob("*.md")}

    # 清单被改漏以及源码改变都必须被第一阶段门禁发现。
    modules[0].write_text(content.replace("HTTP：POST /users", "HTTP：POST /users").replace(
        next(line for line in content.splitlines() if "HTTP：POST /users" in line), ""), encoding="utf-8")
    assert cli.check_command([*args, "--stage", "entries"]) == 1
    modules[0].write_text(content, encoding="utf-8")
    with (tmp_path / "app.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# 删除用户资料\n@app.delete('/users')\ndef delete_user(): return True\n")
    assert cli.check_command([*args, "--stage", "entries"]) == 1
