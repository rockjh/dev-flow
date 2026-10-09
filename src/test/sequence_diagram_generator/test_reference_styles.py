"""Reference exports here are synthetic style variations of the actual converter fixture."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.feishu import FeishuLayoutBuilder, FeishuStructureValidator
from toolkit.sequence_diagram_generator.models import NativeStyleBinding, FlowModel, SemanticAnnotations
from test_native_structure import native
from test_boundaries import analyze


def sample(native):
    nodes = FeishuStructureValidator()._absolute_nodes(deepcopy(native[2]["nodes"]))
    shape = next(n for n in nodes if n["type"] == "composite_shape" and n["height"] == 72)
    text = next(n for n in nodes if n["type"] == "text_shape" and n["x"] == shape["x"] and shape["y"] <= n["y"] < shape["y"] + 72)
    # Flatten the test export after calculating actual coordinates.
    for n in nodes:
        n.pop("parent_id", None)
    reference = replace(native[0], style_bindings=(NativeStyleBinding("step", shape["id"], text["id"]),))
    return reference, nodes, shape, text


def test_reference_dimensions_typography_and_colors_reflow_layout(native):
    reference, nodes, shape, text = sample(native)
    shape.update(width=300, height=96)
    shape["style"].update(fill_color="#dff5e5", border_color="#509863")
    text["text"].update(font_size=18, text_color="#223344")
    for p in text["text"].get("rich_text", {}).get("paragraphs", []):
        for e in p["elements"]:
            e["text_element"]["text_style"].update(font_size=18, text_color="#223344")
    builder = FeishuLayoutBuilder()
    derived = builder.reference_styles(reference, json.dumps({"nodes": nodes}))
    model = FlowModel((analyze("python", "def flow(x):\n if x: return True\n return False\n"),), "", "")
    scene = builder.build(model, derived, SemanticAnnotations((), (), (), (), ()), "synthetic").scenes[0]
    steps = [n for n in scene.nodes if n.role == "step"]
    assert steps and all((n.width, n.height, n.font_size, n.text_color, n.fill) == (300, 96, 18, "#223344", "#dff5e5") for n in steps)
    assert all(n.width >= 324 for n in scene.nodes if n.role == "lane")
    ordered = sorted((n for n in scene.nodes if n.role not in {"title", "header", "lane"}), key=lambda n: n.y)
    assert all(a.y + a.height < b.y for a, b in zip(ordered, ordered[1:]))
    dsl = builder.dsl(scene)
    assert next(n for n in dsl["nodes"] if n["id"] == steps[0].node_id)["textColor"] == "#223344"


@pytest.mark.parametrize("damage", ["missing", "role", "rich", "binding", "shape", "claimed"])
def test_reference_conflicts_fail_instead_of_defaulting(native, damage):
    reference, nodes, shape, text = sample(native)
    if damage == "missing":
        reference = replace(reference, style_bindings=())
    elif damage == "role":
        reference = replace(reference, style_bindings=(replace(reference.style_bindings[0], role="guessed"),))
    elif damage == "rich":
        text["text"]["rich_text"] = {"paragraphs": [{"elements": [{"text_element": {"text_style": {"font_size": 20}}}]}]}
    elif damage == "binding":
        text["x"] += 100
    elif damage == "shape":
        shape["composite_shape"]["type"] = "diamond"
    else:
        derived = FeishuLayoutBuilder().reference_styles(reference, json.dumps({"nodes": nodes}))
        reference = replace(derived, node_styles=(replace(derived.node_styles[0], fill="#ffffff"),))
    with pytest.raises(DevflowError):
        FeishuLayoutBuilder().reference_styles(reference, json.dumps({"nodes": nodes}))
