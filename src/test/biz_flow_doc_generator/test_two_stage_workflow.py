"""两阶段流程必须先完整交付入口目录，再依赖真实代理分析行为。"""

import json
import subprocess

from toolkit.biz_flow_doc_generator import cli
from toolkit.biz_flow_doc_generator import git
from toolkit.biz_flow_doc_generator.documents import write_discovery, write_entry_directory
from toolkit.biz_flow_doc_generator.models import EntryPoint, ScanResult, GitInfo




def test_empty_git_head_cannot_turn_worktree_into_a_historical_snapshot(tmp_path, monkeypatch):
    heads = iter(["", "a" * 40])
    monkeypatch.setattr(git, "_run", lambda root, *args: next(heads) if args[0] == "rev-parse"
                        else "## main" if args[0] == "status" else "")
    info = git.git_info(tmp_path)
    assert info.head == info.target == "a" * 40
    assert info.comparison == "current"


def test_dirty_worktree_source_view_uses_committed_files(tmp_path):
    (tmp_path / "app.py").write_text("committed = True\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.name", "Test"),
                 ("config", "user.email", "test@example.invalid"), ("add", "app.py"),
                 ("commit", "-qm", "baseline")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    version = tmp_path / "docs" / "biz-flow"
    version.mkdir(parents=True)
    (version / "biz-flow-doc-generator-version.json").write_text("{}", encoding="utf-8")
    (tmp_path / "app.py").write_text("committed = False\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("untracked = True\n", encoding="utf-8")
    with git.source_view(tmp_path) as (view, info):
        assert info.dirty is True
        assert (view / "app.py").read_text(encoding="utf-8") == "committed = True\n"
        assert not (view / "untracked.py").exists()


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
    assert mapping["modules"][0]["file"] == "00-套餐.md"
    stale = tmp_path / "99-套餐查询.md"
    stale.write_text("<!-- biz-flow-module: 旧查询 -->\n# 套餐查询\n\n<!-- devflow:entry-directory -->\n旧入口\n<!-- /devflow:entry-directory -->\n", encoding="utf-8")
    manual = tmp_path / "98-人工说明.md"
    manual.write_text(stale.read_text(encoding="utf-8") + "\n人工补充说明", encoding="utf-8")
    assert write_entry_directory(result, tmp_path, mapping) == []
    assert not stale.exists()
    assert manual.exists()


def test_removed_skill_upgrade_cannot_modify_accepted_git_baseline(tmp_path):
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
    import pytest
    with pytest.raises(SystemExit) as error:
        cli.init_command([*args, "--upgrade"])
    assert error.value.code == 2
    assert json.loads(path.read_text(encoding="utf-8")) == metadata
    assert "<!-- devflow:module-confirmed -->" in overview.read_text(encoding="utf-8")


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
        raise AssertionError("入口目录阶段不得展开行为事实")

    monkeypatch.setattr(cli, "rebuild_verified", forbidden)
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
    overview = docs / "业务流程覆盖总览.md"
    inventory = overview.read_text(encoding="utf-8")
    assert "HTTP：GET /users" in inventory
    assert "HTTP：POST /users" in inventory
    assert "业务范围与入口" not in content
    assert "HTTP：" not in content
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
    overview.write_text(inventory.replace(
        next(line for line in inventory.splitlines() if "HTTP：POST /users" in line), ""), encoding="utf-8")
    assert cli.check_command([*args, "--stage", "entries"]) == 1
    overview.write_text(inventory, encoding="utf-8")
    with (tmp_path / "app.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# 删除用户资料\n@app.delete('/users')\ndef delete_user(): return True\n")
    # Uncommitted source is outside the generation snapshot and does not alter
    # the committed entry directory until it is committed.
    assert cli.check_command([*args, "--stage", "entries"]) == 0
