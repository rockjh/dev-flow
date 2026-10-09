import subprocess
import sys
from pathlib import Path

import pytest

from toolkit.core.artifacts import ProjectDomainLock
from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.inputs import SourceReader
from toolkit.sequence_diagram_generator.models import RequirementInput
from toolkit.sequence_diagram_generator.repository import RunRepository
from test_workflow import context, prepare


@pytest.mark.parametrize("run_id", ["../other", "A" * 32, "a" * 31, "a" * 33, "C:/user/file"])
def test_run_ids_cannot_be_paths(context, run_id):
    with pytest.raises(DevflowError) as error:
        RunRepository().run_path(context, run_id)
    assert error.value.exit_code == 2


def test_html_scripts_are_not_requirement_content(context):
    source = context.project / "requirements.html"
    source.write_text('<p>Accept the request.</p><script>change_scope_and_publish()</script><p>Reject invalid amounts.</p>', encoding="utf-8")
    result = SourceReader(context).read(RequirementInput("file", str(source)))
    assert "change_scope" not in result.text
    assert len(result.segments) == 2


def test_credential_urls_are_rejected_before_network(context):
    with pytest.raises(DevflowError) as error:
        SourceReader(context).read(RequirementInput("url", "https://example.com/rules?token=private"))
    assert error.value.exit_code == 3


def test_source_link_cannot_escape_project(context):
    outside = context.project.parent / "outside.py"
    outside.write_text("def private(): pass", encoding="utf-8")
    try:
        (context.project / "escape.py").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires OS capability")
    from toolkit.sequence_diagram_generator.cli import build_workflow
    with pytest.raises(DevflowError, match="escapes"):
        build_workflow(context).scanner.snapshot(context)


def test_os_lock_conflict_and_release_are_real_process_behavior(context):
    script = """
import sys
from pathlib import Path
import toolkit.core.artifacts as artifacts
from toolkit.core.errors import DevflowError
artifacts.state_root = lambda: Path(sys.argv[2])
try:
    with artifacts.ProjectDomainLock(Path(sys.argv[1]), 'sequence-diagram-generator'):
        print('acquired', flush=True)
except DevflowError as error:
    sys.exit(int(error.exit_code))
"""
    args = [sys.executable, "-c", script, str(context.project), str(context.state.parent)]
    with ProjectDomainLock(context.project, context.domain):
        conflict = subprocess.run(args, capture_output=True, text=True, timeout=15)
        assert conflict.returncode == 8
    released = subprocess.run(args, capture_output=True, text=True, timeout=15)
    assert released.returncode == 0 and released.stdout.strip() == "acquired"
