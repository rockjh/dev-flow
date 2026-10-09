"""One frozen sequence tree produces Mermaid, Markdown and the coverage matrix."""
from pathlib import Path
import shutil
import subprocess

from .models import DiagramPosition, DocumentBundle, FlowStep, RenderReport, SceneDocument, SequenceArm, SequenceBlock, SequenceStep
from .repository import digest, stable_id


def mermaid_text(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace(";", "；").replace('"', "＂").replace("<", "＜").replace(">", "＞").replace("&", "＆")


class SequenceRenderer:
    def _diagram(self, tree, steps, labels, filename, view, block_evidence):
        names = sorted({name for step in steps.values() for name in (step.sender, step.receiver)})
        participants = {name: f"P{index}" for index, name in enumerate(names)}
        lines = ["sequenceDiagram", "autonumber"] + [f"participant {alias} as {mermaid_text(name)}" for name, alias in participants.items()]
        positions = []
        def items(values, path):
            for index, item in enumerate(values):
                location = path + f"/{index}"
                if isinstance(item, SequenceBlock):
                    visit(item, location)
                else:
                    step = steps[item.step_id]
                    arrow = "-->>" if step.kind in {"call_return", "return", "await", "wait"} else "->>"
                    caption = labels.get(step.step_id, step.label)
                    if view == "proposal":
                        caption = "[需求方案] " + caption
                    sender, receiver = (step.receiver, step.sender) if step.kind == "call_return" else (step.sender, step.receiver)
                    lines.append(f"{participants[sender]}{arrow}{participants[receiver]}: {mermaid_text(caption)}")
                    positions.append(DiagramPosition(step.step_id, filename, location, step.evidence_ids))
        def arm_position(block, arm, location):
            if arm.exit_id:
                positions.append(DiagramPosition(arm.exit_id, filename, location, block_evidence.get(block.block_id, ())))
        def visit(block, path):
            if block.kind == "sequence":
                for index, arm in enumerate(block.arms):
                    items(arm.items, path + f"/arm:{index}")
                return
            positions.append(DiagramPosition(block.block_id, filename, path, block_evidence.get(block.block_id, ())))
            if block.kind == "loop":
                lines.append("loop " + mermaid_text(block.label))
                first = block.arms[0]
                arm_position(block, first, path + "/iteration")
                items(first.items, path + "/iteration")
                lines.append("end")
                for index, arm in enumerate(block.arms[1:]):
                    lines.append(("alt " if index == 0 else "else ") + mermaid_text(arm.label))
                    arm_position(block, arm, path + f"/exit:{index}")
                    items(arm.items, path + f"/exit:{index}")
                if len(block.arms) > 1:
                    lines.append("end")
                return
            for index, arm in enumerate(block.arms):
                directive = block.kind if index == 0 else "and" if block.kind == "par" else "else"
                lines.append(directive + " " + mermaid_text(arm.label or block.label))
                arm_position(block, arm, path + f"/arm:{index}")
                items(arm.items, path + f"/arm:{index}")
            lines.append("end")
        visit(tree, "root")
        return "\n".join(lines) + "\n", tuple(positions)

    def build(self, model, annotations, intent, requirement_report):
        labels = {item.target_id: item.label for item in annotations.labels}
        scenes, rows = [], []
        for index, scope in enumerate(model.scopes, 1):
            steps = {step.step_id: step for step in scope.steps}
            block_evidence = {c.control_id: c.evidence_ids for c in scope.controls}
            filename = f"{index:02d}-{scope.scope.entry_id}-implementation.md"
            mermaid, positions = self._diagram(scope.sequence, steps, labels, filename, "implementation", block_evidence)
            by_step = {position.target_id: position for position in positions}
            positions += tuple(DiagramPosition(operation.operation_id, filename, by_step[operation.call_site_id].tree_path,
                                              operation.evidence_ids) for operation in scope.external
                               if operation.call_site_id in by_step)
            names = sorted({step.receiver for step in scope.steps} | {step.sender for step in scope.steps})
            markdown = f"# {scope.scope.symbol.qualified_name}\n\n目的：呈现选定范围的当前静态实现。\n\n参与方：{'、'.join(names) or '所选函数'}。\n\n关键流程：按代码控制出口、调用上下文和已观察等待关系展示；依赖内部不展开。\n\n```mermaid\n{mermaid}```\n\n完整覆盖仅指选定静态范围内已发现的相关控制点及出口，不证明所有输入、循环次数或并发交错。\n"
            scenes.append(SceneDocument(filename, scope.scope.entry_id, "implementation", scope.sequence, mermaid, markdown, positions))
            rows += [f"| `{p.target_id}` | {filename} | `{p.tree_path}` | {', '.join(p.evidence_ids)} |" for p in positions]
        if intent == "proposal" and requirement_report.requirements:
            steps, seq = {}, []
            by_requirement = {r.requirement_id: r for r in requirement_report.requirements}
            for proposed in annotations.proposed_steps:
                evidence = tuple(segment for rid in proposed.requirement_ids for segment in by_requirement[rid].segment_ids)
                step = FlowStep(proposed.step_id, "requirement-plan", proposed.kind, proposed.sender, proposed.receiver,
                                proposed.label + " [" + ", ".join(proposed.requirement_ids) + "]", "", evidence)
                steps[step.step_id] = step
                seq.append(SequenceStep(step.step_id))
            tree = annotations.proposed_sequence or SequenceBlock(stable_id("B", "proposal", tuple(steps)), "sequence", "拟议流程", (SequenceArm("", "", tuple(seq)),))
            filename = "proposal.md"
            control_evidence = {c.control_id: tuple(segment for rid in c.requirement_ids for segment in by_requirement[rid].segment_ids) for c in annotations.proposed_controls}
            mermaid, positions = self._diagram(tree, steps, {}, filename, "proposal", control_evidence)
            markdown = "# 需求流程方案\n\n目的：表达有来源依据的目标流程；待实现内容不作为源码事实。\n\n参与方：" + "、".join(sorted({s.sender for s in steps.values()} | {s.receiver for s in steps.values()})) + "。\n\n关键流程：每个步骤标明 R-ID，与当前实现分别验收。\n\n```mermaid\n" + mermaid + "```\n\n"
            for r in requirement_report.requirements:
                markdown += f"- `{r.requirement_id}`：{r.text}；状态：{r.status}；实现评估：{r.implementation_assessment}；差异：{r.difference}\n"
            scenes.append(SceneDocument(filename, "requirement-plan", "proposal", tree, mermaid, markdown, positions))
            rows += [f"| `{p.target_id}` | {filename} | `{p.tree_path}` | {', '.join(p.evidence_ids)} |" for p in positions]
        matrix = "# 图与证据覆盖矩阵\n\n| 目标 | 场景 | 树位置 | 证据 |\n| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n"
        matrix += "\n## 需求映射\n\n| R-ID | 状态 | 实现评估 | 目标 | 来源区段 |\n| --- | --- | --- | --- | --- |\n"
        links = {link.requirement_id: link.target_ids for link in requirement_report.links}
        for r in requirement_report.requirements:
            matrix += f"| {r.requirement_id} | {r.status} | {r.implementation_assessment} | {', '.join(links.get(r.requirement_id, ()))} | {', '.join(r.segment_ids)} |\n"
        gaps = [g for s in model.scopes for g in s.gaps]
        overview = f"# 时序图覆盖报告\n\n代码作用域：{len(model.scopes)}。需求来源区段：{requirement_report.processed_segments}/{requirement_report.candidate_segments}。\n\n实现一致性：{requirement_report.implementation_consistency}。解析缺口：{len(gaps)}（独立于图覆盖率）。\n\n宿主证据为 host_attested，CLI 不证明代理真实运行或业务解释绝对正确。\n"
        return DocumentBundle(tuple(scenes), matrix, overview, requirement_report)

    def render(self, bundle, renderer, directory):
        executable = shutil.which(renderer) if renderer else None
        hashes = tuple(digest(scene.mermaid) for scene in bundle.scenes)
        if not executable:
            return RenderReport("not_run", "", "", hashes, ("mmdc unavailable; local structural validation only",))
        executable = str(Path(executable).resolve())
        directory.mkdir(parents=True, exist_ok=True)
        try:
            version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=True).stdout.strip()
            for index, scene in enumerate(bundle.scenes):
                source, output = directory / f"scene-{index}.mmd", directory / f"scene-{index}.svg"
                source.write_text(scene.mermaid, encoding="utf-8")
                subprocess.run([executable, "-i", str(source), "-o", str(output)], capture_output=True, text=True, timeout=60, check=True)
                if not output.is_file() or not output.stat().st_size:
                    raise ValueError("renderer did not produce an image")
            return RenderReport("passed", executable, version, hashes, ())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return RenderReport("failed", executable, "", hashes, (str(exc),))
