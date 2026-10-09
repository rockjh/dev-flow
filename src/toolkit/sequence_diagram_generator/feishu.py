"""Native layout plus explicit host write/preview/export publication protocol."""
from dataclasses import dataclass, replace
from copy import deepcopy
from pathlib import Path
import json
import re
import struct
import unicodedata
import zlib

from ..core.artifacts import ProjectDomainLock
from ..core.errors import DevflowError, ExitCode
from .models import (BoardConnector, BoardNode, CommitJournal, ControlFlowEdge, ControlNode, DiagramPosition, DocumentBundle, DomainCommandResult, ExternalOperation, FlowModel, FlowStep, NativeBoardBundle,
                     NativeBoardScene, NativeNodeStyle, PublicationManifest, PublicationReceipt, ReferenceBundle, RuleResult, RunState,
                     SemanticAnnotations, SequenceArm, SequenceBlock, SequenceStep, ValidationReport)
from .repository import bytes_digest, confined, digest, from_dict, stable_id, to_dict


def _read(path, limit=50 * 1024 * 1024):
    try:
        path = Path(path).resolve(strict=True)
    except FileNotFoundError as exc:
        raise DevflowError("TARGET_NOT_FOUND", "publication evidence file does not exist", ExitCode.NOT_FOUND) from exc
    if not path.is_file() or path.stat().st_size > limit:
        raise DevflowError("GATE_FAILED", "publication evidence is missing or exceeds the size limit", ExitCode.GATE_FAILED)
    return path.read_bytes()


def _image(path, expected):
    raw = _read(path)
    valid = raw.startswith(b"\x89PNG\r\n\x1a\n")
    offset, chunks = 8, []
    while valid and offset + 12 <= len(raw):
        length = struct.unpack_from(">I", raw, offset)[0]
        end = offset + 12 + length
        if end > len(raw):
            valid = False
            break
        kind = raw[offset + 4:offset + 8]
        content = raw[offset + 8:end - 4]
        valid = zlib.crc32(kind + content) == struct.unpack_from(">I", raw, end - 4)[0]
        if kind == b"IHDR":
            valid = valid and length == 13 and bool(struct.unpack_from(">I", content, 0)[0]) and bool(struct.unpack_from(">I", content, 4)[0])
        chunks.append(kind)
        offset = end
        if kind == b"IEND":
            valid = valid and length == 0
            break
    valid = valid and offset == len(raw) and bool(chunks) and chunks[0] == b"IHDR" and chunks[-1] == b"IEND" and b"IDAT" in chunks
    if bytes_digest(raw) != expected or not valid:
        raise DevflowError("GATE_FAILED", "preview evidence is not a bound structurally valid PNG", ExitCode.GATE_FAILED)


@dataclass(frozen=True, slots=True)
class _LayoutScope:
    entry_id: str
    title: str
    steps: tuple[FlowStep, ...]
    controls: tuple[ControlNode, ...]
    sequence: SequenceBlock
    context_id: str
    control_flow: tuple[ControlFlowEdge, ...] = ()
    operations: tuple[ExternalOperation, ...] = ()


class FeishuLayoutBuilder:
    def reference_styles(self, reference, raw):
        """Derive styles only from explicit role bindings to exported native nodes."""
        validator = FeishuStructureValidator()
        try:
            nodes = validator._absolute_nodes(validator._nodes(raw))
            by_id = {n["id"]: n for n in nodes}
            roles, styles = set(), []
            for binding in reference.style_bindings:
                if binding.role not in {"title", "header", "lane", "step", "control", "wait", "exit"} or binding.role in roles:
                    raise ValueError("unknown or duplicate reference role")
                roles.add(binding.role)
                shape = by_id.get(binding.shape_id)
                text = by_id.get(binding.text_id)
                if binding.role == "title":
                    if binding.shape_id or not text or text.get("type") != "text_shape":
                        raise ValueError("title reference requires only a text node")
                    shape = text
                    fill, border, kind = "#ffffff", "#ffffff", ""
                else:
                    if not shape or shape.get("type") != "composite_shape":
                        raise ValueError("reference requires a native composite shape")
                    style = shape.get("style", {})
                    fill, border = style.get("fill_color", "").lower(), style.get("border_color", "").lower()
                    kind = shape.get("composite_shape", {}).get("type")
                    if kind not in {"rect", "round_rect"} or style.get("border_style") != "solid" or style.get("border_width") != "narrow":
                        raise ValueError("unsupported reference shape or border")
                    if any(style.get(key) for key in ("shadow", "gradient")):
                        raise ValueError("reference decorations are unsupported")
                width, height = shape.get("width"), shape.get("height")
                if not isinstance(width, int) or not isinstance(height, int) or not 100 <= width <= 2000 or not 30 <= height <= 10000:
                    raise ValueError("reference dimensions outside supported layout bounds")
                if binding.role != "lane":
                    if not text or text.get("type") != "text_shape" or not text.get("text", {}).get("text"):
                        raise ValueError("reference role requires a text sample")
                    if not (text.get("x") == shape.get("x") and shape.get("y") <= text.get("y", -1) < shape.get("y") + height):
                        raise ValueError("reference text is not geometrically bound to its shape")
                    typography = text["text"]
                    size, color, weight = typography.get("font_size"), typography.get("text_color", "").lower(), typography.get("font_weight")
                    if not isinstance(size, int) or not 14 <= size <= 40 or weight not in {"regular", "bold"}:
                        raise ValueError("unsupported reference typography")
                    sample = BoardNode("", binding.role, 0, 0, width, height, "", fill, border, size, weight == "bold", (), color, kind)
                    if not validator._typography(text, sample):
                        raise ValueError("reference plain and rich typography disagree")
                    if height < size * (1 if binding.role == "title" else 2) + 12:
                        raise ValueError("reference node cannot contain two lines at its font size")
                else:
                    if binding.text_id:
                        raise ValueError("lane reference must not bind business text")
                    size, color, weight = 15, "#1f2329", "regular"
                if any(not re.fullmatch(r"#[0-9a-f]{6}", value) for value in (fill, border, color)):
                    raise ValueError("reference colors must be explicit RGB hex")
                styles.append(NativeNodeStyle(binding.role, width, height, fill, border, size, weight == "bold", color, kind))
            if not styles:
                raise ValueError("reference requires explicit native role bindings")
            dimensions = {(s.width, s.height) for s in styles if s.role in {"step", "control", "wait", "exit"}}
            if len(dimensions) > 1:
                raise ValueError("business reference nodes must use consistent dimensions")
            derived = tuple(sorted(styles, key=lambda s: s.role))
            if reference.node_styles and reference.node_styles != derived:
                raise ValueError("claimed reference styles disagree with native evidence")
            return replace(reference, node_styles=derived)
        except (ValueError, KeyError, TypeError) as exc:
            raise DevflowError("GATE_FAILED", str(exc), ExitCode.GATE_FAILED) from exc

    def _wrap(self, value, units=26):
        lines, current, width = [], "", 0
        for char in value.replace("\n", " "):
            size = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
            if width + size > units:
                lines.append(current)
                current, width = "", 0
            current += char
            width += size
        lines.append(current)
        if len(lines) > 2:
            raise DevflowError("EXTERNAL_UNAVAILABLE", "native node label exceeds two lines; supply a shorter evidence-backed business label", ExitCode.UNAVAILABLE)
        return "\n".join(lines)

    def build(self, model, reference, annotations, accepted_digest):
        scenes = []
        styles = {style.role: style for style in reference.node_styles}
        def styled(value):
            style = styles.get(value.role)
            if not style:
                return value
            return replace(value, width=value.width if value.role in {"lane", "header", "title"} else style.width,
                           height=value.height if value.role == "lane" else style.height,
                           fill=style.fill, border=style.border, font_size=style.font_size, bold=style.bold,
                           text_color=style.text_color, shape=style.shape)
        business_styles = [s for s in reference.node_styles if s.role in {"step", "control", "wait", "exit"}]
        node_width = business_styles[0].width if business_styles else 228
        node_height = business_styles[0].height if business_styles else 72
        lane_width = max([252, node_width + 24] + [s.width for s in reference.node_styles if s.role in {"lane", "header"}])
        pitch = lane_width + 28
        title_height = styles["title"].height if "title" in styles else 42
        header_y = max(80, title_height + 38)
        header_height = styles["header"].height if "header" in styles else 58
        labels = {label.target_id: label.label for label in annotations.labels}
        scopes = [_LayoutScope(s.scope.entry_id, labels.get(s.scope.symbol.symbol_id, s.scope.symbol.qualified_name), s.steps, s.controls,
                               s.sequence, s.contexts[0].context_id if s.contexts else "", s.control_flow, s.external) for s in model.scopes]
        if annotations.proposed_steps:
            requirements = {r.requirement_id: r for r in annotations.requirements}
            steps = tuple(FlowStep(p.step_id, "requirement-plan", "proposed", p.sender, p.receiver, p.label + " [需求方案]", "",
                                  tuple(segment for rid in p.requirement_ids for segment in requirements[rid].segment_ids)) for p in annotations.proposed_steps)
            tree = annotations.proposed_sequence or SequenceBlock(stable_id("B", "proposal", tuple(p.step_id for p in steps)), "sequence", "需求方案",
                                                                  (SequenceArm("", "", tuple(SequenceStep(p.step_id) for p in steps)),))
            controls = tuple(ControlNode(c.control_id, c.kind, "", c.exit_ids, (), c.exit_ids, c.condition, stable_id("B", c.control_id, "merge"), "",
                                         "requirement-plan", tuple(segment for rid in c.requirement_ids for segment in requirements[rid].segment_ids)) for c in annotations.proposed_controls)
            scopes.append(_LayoutScope("requirement-plan", "需求流程方案", steps, controls, tree, "requirement-plan"))
        if not scopes:
            raise DevflowError("EXTERNAL_UNAVAILABLE", "no native board units to publish", ExitCode.UNAVAILABLE)
        for scope in scopes:
            participants = sorted({s.receiver for s in scope.steps} | {s.sender for s in scope.steps}) or [scope.title]
            if len(participants) > 8 or len(scope.steps) > 120:
                raise DevflowError("EXTERNAL_UNAVAILABLE", "native layout requires smaller scopes (max 8 participants and 120 steps per board)", ExitCode.UNAVAILABLE)
            lane = {name: 40 + index * pitch for index, name in enumerate(participants)}
            width = max(320, len(participants) * pitch + 40)
            nodes, connections, positions = [], [], []
            steps = {step.step_id: step for step in scope.steps}
            controls = {node.control_id: node for node in scope.controls}
            context_owner = {step.context_id: step.sender for step in scope.steps}
            cursor = max(142, header_y + header_height + 4)
            counter = 0
            def node(identifier, role, caption, owner, evidence=()):
                nonlocal cursor
                colors = ("#fef1ce", "#d4b45b") if role in {"control", "wait", "exit"} else ("#f0f4fc", "#5178c6")
                value = styled(BoardNode(identifier, role, lane.get(owner, 40), cursor, node_width, node_height, "", *colors, 15, False, tuple(evidence)))
                units = max(1, int((value.width - 32) / (value.font_size * .55)))
                value = replace(value, text=self._wrap(caption, units if role in styles or business_styles else 26))
                nodes.append(value)
                cursor += value.height + 64
                return identifier
            def connect(start, end, caption="", target_ids=(), back=False):
                nonlocal counter
                if not start or not end:
                    return
                by_node = {value.node_id: value for value in nodes}
                source, target = by_node[start], by_node[end]
                bypass = source.x == target.x and abs(target.y - source.y) > 180
                counter += 1
                connections.append(BoardConnector(stable_id("L", scope.entry_id, counter), start, end,
                    "left" if back else "right" if bypass else "bottom",
                    "left" if back else "right" if bypass else "top", caption, tuple(target_ids)))
            def visit(values, incoming=(), context=""):
                ends = tuple(incoming)
                for item in values:
                    if not isinstance(item, SequenceBlock):
                        step = steps[item.step_id]
                        caption = labels.get(step.step_id, step.label)
                        ident = node(step.step_id, "wait" if step.kind in {"wait", "await"} else "step", caption,
                                     step.sender if step.kind == "call_return" else step.receiver, step.evidence_ids)
                        for previous in ends:
                            connect(previous, ident)
                        positions.append(DiagramPosition(step.step_id, scope.entry_id, ident, step.evidence_ids))
                        ends = () if step.kind in {"return", "raise", "throw", "panic"} and step.context_id == context else (ident,)
                        continue
                    control = controls[item.block_id]
                    caption = labels.get(item.block_id, control.condition or item.kind)
                    owner = context_owner.get(control.context_id, scope.title)
                    ident = node(item.block_id, "control", caption, owner, control.evidence_ids)
                    positions.append(DiagramPosition(item.block_id, scope.entry_id, ident, control.evidence_ids))
                    for previous in ends:
                        connect(previous, ident)
                    exits = []
                    for arm_index, arm in enumerate(item.arms):
                        exit_node = node(arm.exit_id, "exit", arm.label or "控制出口", owner, control.evidence_ids)
                        connect(ident, exit_node, arm.label, (arm.exit_id,))
                        positions.append(DiagramPosition(arm.exit_id, scope.entry_id, exit_node, control.evidence_ids))
                        branch_ends = visit(arm.items, (exit_node,), context)
                        if item.kind == "loop" and arm_index == 0:
                            for previous in branch_ends:
                                connect(previous, ident, "下一次迭代", (control.control_id,), True)
                        else:
                            exits.extend(branch_ends)
                    if exits:
                        merge = node(control.merge_id, "control", "控制合流", owner, control.evidence_ids)
                        for previous in exits:
                            connect(previous, merge)
                        ends = (merge,)
                    else:
                        ends = ()
                return ends
            root_context = scope.context_id
            visit(scope.sequence.arms[0].items, context=root_context)
            positions.extend(DiagramPosition(operation.operation_id, scope.entry_id, operation.call_site_id, operation.evidence_ids)
                             for operation in scope.operations)
            if scope.control_flow:
                # Nodes are laid out from the same tree; edges come from the
                # frozen graph so transfers and callee resumes stay exact.
                connections.clear()
                counter = 0
                visible = {n.node_id for n in nodes}
                outgoing = {}
                for edge in scope.control_flow:
                    outgoing.setdefault(edge.source_id, []).append(edge)
                reachable, pending = set(), [stable_id("G", root_context, "entry")]
                while pending:
                    identifier = pending.pop()
                    if identifier in reachable:
                        continue
                    reachable.add(identifier)
                    pending.extend(e.target_id for e in outgoing.get(identifier, ()))
                exit_labels = {arm.exit_id: arm.label for control in scope.controls for arm in self._arms(scope.sequence, control.control_id)}
                for source in sorted(visible & reachable):
                    for edge in outgoing.get(source, ()):
                        targets, pending, seen = [], [edge.target_id], set()
                        while pending:
                            target = pending.pop()
                            if target in seen:
                                continue
                            seen.add(target)
                            if target in visible:
                                targets.append(target)
                            else:
                                pending.extend(e.target_id for e in outgoing.get(target, ()))
                        for target in sorted(set(targets)):
                            caption = exit_labels.get(target, "") if edge.kind in {"arm", "fork"} else "下一次迭代" if edge.kind == "loopback" else edge.kind if edge.kind in {"break", "continue", "skip"} else ""
                            connect(source, target, caption, (target,) if caption else (),
                                    next(n.y for n in nodes if n.node_id == target) <= next(n.y for n in nodes if n.node_id == source))
                bound = {c.start_id for c in connections} | {c.end_id for c in connections}
                merges = {c.merge_id for c in scope.controls}
                nodes[:] = [n for n in nodes if n.node_id not in merges or n.node_id in bound]
            height = cursor + 40
            title = scope.title
            decorations = [styled(BoardNode(stable_id("N", scope.entry_id, "title"), "title", 20, 20, width - 40, 42, title,
                                     "#ffffff", "#ffffff", 26, True, ()))]
            for name, x in lane.items():
                decorations.extend((styled(BoardNode(stable_id("N", scope.entry_id, name, "lane"), "lane", x - 12, header_y, lane_width, height - header_y - 20,
                                              "", "#f6f8fc", "#dadde4", 15, False, ())),
                                    styled(BoardNode(stable_id("N", scope.entry_id, name, "header"), "header", x - 12, header_y, lane_width, 58,
                                              self._wrap(name, 32), "#f2f3f5", "#dadde4", 18, True, ()))))
            scenes.append(NativeBoardScene(scope.entry_id, title, width, height, tuple(decorations + nodes), tuple(connections), tuple(positions)))
        return NativeBoardBundle(tuple(scenes), accepted_digest, digest(reference))

    def _arms(self, tree, identifier):
        if tree.block_id == identifier:
            return tree.arms
        for arm in tree.arms:
            for item in arm.items:
                if isinstance(item, SequenceBlock):
                    found = self._arms(item, identifier)
                    if found:
                        return found
        return ()

    def dsl(self, scene):
        # Serialization boundary to the installed whiteboard-cli DSL, not raw OpenAPI invention.
        nodes = []
        for item in scene.nodes:
            value = {"id": item.node_id, "type": "text" if item.role == "title" else "frame" if item.role == "lane" else "rect",
                "x": item.x, "y": item.y, "width": item.width, "height": item.height,
                "fillColor": item.fill, "borderColor": item.border, "borderWidth": 2, "borderRadius": 8 if (item.shape or ("round_rect" if item.role in {"step", "wait", "control", "exit"} else "rect")) == "round_rect" else 0,
                "fontSize": item.font_size, "textColor": item.text_color, "textAlign": "center", "verticalAlign": "middle"}
            if item.bold:
                value["text"] = [{"content": item.text, "bold": True, "fontSize": item.font_size, "color": item.text_color}]
            else:
                value["text"] = item.text
            if item.role == "lane":
                value.update(layout="none", gap=0, padding=0, children=[])
            nodes.append(value)
        nodes += [{"type": "connector", "id": item.connector_id, "connector": {"from": item.start_id, "to": item.end_id,
                   "fromAnchor": item.start_anchor, "toAnchor": item.end_anchor, "lineShape": "polyline", "lineColor": "#000000",
                   "lineWidth": 2, "lineStyle": "solid", "startArrow": "none", "endArrow": "arrow", "label": item.caption}} for item in scene.connectors]
        return {"version": 2, "nodes": nodes}

    def normalize_native(self, scene, raw):
        """Correct a real converter export using the bound layout, never invent facts.

        OpenAPI board-v1 data-structure: group is a container; child coordinates
        are relative to parent_id. The converter omits that relationship and
        exports borderRadius=0 rectangles as round_rect.
        """
        nodes = deepcopy(FeishuStructureValidator()._nodes(raw))
        if any(node.get("parent_id") for node in nodes):
            raise DevflowError("GATE_FAILED", "normalize expects an original flat converter export", ExitCode.GATE_FAILED)
        for expected in scene.nodes:
            if expected.role != "title":
                shapes = [node for node in nodes if node.get("type") == "composite_shape" and
                          (node.get("x"), node.get("y"), node.get("width"), node.get("height")) ==
                          (expected.x, expected.y, expected.width, expected.height)]
                if len(shapes) != 1:
                    raise DevflowError("GATE_FAILED", "converter geometry does not uniquely match the bound layout", ExitCode.GATE_FAILED)
                shapes[0]["composite_shape"]["type"] = expected.shape or ("rect" if expected.role in {"header", "lane"} else "round_rect")
            if expected.text:
                texts = [node for node in nodes if node.get("type") == "text_shape" and
                         node.get("text", {}).get("text") == expected.text and node.get("x") == expected.x and
                         expected.y <= node.get("y", -1) < expected.y + expected.height]
                if len(texts) != 1:
                    raise DevflowError("GATE_FAILED", "converter text does not uniquely match the bound layout", ExitCode.GATE_FAILED)
                texts[0]["text"]["font_weight"] = "bold" if expected.bold else "regular"
        for node in nodes:
            if node.get("type") == "connector":
                for caption in node.get("connector", {}).get("captions", {}).get("data", []):
                    caption.update(font_size=14, font_weight="regular", horizontal_align="center", text_color="#1f2329")
        groups = []
        for lane in (node for node in scene.nodes if node.role == "lane"):
            group_id = stable_id("G", scene.scene_id, lane.node_id)
            if any(node.get("id") == group_id for node in nodes):
                raise DevflowError("GATE_FAILED", "native container ID collision", ExitCode.GATE_FAILED)
            groups.append({"id": group_id, "type": "group", "x": lane.x, "y": lane.y,
                           "width": lane.width, "height": lane.height})
            for node in nodes:
                if node.get("type") == "connector":
                    continue
                if (lane.x <= node.get("x", -1) and lane.y <= node.get("y", -1) and
                    node.get("x", -1) + node.get("width", 0) <= lane.x + lane.width and
                    node.get("y", -1) + node.get("height", 0) <= lane.y + lane.height):
                    node["parent_id"] = group_id
                    node["x"] -= lane.x
                    node["y"] -= lane.y
        return {"nodes": groups + nodes}


class FeishuStructureValidator:
    def _nodes(self, raw):
        value = json.loads(raw)
        if "nodes" not in value:
            value = value.get("data", {}).get("result", value.get("data", {}))
        if not isinstance(value.get("nodes"), list):
            raise DevflowError("GATE_FAILED", "native export lacks nodes", ExitCode.GATE_FAILED)
        return value["nodes"]

    def _absolute_nodes(self, nodes):
        by_id = {node["id"]: node for node in nodes}
        if len(by_id) != len(nodes):
            raise ValueError("duplicate native node IDs")
        def position(node, active=frozenset()):
            if node["id"] in active:
                raise ValueError("native container cycle")
            parent = node.get("parent_id")
            if not parent:
                return node.get("x", 0), node.get("y", 0)
            if parent not in by_id or by_id[parent].get("type") not in {"group", "section"}:
                raise ValueError("missing or invalid native container")
            x, y = position(by_id[parent], active | {node["id"]})
            return x + node.get("x", 0), y + node.get("y", 0)
        for node in nodes:
            if "children" in node and set(node["children"]) != {child["id"] for child in nodes if child.get("parent_id") == node["id"]}:
                raise ValueError("native container children conflict with parent bindings")
        return [{**node, "x": position(node)[0], "y": position(node)[1]} for node in nodes]

    def _typography(self, node, expected):
        text = node.get("text", {})
        wanted = {"font_size": expected.font_size, "font_weight": "bold" if expected.bold else "regular", "text_color": expected.text_color}
        if any(text.get(key) != value for key, value in wanted.items()) or text.get("horizontal_align") != "center":
            return False
        for paragraph in text.get("rich_text", {}).get("paragraphs", []):
            for element in paragraph.get("elements", []):
                style = element.get("text_element", {}).get("text_style", {})
                if any(style.get(key, value) != value for key, value in wanted.items()):
                    return False
        return True

    def _canonical_nodes(self, nodes):
        # Compare structure and bindings independent of remote/server-assigned IDs.
        absolute = {node["id"]: node for node in self._absolute_nodes(nodes)}
        ids = {node["id"]: index for index, node in enumerate(sorted(nodes, key=lambda n: (absolute[n["id"]].get("y", 0), absolute[n["id"]].get("x", 0), n.get("type", ""), digest(n.get("text", {})))))}
        def normalized(value, key=""):
            if isinstance(value, dict):
                return {name: normalized(item, name) for name, item in value.items() if name not in {"created_at", "updated_at", "creator", "revision", "children"}}
            if isinstance(value, list):
                return [normalized(item) for item in value]
            if key in {"id", "parent_id"}:
                return ids.get(value, value)
            return value
        return tuple(normalized(node) for node in sorted(nodes, key=lambda n: ids[n["id"]]))

    def validate(self, reference, exported, expected):
        # `exported` is a typed receipt with local/remote double-export evidence.
        rules = [RuleResult("feishu.scene_set", bool(expected.scenes) and len(exported.exports) == len(expected.scenes) and {s.scene_id for s in expected.scenes} == {e.scene_id for e in exported.exports}, "complete unique actual exports")]
        if reference.raw_path:
            try:
                raw = _read(reference.raw_path)
                _image(reference.preview_path, reference.preview_digest)
                derived = FeishuLayoutBuilder().reference_styles(reference, raw)
                valid = bytes_digest(raw) == reference.raw_digest and derived == reference and digest(reference) == expected.reference_digest
                rules.append(RuleResult("feishu.reference_evidence", valid, reference.source))
            except (OSError, ValueError, DevflowError) as exc:
                rules.append(RuleResult("feishu.reference_evidence", False, str(exc)))
        for scene in expected.scenes:
            evidence = next((item for item in exported.exports if item.scene_id == scene.scene_id), None)
            if evidence is None:
                rules.append(RuleResult("feishu.export_set", False, scene.scene_id))
                continue
            try:
                local_raw, remote_raw = _read(evidence.local_native_path), _read(evidence.remote_native_path)
                local, remote = self._nodes(local_raw), self._nodes(remote_raw)
                recorded = [obj for obj in exported.objects if obj.scene_id == scene.scene_id]
                rules.append(RuleResult("feishu.recorded_node_ids", len(recorded) == 1 and len(recorded[0].node_ids) == len(remote)
                                        and set(recorded[0].node_ids) == {node.get("id") for node in remote}, scene.scene_id))
                _image(evidence.local_preview_path, evidence.local_preview_digest)
                _image(evidence.remote_preview_path, evidence.remote_preview_digest)
                valid_digest = bytes_digest(local_raw) == evidence.local_native_digest and bytes_digest(remote_raw) == evidence.remote_native_digest
                rules.append(RuleResult("feishu.double_export", valid_digest, scene.scene_id))
                rules.append(RuleResult("feishu.native_structure", self._canonical_nodes(local) == self._canonical_nodes(remote), scene.scene_id))
                remote = self._absolute_nodes(remote)
                captions = [node for node in remote if node.get("type") == "connector"]
                shapes = [node for node in remote if node.get("type") in {"composite_shape", "basic_shape"}]
                texts = [node for node in remote if node.get("type") == "text_shape"]
                expected_text = {node.text for node in scene.nodes if node.text}
                actual_text = {node.get("text", {}).get("text", "") for node in texts}
                rules.append(RuleResult("feishu.node_text_coverage", expected_text <= actual_text, scene.scene_id))
                bound_shapes = {}
                for expected_node in scene.nodes:
                    if expected_node.role != "title":
                        matching = [n for n in shapes if (n.get("x"), n.get("y"), n.get("width"), n.get("height")) ==
                                    (expected_node.x, expected_node.y, expected_node.width, expected_node.height)]
                        correct = len(matching) == 1
                        if correct:
                            shape = matching[0]
                            bound_shapes[expected_node.node_id] = shape["id"]
                            style = shape.get("style", {})
                            correct = (style.get("fill_color", "").lower() == expected_node.fill
                                       and style.get("border_color", "").lower() == expected_node.border
                                       and style.get("border_style") == "solid"
                                       and style.get("border_width") == "narrow"
                                       and shape.get("composite_shape", {}).get("type") == (expected_node.shape or ("rect" if expected_node.role in {"header", "lane"} else "round_rect")))
                            parent = next((n for n in remote if n.get("id") == shape.get("parent_id")), None)
                            lane = next((n for n in scene.nodes if n.role == "lane" and n.x <= expected_node.x < n.x + n.width), None)
                            correct = correct and parent is not None and lane is not None and parent.get("type") == "group" and (
                                parent.get("x"), parent.get("y"), parent.get("width"), parent.get("height")) == (lane.x, lane.y, lane.width, lane.height)
                        rules.append(RuleResult("feishu.node_shape_style", correct, expected_node.node_id))
                    if expected_node.text:
                        matching_text = [n for n in texts if n.get("text", {}).get("text") == expected_node.text
                                         and n.get("x") == expected_node.x and expected_node.y <= n.get("y", -1) < expected_node.y + expected_node.height]
                        typography = len(matching_text) == 1 and self._typography(matching_text[0], expected_node)
                        rules.append(RuleResult("feishu.node_typography", typography, expected_node.node_id))
                remote_ids = {node.get("id") for node in remote}
                for node in captions:
                    connection, style = node.get("connector", {}), node.get("style", {})
                    start, end = connection.get("start", {}), connection.get("end", {})
                    bound = start.get("attached_object", {}).get("id") in remote_ids and end.get("attached_object", {}).get("id") in remote_ids
                    supported = connection.get("shape") == "polyline" and style.get("border_color", "").lower() == "#000000" and style.get("border_width") == "narrow" and style.get("border_style") == "solid"
                    arrow = start.get("arrow_style") == "none" and end.get("arrow_style") == "line_arrow"
                    caption_data = connection.get("captions", {}).get("data", [])
                    typography = all(c.get("font_size") == 14 and c.get("font_weight") == "regular" and c.get("horizontal_align") == "center" and c.get("text_color", "").lower() == "#1f2329" for c in caption_data)
                    rules.append(RuleResult("feishu.binding_caption_style", bound and supported and arrow and typography, node.get("id", "")))
                rules.append(RuleResult("feishu.connector_count", len(captions) == len(scene.connectors), scene.scene_id))
                for expected_connector in scene.connectors:
                    matches = [n for n in captions if n.get("connector", {}).get("start", {}).get("attached_object", {}).get("id") == bound_shapes.get(expected_connector.start_id)
                               and n.get("connector", {}).get("end", {}).get("attached_object", {}).get("id") == bound_shapes.get(expected_connector.end_id)]
                    valid = len(matches) == 1
                    if valid:
                        connection = matches[0]["connector"]
                        valid = (connection["start"]["attached_object"].get("snap_to") == expected_connector.start_anchor
                                 and connection["end"]["attached_object"].get("snap_to") == expected_connector.end_anchor
                                 and [c.get("text") for c in connection.get("captions", {}).get("data", [])] ==
                                     ([expected_connector.caption] if expected_connector.caption else []))
                    rules.append(RuleResult("feishu.expected_binding_caption", valid, expected_connector.connector_id))
                rules.append(RuleResult("feishu.visual_review", evidence.visual_review_passed and bool(evidence.visual_review_reference) and bool(evidence.comparison_reference), scene.scene_id))
            except (OSError, ValueError, KeyError, DevflowError) as exc:
                rules.append(RuleResult("feishu.export_read", False, str(exc)))
        return ValidationReport(tuple(rules))


class FeishuPublisher:
    def __init__(self, repository, builder, validator):
        self.repository, self.builder, self.validator = repository, builder, validator

    def _path(self, context, run_id, name):
        return self.repository.artifact_path(context, run_id, "publication/" + name)

    def _previous(self, request):
        """Follow accepted commit ancestry, never scan for a convenient publication."""
        current, seen = request.run_id, set()
        while current:
            if current in seen or len(seen) >= 100:
                raise DevflowError("GATE_FAILED", "accepted publication ancestry is cyclic or exceeds its limit", ExitCode.GATE_FAILED)
            seen.add(current)
            journal = self.repository.read_artifact(request.project, current, "commit_journal.json", CommitJournal)
            if journal.phase != "finalized" or journal.plan.run_id != current:
                raise DevflowError("GATE_FAILED", "publication ancestry is not finalized", ExitCode.GATE_FAILED)
            current = journal.plan.parent.accepted_run_id
            if not current:
                break
            self.repository.load(request.project, current)
            if not self._path(request.project, current, "manifest.json").exists():
                continue
            previous = self.repository.read_artifact(request.project, current, "publication/manifest.json", PublicationManifest)
            if (previous.target, previous.write_scope) != (request.target, request.write_scope):
                continue
            if previous.state != "verified":
                raise DevflowError("GATE_FAILED", "finish or reconcile the previous remote publication before updating it", ExitCode.GATE_FAILED)
            receipt = self.repository.read_artifact(request.project, current, "publication/receipt.json", PublicationReceipt)
            layout = self.repository.read_artifact(request.project, current, "publication/layout.json", NativeBoardBundle)
            parent = journal.plan.parent
            if (previous.run_id != current or previous.accepted_digest != parent.verified_digest
                or previous.layout_digest != digest(layout) or layout.accepted_digest != previous.accepted_digest
                or previous.publication_id != digest((previous.accepted_digest, previous.target, previous.write_scope, digest(previous.reference)))
                or (receipt.publication_id, receipt.accepted_digest, receipt.target, receipt.write_scope, receipt.layout_digest, receipt.objects) !=
                   (previous.publication_id, previous.accepted_digest, previous.target, previous.write_scope, previous.layout_digest, previous.objects)):
                raise DevflowError("GATE_FAILED", "previous publication is not bound to the accepted parent", ExitCode.GATE_FAILED)
            if not self.validator.validate(previous.reference, receipt, layout).passed:
                raise DevflowError("GATE_FAILED", "previous remote ownership evidence has changed", ExitCode.GATE_FAILED)
            return previous, receipt
        return None

    def prepare(self, request, manifest, baseline):
        if manifest.state != RunState.ACCEPTED or baseline.accepted_run_id != request.run_id:
            raise DevflowError("GATE_FAILED", "publish requires the active accepted baseline", ExitCode.GATE_FAILED)
        if not request.target or not request.write_scope or not request.execution_approval:
            raise DevflowError("AUTHORIZATION_REQUIRED", "publish needs explicit target, write scope and authorization reference", ExitCode.UNAUTHORIZED)
        if request.reference_path:
            reference = from_dict(ReferenceBundle, json.loads(_read(request.reference_path)))
            for path in (reference.raw_path, reference.preview_path):
                confined(Path(path), request.reference_path.parent)
            if bytes_digest(_read(reference.raw_path)) != reference.raw_digest:
                raise DevflowError("GATE_FAILED", "reference raw export changed", ExitCode.GATE_FAILED)
            _image(reference.preview_path, reference.preview_digest)
            reference = self.builder.reference_styles(reference, _read(reference.raw_path))
        else:
            reference = ReferenceBundle("builtin:sequence-default-style-v1", "", "", "", "", "", "builtin-style-policy")
        model = self.repository.read_artifact(request.project, request.run_id, "flow-model.json", FlowModel)
        annotations = self.repository.read_artifact(request.project, request.run_id, "annotations.json", SemanticAnnotations)
        layout = self.builder.build(model, reference, annotations, baseline.verified_digest)
        identity = digest((baseline.verified_digest, request.target, request.write_scope, digest(reference)))
        path = self._path(request.project, request.run_id, "manifest.json")
        if path.exists():
            existing = self.repository.read_artifact(request.project, request.run_id, "publication/manifest.json", PublicationManifest)
            if existing.publication_id != identity or existing.layout_digest != digest(layout):
                raise DevflowError("GATE_FAILED", "publication target/reference changed; do not overwrite recorded remote objects", ExitCode.GATE_FAILED)
            return DomainCommandResult(existing.state, {"publication_id": identity, "state": existing.state, "objects": existing.objects}, str(path))
        previous = self._previous(request)
        if previous and previous[0].publication_id == identity and previous[0].layout_digest == digest(layout):
            inherited = replace(previous[0], run_id=request.run_id)
            self.repository.write_artifact(request.project, request.run_id, "publication/layout.json", layout)
            self.repository.write_artifact(request.project, request.run_id, "publication/receipt.json", previous[1])
            self.repository.write_artifact(request.project, request.run_id, "publication/manifest.json", inherited)
            return DomainCommandResult("verified", {"publication_id": identity, "state": "verified", "target": request.target,
                                       "online_verified": True, "reused": True}, str(path))
        publication = PublicationManifest(identity, request.run_id, baseline.verified_digest, request.target, request.write_scope,
            request.execution_approval, reference, digest(layout), "prepared", (), "", (),
            previous[0].publication_id if previous else "", previous[1].remote_after_digest if previous else "",
            previous[0].objects if previous else ())
        self.repository.write_artifact(request.project, request.run_id, "publication/layout.json", layout)
        for index, scene in enumerate(layout.scenes):
            self.repository.write_artifact(request.project, request.run_id, f"publication/scene-{index}.dsl.json", self.builder.dsl(scene))
        self.repository.write_artifact(request.project, request.run_id, "publication/host-task.json", {
            "publication": to_dict(publication), "layout_path": str(self._path(request.project, request.run_id, "layout.json")),
            "receipt_contract": "sequence-diagram-generator.publication-receipt", "steps": [
                "Render the same DSL locally with an installed absolute whiteboard-cli; retain PNG and native export.",
                ("Review geometry and the explicitly supplied reference side by side; never drop branch/loop/await relationships."
                 if request.reference_path else
                 "Review geometry against the built-in default style and layout.json; no online reference is required. Never drop branch/loop/await relationships."),
                "Use installed FeishuLayoutBuilder.normalize_native(scene, converter_raw) to restore lane containers, rect headers, bold typography and center/14px/regular captions. Retain normalized local native JSON and the preview of the same DSL layout; publish this normalized native structure.",
                "Read remote objects before every write/retry. If expected_remote_digest is set, the actual target scope digest must equal it before an update. Only update matching owned_objects board/node IDs. Preserve retired scenes and all unregistered objects; create new scene objects only within the authorized scope. Changed or uncertain writes require reconciliation, not duplicate insertion.",
                "Write only the authorized target scope, immediately collect a written receipt with object IDs and digest.",
                "Double-export online preview and native structure, visually review, then collect the verified receipt.",
                "Do not overwrite user objects, use SVG fallback, or treat a simulated/local result as online success."]})
        self.repository.write_artifact(request.project, request.run_id, "publication/manifest.json", publication)
        return DomainCommandResult("prepared", {"publication_id": identity, "state": "prepared", "online_verified": False}, str(path))

    def collect(self, request, publication, active_baseline=True):
        if not request.receipt_path:
            raise DevflowError("INVALID_ARGUMENT", "publish collect requires --receipt", ExitCode.ARGUMENT)
        receipt = from_dict(PublicationReceipt, json.loads(_read(request.receipt_path)))
        if not active_baseline:
            # A superseded run can finish reviewing an already recorded write,
            # but cannot attest a fresh write or change its remote outcome.
            if not publication.objects or receipt.status != "verified":
                raise DevflowError("GATE_FAILED", "new remote writes require the active accepted baseline", ExitCode.GATE_FAILED)
            previous = self.repository.read_artifact(request.project, request.run_id, "publication/receipt.json", PublicationReceipt)
            fields = ("objects", "remote_revision", "remote_precondition_digest", "remote_after_digest", "write_tool_references")
            if any(getattr(receipt, field) != getattr(previous, field) for field in fields):
                raise DevflowError("GATE_FAILED", "superseded publication may only review the already recorded remote write", ExitCode.GATE_FAILED)
        for export in receipt.exports:
            for path in (export.local_native_path, export.local_preview_path, export.remote_native_path, export.remote_preview_path):
                confined(Path(path), request.receipt_path.parent)
        if (receipt.publication_id, receipt.accepted_digest, receipt.target, receipt.write_scope, receipt.execution_approval, receipt.layout_digest) != (
            publication.publication_id, publication.accepted_digest, publication.target, publication.write_scope, publication.execution_approval, publication.layout_digest):
            raise DevflowError("GATE_FAILED", "publication receipt identity, scope or authorization changed", ExitCode.GATE_FAILED)
        if publication.state == "verified":
            previous = self.repository.read_artifact(request.project, request.run_id, "publication/receipt.json", PublicationReceipt)
            if digest(previous) != digest(receipt):
                raise DevflowError("GATE_FAILED", "different receipt for verified publication", ExitCode.GATE_FAILED)
            return DomainCommandResult("verified", {"publication_id": publication.publication_id, "target": publication.target, "online_verified": True}, str(self._path(request.project, request.run_id, "manifest.json")))
        if publication.objects and publication.objects != receipt.objects:
            raise DevflowError("GATE_FAILED", "retry attempted to replace recorded remote object identities", ExitCode.GATE_FAILED)
        if publication.expected_remote_digest and receipt.remote_precondition_digest != publication.expected_remote_digest:
            raise DevflowError("GATE_FAILED", "remote precondition differs from the accepted parent publication", ExitCode.GATE_FAILED)
        owned = {item.scene_id: item for item in publication.owned_objects}
        by_board = {item.board_id: item.scene_id for item in publication.owned_objects}
        for item in receipt.objects:
            if (item.scene_id in owned and item.board_id != owned[item.scene_id].board_id
                or item.board_id in by_board and by_board[item.board_id] != item.scene_id):
                raise DevflowError("GATE_FAILED", "new revision attempted to replace or reassign owned remote boards", ExitCode.GATE_FAILED)
        if not receipt.objects or not receipt.write_tool_references or not receipt.remote_after_digest or receipt.status not in {"written", "verified", "failed"}:
            raise DevflowError("GATE_FAILED", "remote write records are incomplete", ExitCode.GATE_FAILED)
        layout = self.repository.read_artifact(request.project, request.run_id, "publication/layout.json", NativeBoardBundle)
        if (len({o.scene_id for o in receipt.objects}) != len(receipt.objects)
            or {o.scene_id for o in receipt.objects} != {s.scene_id for s in layout.scenes}
            or len({o.board_id for o in receipt.objects}) != len(receipt.objects)
            or not receipt.remote_revision or not receipt.remote_precondition_digest
            or any(not o.board_id or not o.node_ids or len(set(o.node_ids)) != len(o.node_ids)
                   or o.written_digest != digest(next(s for s in layout.scenes if s.scene_id == o.scene_id)) for o in receipt.objects)):
            raise DevflowError("GATE_FAILED", "remote object identity, scope or written content is incomplete", ExitCode.GATE_FAILED)
        updated = replace(publication, state="written", objects=receipt.objects, remote_revision=receipt.remote_revision)
        self.repository.write_artifact(request.project, request.run_id, "publication/manifest.json", updated)
        self.repository.write_artifact(request.project, request.run_id, "publication/receipt.json", receipt)
        report = self.validator.validate(publication.reference, receipt, layout)
        self.repository.write_artifact(request.project, request.run_id, "publication/validation.json", report)
        if receipt.status == "verified" and report.passed:
            updated = replace(updated, state="verified")
            self.repository.write_artifact(request.project, request.run_id, "publication/manifest.json", updated)
            return DomainCommandResult("verified", {"publication_id": publication.publication_id, "target": publication.target, "online_verified": True}, str(self._path(request.project, request.run_id, "manifest.json")))
        if receipt.status != "written":
            self.repository.write_artifact(request.project, request.run_id, "publication/manifest.json", replace(updated, state="failed", diagnostics=("online structure/visual verification incomplete",)))
            raise DevflowError("GATE_FAILED", "remote write recorded, online structure/visual verification failed", ExitCode.GATE_FAILED,
                               details_path=str(self._path(request.project, request.run_id, "validation.json")))
        return DomainCommandResult("written", {"publication_id": publication.publication_id, "online_verified": False}, str(self._path(request.project, request.run_id, "manifest.json")))

    def check(self, request, publication):
        receipt = self.repository.read_artifact(request.project, request.run_id, "publication/receipt.json", PublicationReceipt)
        layout = self.repository.read_artifact(request.project, request.run_id, "publication/layout.json", NativeBoardBundle)
        report = self.validator.validate(publication.reference, receipt, layout)
        if not report.passed or publication.state != "verified":
            raise DevflowError("GATE_FAILED", "saved online publication evidence does not verify", ExitCode.GATE_FAILED,
                               details_path=str(self._path(request.project, request.run_id, "manifest.json")))
        return DomainCommandResult("verified", {"publication_id": publication.publication_id, "online_verified": True, "target": publication.target, "report": report}, str(self._path(request.project, request.run_id, "manifest.json")))
