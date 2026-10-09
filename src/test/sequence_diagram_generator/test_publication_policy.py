"""Publication preparation uses local policy without fetching reference links."""
from unittest.mock import patch

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.models import AcceptRequest, PublicationManifest, PublishRequest
from test_acceptance import context, verified
from test_native_structure import native


def test_prepare_uses_builtin_style_without_reading_reference(context):
    flow, run_id = verified(context)
    flow.accept(AcceptRequest(context, run_id))
    request = PublishRequest(context, run_id, "prepare", "explicit-test-target", "new-board-only", "test-session-approval")
    with patch("toolkit.sequence_diagram_generator.feishu._read", side_effect=AssertionError("reference must not be read")):
        result = flow.publish(request)
    assert result.summary == "prepared" and not result.data["online_verified"]
    publication = flow.repository.read_artifact(context, run_id, "publication/manifest.json", PublicationManifest)
    assert publication.reference.source == "builtin:sequence-default-style-v1"
    assert not publication.reference.raw_path and not publication.reference.preview_path


def test_default_style_does_not_remove_write_authorization(context):
    flow, run_id = verified(context)
    flow.accept(AcceptRequest(context, run_id))
    with pytest.raises(DevflowError) as error:
        flow.publish(PublishRequest(context, run_id, "prepare", "explicit-test-target", "new-board-only"))
    assert error.value.exit_code == 7
    assert not flow.repository.artifact_path(context, run_id, "publication/manifest.json").exists()


def test_explicit_invalid_reference_is_not_silently_replaced(context):
    flow, run_id = verified(context)
    flow.accept(AcceptRequest(context, run_id))
    reference = context.project / "explicit-reference.json"
    reference.write_text("{}", encoding="utf-8")
    with pytest.raises(DevflowError):
        flow.publish(PublishRequest(context, run_id, "prepare", "explicit-test-target", "new-board-only", "test-session-approval", reference))
    assert not flow.repository.artifact_path(context, run_id, "publication/manifest.json").exists()


def test_valid_reference_derives_styles_from_bound_native_nodes(context, native):
    from dataclasses import replace
    import json
    from pathlib import Path
    from toolkit.sequence_diagram_generator.repository import to_dict
    from toolkit.sequence_diagram_generator.models import NativeStyleBinding, NativeBoardBundle
    from toolkit.sequence_diagram_generator.feishu import FeishuStructureValidator
    flow, run_id = verified(context)
    flow.accept(AcceptRequest(context, run_id))
    exported = native[3].exports[0]
    reference = replace(native[0], raw_path=exported.local_native_path, preview_path=exported.local_preview_path,
                        raw_digest=exported.local_native_digest, preview_digest=exported.local_preview_digest)
    nodes = FeishuStructureValidator()._absolute_nodes(native[2]["nodes"])
    shape = next(n for n in nodes if n["type"] == "composite_shape" and n["height"] == 72)
    text = next(n for n in nodes if n["type"] == "text_shape" and n["x"] == shape["x"] and shape["y"] <= n["y"] < shape["y"] + 72)
    reference = replace(reference, style_bindings=(NativeStyleBinding("control", shape["id"], text["id"]),))
    path = Path(exported.local_native_path).parent / "synthetic-reference.json"
    path.write_text(json.dumps(to_dict(reference)), encoding="utf-8")
    result = flow.publish(PublishRequest(context, run_id, "prepare", "synthetic-target", "new-board-only", "synthetic-approval", path))
    assert result.summary == "prepared" and not result.data["online_verified"]
    publication = flow.repository.read_artifact(context, run_id, "publication/manifest.json", PublicationManifest)
    layout = flow.repository.read_artifact(context, run_id, "publication/layout.json", NativeBoardBundle)
    assert publication.reference.node_styles[0].fill == shape["style"]["fill_color"]
    assert all(n.fill == shape["style"]["fill_color"] for s in layout.scenes for n in s.nodes if n.role == "control")
