"""Actual local converter fixture; all publication receipts here are synthetic."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import struct
import zlib

import pytest

from toolkit.sequence_diagram_generator.feishu import FeishuLayoutBuilder, FeishuStructureValidator, _image
from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.models import BoardExport, FlowModel, ReferenceBundle, PublicationReceipt, PublishedObject, SemanticAnnotations
from toolkit.sequence_diagram_generator.repository import bytes_digest, digest
from test_boundaries import analyze


@pytest.fixture
def native(tmp_path):
    scope = analyze("python", "def flow(x):\n if x: return True\n return False\n")
    reference = ReferenceBundle("builtin", "", "", "", "", "", "synthetic-test")
    builder = FeishuLayoutBuilder()
    layout = builder.build(FlowModel((scope,), "", ""), reference, SemanticAnnotations((), (), (), (), ()), "synthetic")
    raw = (Path(__file__).parent / "fixtures/whiteboard-cli-0.2.13.json").read_bytes()
    normalized = builder.normalize_native(layout.scenes[0], raw)
    preview = tmp_path / "synthetic-preview.png"
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    preview.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))
    local, remote = tmp_path / "local.json", tmp_path / "remote.json"
    value = json.dumps(normalized).encode()
    local.write_bytes(value)
    remote.write_bytes(value)
    exported = BoardExport(layout.scenes[0].scene_id, str(local), str(preview), str(remote), str(preview),
                           bytes_digest(value), bytes_digest(preview.read_bytes()), bytes_digest(value), bytes_digest(preview.read_bytes()),
                           "synthetic-review", True, "synthetic-comparison")
    objects = (PublishedObject(layout.scenes[0].scene_id, "synthetic-board", tuple(n["id"] for n in normalized["nodes"]), digest(layout.scenes[0])),)
    receipt = PublicationReceipt("synthetic", "synthetic", "synthetic", "synthetic", "synthetic", "synthetic", objects, "synthetic",
                                 (exported,), "verified", "synthetic", "synthetic", ("synthetic",))
    return reference, layout, normalized, receipt


def validate_changed(native, value):
    reference, layout, _, receipt = native
    export = receipt.exports[0]
    data = json.dumps(value).encode()
    # Make both exports agree: expected-layout validation must still catch damage.
    Path(export.local_native_path).write_bytes(data)
    Path(export.remote_native_path).write_bytes(data)
    receipt = replace(receipt, exports=(replace(export, local_native_digest=bytes_digest(data), remote_native_digest=bytes_digest(data)),))
    return FeishuStructureValidator().validate(reference, receipt, layout)


def test_actual_converter_output_normalizes_and_preserves_structure(native):
    reference, layout, normalized, receipt = native
    result = FeishuStructureValidator().validate(reference, receipt, layout)
    assert result.passed, [r for r in result.rules if not r.passed]
    groups = {n["id"] for n in normalized["nodes"] if n["type"] == "group"}
    assert groups and all(n.get("parent_id") in groups for n in normalized["nodes"] if n["type"] == "composite_shape")


def test_png_magic_without_real_chunks_is_rejected(tmp_path):
    path = tmp_path / "fake.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot an exported preview")
    with pytest.raises(DevflowError, match="structurally valid"):
        _image(path, bytes_digest(path.read_bytes()))


@pytest.mark.parametrize("damage", ["container", "header", "bold", "caption", "binding"])
def test_matching_local_remote_damage_still_fails_expected_structure(native, damage):
    value = deepcopy(native[2])
    if damage == "container":
        next(n for n in value["nodes"] if n["type"] == "composite_shape").pop("parent_id")
    elif damage == "header":
        next(n for n in value["nodes"] if n.get("height") == 58 and n["type"] == "composite_shape")["composite_shape"]["type"] = "round_rect"
    elif damage == "bold":
        next(n for n in value["nodes"] if n["type"] == "text_shape")["text"]["rich_text"]["paragraphs"][0]["elements"][0]["text_element"]["text_style"]["font_weight"] = "regular"
    elif damage == "caption":
        next(n for n in value["nodes"] if n["type"] == "connector" and n["connector"].get("captions"))["connector"]["captions"]["data"][0]["font_size"] = 10
    else:
        next(n for n in value["nodes"] if n["type"] == "connector")["connector"]["end"]["attached_object"]["id"] = "missing"
    assert not validate_changed(native, value).passed


def test_remote_server_ids_and_derived_children_are_not_semantic_changes(native):
    reference, layout, value, receipt = native
    mapping = {n["id"]: "remote-" + str(i) for i, n in enumerate(value["nodes"])}
    def rename(item, key=""):
        if isinstance(item, dict):
            return {k: rename(v, k) for k, v in item.items()}
        if isinstance(item, list):
            return [rename(v) for v in item]
        return mapping.get(item, item) if key in {"id", "parent_id"} else item
    remote = rename(value)
    for node in remote["nodes"]:
        if node["type"] == "group":
            node["children"] = [child["id"] for child in remote["nodes"] if child.get("parent_id") == node["id"]]
    export = receipt.exports[0]
    data = json.dumps(remote).encode()
    Path(export.remote_native_path).write_bytes(data)
    receipt = replace(receipt, exports=(replace(export, remote_native_digest=bytes_digest(data)),))
    receipt = replace(receipt, objects=(replace(receipt.objects[0], node_ids=tuple(n["id"] for n in remote["nodes"])),))
    result = FeishuStructureValidator().validate(reference, receipt, layout)
    assert result.passed, [r for r in result.rules if not r.passed]
